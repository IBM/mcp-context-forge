// fast-time-server - Ultra-fast MCP server for performance testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

mod app;
mod config;
mod delay;
mod prompts;
mod resources;
mod rest;
mod server;
mod time;
mod transports;

pub use app::run;
