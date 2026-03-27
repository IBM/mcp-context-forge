// Location: tools_rust/mcp_runtime/build.rs
// SPDX-License-Identifier: Apache-2.0
//
// Compile proto/mcp_runtime.proto into Rust code when the grpc-uds feature is enabled.
// Generated code is written to OUT_DIR and included via the tonic::include_proto! macro.

fn main() {
    #[cfg(feature = "grpc-uds")]
    {
        tonic_build::configure()
            .build_server(true)
            .build_client(false) // client lives in Python; no Rust-side client needed
            .compile_protos(&["proto/mcp_runtime.proto"], &["proto"])
            .unwrap_or_else(|e| panic!("Failed to compile proto files: {e}"));
    }
}
