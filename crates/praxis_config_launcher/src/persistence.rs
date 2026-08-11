use std::fs::{self, File, OpenOptions};
use std::io::Write as _;
use std::os::unix::fs::{OpenOptionsExt as _, PermissionsExt as _};
use std::path::{Path, PathBuf};

use crate::error::LauncherError;
use crate::state::SupervisorState;

#[derive(Clone, Debug)]
pub struct StateStore {
    path: PathBuf,
}

impl StateStore {
    #[must_use]
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self {
            path: path.as_ref().to_path_buf(),
        }
    }

    pub fn load(&self) -> Result<SupervisorState, LauncherError> {
        self.cleanup_temporary()?;
        if !self.path.exists() {
            return Ok(SupervisorState::new());
        }
        let metadata = fs::symlink_metadata(&self.path)
            .map_err(|source| io_error("inspect state", &self.path, source))?;
        if !metadata.file_type().is_file() || metadata.permissions().mode() & 0o777 != 0o600 {
            return Err(LauncherError::State(
                "persisted state permissions are invalid",
            ));
        }
        let bytes =
            fs::read(&self.path).map_err(|source| io_error("read state", &self.path, source))?;
        let mut state: SupervisorState = serde_json::from_slice(&bytes)
            .map_err(|_| LauncherError::State("persisted state is corrupt"))?;
        state.validate_recovered().map_err(LauncherError::State)?;
        state.make_unready();
        Ok(state)
    }

    pub fn save(&self, state: &SupervisorState) -> Result<(), LauncherError> {
        let parent = self
            .path
            .parent()
            .ok_or(LauncherError::State("state path has no parent"))?;
        let temporary = self.path.with_extension("tmp");
        self.cleanup_temporary()?;
        let bytes = serde_json::to_vec(state)
            .map_err(|_| LauncherError::State("state serialization failed"))?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|source| io_error("create temporary state", &temporary, source))?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|source| io_error("write temporary state", &temporary, source))?;
        fs::rename(&temporary, &self.path)
            .map_err(|source| io_error("publish state", &self.path, source))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|source| io_error("sync state directory", parent, source))
    }

    fn cleanup_temporary(&self) -> Result<(), LauncherError> {
        let temporary = self.path.with_extension("tmp");
        if !temporary.exists() {
            return Ok(());
        }
        let metadata = fs::symlink_metadata(&temporary)
            .map_err(|source| io_error("inspect temporary state", &temporary, source))?;
        if metadata.file_type().is_dir() {
            return Err(LauncherError::State("temporary state path is a directory"));
        }
        fs::remove_file(&temporary)
            .map_err(|source| io_error("remove temporary state", &temporary, source))
    }
}

fn io_error(operation: &'static str, path: &Path, source: std::io::Error) -> LauncherError {
    LauncherError::StateIo {
        operation,
        path: path.to_path_buf(),
        source,
    }
}
