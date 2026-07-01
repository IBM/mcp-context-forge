// fast-time-server - Ultra-fast MCP server for performance testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    fast_time_server::run().await
}
