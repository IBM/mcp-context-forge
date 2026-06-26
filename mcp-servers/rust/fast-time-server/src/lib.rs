// fast-time-server - Ultra-fast MCP server for performance testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

mod app;
mod cli;
mod config;
mod delay;
mod prompts;
mod resources;
mod rest;
mod rest_v1;
mod server;
mod time;
mod transports;

pub use app::run;
