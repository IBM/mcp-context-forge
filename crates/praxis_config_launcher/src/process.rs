use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use std::os::unix::process::CommandExt as _;

use nix::errno::Errno;
use nix::sys::signal::{Signal, killpg};
use nix::sys::wait::{WaitPidFlag, WaitStatus, waitpid};
use nix::unistd::Pid;
use tokio::process::{Child, Command};
use tokio::time::{Instant, sleep};

use crate::error::LauncherError;

pub const TERM_GRACE: Duration = Duration::from_secs(30);
pub const KILL_GRACE: Duration = Duration::from_secs(5);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessSpec {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}

impl ProcessSpec {
    #[must_use]
    pub fn praxis(program: impl AsRef<Path>) -> Self {
        Self {
            program: program.as_ref().to_path_buf(),
            args: vec!["--config".into(), "praxis.yaml".into()],
        }
    }
}

#[derive(Debug)]
pub struct ManagedProcess {
    child: Child,
    process_group: Pid,
}

impl ManagedProcess {
    pub fn spawn(spec: &ProcessSpec, cwd: &Path) -> Result<Self, LauncherError> {
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(cwd)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        command.as_std_mut().process_group(0);
        let child = command
            .spawn()
            .map_err(|_| LauncherError::Process("failed to spawn Praxis session"))?;
        let raw_pid = child
            .id()
            .and_then(|value| i32::try_from(value).ok())
            .ok_or(LauncherError::Process("spawned Praxis has no valid PID"))?;
        Ok(Self {
            child,
            process_group: Pid::from_raw(raw_pid),
        })
    }

    pub fn try_wait(&mut self) -> Result<Option<std::process::ExitStatus>, LauncherError> {
        self.child
            .try_wait()
            .map_err(|_| LauncherError::Process("failed to inspect Praxis process"))
    }

    #[must_use]
    pub const fn process_group(&self) -> Pid {
        self.process_group
    }

    pub async fn stop(self) -> Result<(), LauncherError> {
        self.stop_with_grace(TERM_GRACE, KILL_GRACE).await
    }

    pub async fn stop_with_grace(
        mut self,
        term_grace: Duration,
        kill_grace: Duration,
    ) -> Result<(), LauncherError> {
        signal_group(self.process_group, Signal::SIGTERM)?;
        if !wait_group(&mut self.child, self.process_group, term_grace).await? {
            signal_group(self.process_group, Signal::SIGKILL)?;
            if !wait_group(&mut self.child, self.process_group, kill_grace).await? {
                return Err(LauncherError::Process("Praxis process group did not exit"));
            }
        }
        reap_adopted_children()?;
        Ok(())
    }
}

impl Drop for ManagedProcess {
    fn drop(&mut self) {
        let _ = signal_group(self.process_group, Signal::SIGKILL);
        let _ = self.child.start_kill();
        let _ = reap_adopted_children();
    }
}

pub fn become_subreaper() -> Result<(), LauncherError> {
    #[cfg(target_os = "linux")]
    nix::sys::prctl::set_child_subreaper(true)
        .map_err(|_| LauncherError::Process("failed to become child subreaper"))?;
    Ok(())
}

fn signal_group(group: Pid, signal: Signal) -> Result<(), LauncherError> {
    match killpg(group, signal) {
        Ok(()) | Err(Errno::ESRCH) => Ok(()),
        Err(_) => Err(LauncherError::Process(
            "failed to signal Praxis process group",
        )),
    }
}

async fn wait_group(child: &mut Child, group: Pid, grace: Duration) -> Result<bool, LauncherError> {
    let deadline = Instant::now() + grace;
    loop {
        let leader_exited = child
            .try_wait()
            .map_err(|_| LauncherError::Process("failed to reap Praxis process"))?
            .is_some();
        reap_adopted_children()?;
        if leader_exited && !group_exists(group)? {
            return Ok(true);
        }
        if Instant::now() >= deadline {
            return Ok(false);
        }
        sleep(Duration::from_millis(10)).await;
    }
}

fn group_exists(group: Pid) -> Result<bool, LauncherError> {
    match nix::sys::signal::kill(Pid::from_raw(-group.as_raw()), None) {
        Ok(()) | Err(Errno::EPERM) => Ok(true),
        Err(Errno::ESRCH) => Ok(false),
        Err(_) => Err(LauncherError::Process(
            "failed to inspect Praxis process group",
        )),
    }
}

fn reap_adopted_children() -> Result<(), LauncherError> {
    loop {
        match waitpid(Pid::from_raw(-1), Some(WaitPidFlag::WNOHANG)) {
            Ok(WaitStatus::StillAlive) | Err(Errno::ECHILD) => return Ok(()),
            Ok(_) => {}
            Err(_) => return Err(LauncherError::Process("failed to reap adopted child")),
        }
    }
}
