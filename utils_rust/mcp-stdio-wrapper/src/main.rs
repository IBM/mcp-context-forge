mod config;
mod config_defaults;
mod config_from_cli;
mod config_from_env;
mod logger;
mod mcp_workers;
mod post_result;
mod stdio_reader;
mod stdio_writer;
mod streamer;
mod streamer_new;
mod streamer_post;
mod streamer_id;

use crate::config::Config;
use crate::logger::init_logger;
use crate::mcp_workers::spawn_workers;
use crate::stdio_reader::spawn_reader;
use crate::stdio_writer::spawn_writer;
use std::sync::Arc;

use streamer::McpStreamClient;
use tracing::{debug, info};

#[tokio::main]
async fn main() {
    init_logger();
    let config = Config::from_cli();
    info!("{config:?}");

    info!("Start");

    let mcp_client = Arc::new(McpStreamClient::new(config.mcp_server_url));
    debug!("Mcp client: {mcp_client:?}");

    // (Reader -> Worker)
    let (reader_tx, reader_rx) = flume::unbounded::<String>();
    // (Worker -> Writer)
    let (writer_tx, writer_rx) = flume::unbounded::<String>();

    spawn_reader(reader_tx);
    spawn_workers(config.concurrency, &mcp_client, &reader_rx, &writer_tx);
    let exit = spawn_writer(writer_rx);

    let _ = exit.await;

    info!("Finish");
}
