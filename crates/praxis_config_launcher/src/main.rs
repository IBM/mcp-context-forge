use std::path::PathBuf;

use praxis_config_launcher::LauncherError;
use praxis_config_launcher::build_info;
use praxis_config_launcher::bundle_validation;
use praxis_config_launcher::process::become_subreaper;
use praxis_config_launcher::runtime::{RuntimeConfig, run};

fn usage() {
    println!(
        "praxis_config_launcher\n\nOptions: --build-info | --validate-bundle PATH\n\nEnvironment: PRAXIS_CONTROL_PLANE_URL, PRAXIS_CA_PATH, PRAXIS_TOKEN_PATH, PRAXIS_GENERATION_ROOT, PRAXIS_STATE_PATH, PRAXIS_BINARY, PRAXIS_HEALTH_LISTEN"
    );
}

#[tokio::main]
async fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let result = match arguments.as_slice() {
        [flag] if flag == "--help" || flag == "-h" => {
            usage();
            Ok(())
        }
        [flag] if flag == "--build-info" => print_build_info(),
        [flag, root] if flag == "--validate-bundle" => {
            bundle_validation::validate(&praxis_binary(), &PathBuf::from(root))
        }
        [] => {
            async {
                become_subreaper()?;
                run(RuntimeConfig::from_env()?).await
            }
            .await
        }
        _ => Err(LauncherError::Config("unsupported launcher arguments")),
    };
    if let Err(error) = result {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn praxis_binary() -> PathBuf {
    std::env::var_os("PRAXIS_BINARY")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/usr/local/bin/praxis"))
}

fn print_build_info() -> Result<(), LauncherError> {
    let info = build_info::collect(&praxis_binary())?;
    serde_json::to_writer(std::io::stdout().lock(), &info).map_err(|_| LauncherError::BuildInfo)?;
    println!();
    Ok(())
}
