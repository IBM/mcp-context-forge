use std::path::{Path, PathBuf};

use clap::Parser;
use praxis_filter::FilterRegistry;

#[derive(Parser)]
#[command(name = "praxis", version = "0.5.1 (ed46eb5)")]
struct Cli {
    #[arg(short = 'c', long = "config", default_value = "praxis.yaml")]
    config: PathBuf,
    #[arg(short = 't', long = "validate")]
    validate: bool,
}

fn main() {
    let cli = Cli::parse();
    if cli.validate {
        let Some(root) = validation_root(&cli.config) else {
            eprintln!("invalid configuration: config file must be named praxis.yaml");
            std::process::exit(1);
        };
        if let Err(error) = praxis_cf_dataplane::validate_generation(root) {
            eprintln!("invalid configuration: {error}");
            std::process::exit(1);
        }
        return;
    }
    let config_path = cli.config.to_string_lossy();
    let config =
        praxis::load_config(Some(&config_path)).unwrap_or_else(|error| praxis::fatal(&error));
    praxis::init_tracing(&config).unwrap_or_else(|error| praxis::fatal(&error));
    let mut registry = FilterRegistry::with_builtins();
    praxis_cf_dataplane::register_filters(&mut registry);
    praxis::run_server_with_registry(config, registry, Some(cli.config))
}

fn validation_root(config: &Path) -> Option<&Path> {
    if config.file_name()? != "praxis.yaml" {
        return None;
    }
    Some(
        config
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new(".")),
    )
}

#[cfg(test)]
mod tests {
    use super::validation_root;
    use std::path::Path;

    #[test]
    fn validation_root_normalizes_bare_and_preserves_nested_paths() {
        assert_eq!(
            validation_root(Path::new("praxis.yaml")),
            Some(Path::new("."))
        );
        assert_eq!(
            validation_root(Path::new("generation/praxis.yaml")),
            Some(Path::new("generation"))
        );
        assert_eq!(
            validation_root(Path::new("/fixtures/golden/praxis.yaml")),
            Some(Path::new("/fixtures/golden"))
        );
        assert_eq!(validation_root(Path::new("other.yaml")), None);
    }
}
