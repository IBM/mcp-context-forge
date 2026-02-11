use contextforge_stdio_wrapper::main_init::init_main;
use contextforge_stdio_wrapper::main_loop::main_loop;
use tokio::io::{stdin, stdout};
use tokio::signal;
use tracing::info;

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[tokio::main]
async fn main() {
    let config = init_main(std::env::args());

    tokio::select! {
        () = main_loop(config, stdin(), stdout()) => {}
        () = shutdown_signal() => {
            info!("Shutdown signal received, exiting");
        }
    }
}

async fn shutdown_signal() {
    let ctrl_c = signal::ctrl_c();

    #[cfg(unix)]
    {
        let mut sigterm =
            signal::unix::signal(signal::unix::SignalKind::terminate()).expect("SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {}
            _ = sigterm.recv() => {}
        }
    }

    #[cfg(not(unix))]
    {
        ctrl_c.await.ok();
    }
}
