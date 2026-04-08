pub(crate) fn run_cleanup() -> AppResult<std::process::ExitStatus> {
    let engine = env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "podman".to_string());
    let chosen_engine = if Command::new(&engine)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
    {
        engine
    } else {
        "docker".to_string()
    };

    if chosen_engine == "podman" {
        if let Ok(output) = Command::new("podman")
            .args(["pod", "ps", "-a", "--format", "{{.Name}}"])
            .output()
        {
            for pod in String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::trim)
                .filter(|name| name.starts_with("bench-"))
            {
                let _ = Command::new("podman")
                    .args(["pod", "rm", "-f", pod])
                    .status();
            }
        }
    }

    if let Ok(output) = Command::new(&chosen_engine)
        .args(["ps", "-a", "--format", "{{.Names}}"])
        .output()
    {
        for container in String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(str::trim)
            .filter(|name| name.starts_with("bench-"))
        {
            let _ = Command::new(&chosen_engine)
                .args(["rm", "-f", container])
                .status();
        }
    }

    let reports_dir = Path::new("reports/benchmarks");
    if reports_dir.exists() {
        for entry in fs::read_dir(&reports_dir)? {
            let path = entry?.path();
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("");
            if name.starts_with("all-scenarios_")
                || name.starts_with("rust-mcp-runtime-300_")
                || name.starts_with("a2a-invoke-300_")
                || name == "_runtime_staging"
            {
                if path.is_dir() {
                    let _ = fs::remove_dir_all(&path);
                } else {
                    let _ = fs::remove_file(&path);
                }
            }
        }
    }

    Command::new("true").status().map_err(Into::into)
}
use crate::*;
