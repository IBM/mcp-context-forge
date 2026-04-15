// Allow duplicate transitive deps in this benchmark-only binary target.
#![allow(clippy::multiple_crate_versions)]

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use contextforge_benchmark_runner::{
    DEFAULT_SCENARIO_DIR, discover_scenarios, regenerate_reports, repo_root, run_benchmark,
};

#[derive(Parser, Debug)]
#[command(name = "contextforge-benchmark-runner")]
#[command(about = "Rust-native benchmark runner for crates/contextforge_benchmark_runner")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    List,
    Validate {
        #[arg(long)]
        scenario: String,
        #[arg(long, default_value_t = false)]
        smoke: bool,
    },
    Run {
        #[arg(long)]
        scenario: String,
        #[arg(long, default_value_t = false)]
        smoke: bool,
    },
    RunAll {
        #[arg(long, default_value_t = false)]
        smoke: bool,
    },
    CheckRuntime {
        #[arg(long)]
        scenario: String,
        #[arg(long, default_value_t = false)]
        smoke: bool,
    },
    RegenerateReport {
        #[arg(long)]
        run_dir: PathBuf,
    },
    CompareRun {
        #[arg(long)]
        run_dir: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let root = repo_root()?;
    match cli.command {
        Commands::List => {
            for scenario in discover_scenarios(&root)? {
                println!("{scenario}");
            }
        }
        Commands::Validate { scenario, smoke } => {
            let run_dir = run_benchmark(&root, &scenario, false, true, smoke, false)?;
            println!("{}", run_dir.display());
        }
        Commands::Run { scenario, smoke } => {
            let run_dir = run_benchmark(&root, &scenario, false, false, smoke, false)?;
            println!("{}", run_dir.display());
        }
        Commands::RunAll { smoke } => {
            let run_dir = run_benchmark(&root, "all-scenarios", true, false, smoke, false)?;
            println!("{}", run_dir.display());
        }
        Commands::CheckRuntime { scenario, smoke } => {
            let run_dir = run_benchmark(&root, &scenario, false, false, smoke, true)?;
            println!("{}", run_dir.display());
        }
        Commands::RegenerateReport { run_dir } | Commands::CompareRun { run_dir } => {
            let output = regenerate_reports(&run_dir)?;
            println!("{}", output.display());
        }
    }
    let _ = DEFAULT_SCENARIO_DIR;
    Ok(())
}
