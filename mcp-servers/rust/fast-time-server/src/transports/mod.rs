// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Transports. The modern Streamable HTTP transport (`/mcp`) is served by the
//! rmcp SDK directly from [`crate::app`]; only the legacy HTTP+SSE shim lives
//! here.

pub(crate) mod sse;
