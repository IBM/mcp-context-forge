// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// MCP Gateway Rust - Root module exposing all Rust-accelerated services

use pyo3::prelude::*;

/// Register all services as submodules under the services namespace
fn register_services(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Create services submodule
    let services_module = PyModule::new(m.py(), "services")?;

    // Add a2a_service to services submodule
    let a2a_module = PyModule::new(m.py(), "a2a_service")?;
    a2a_service::a2a_service(&a2a_module)?;
    services_module.add_submodule(&a2a_module)?;

    // Register a2a_service in sys.modules for direct import
    m.py()
        .import("sys")?
        .getattr("modules")?
        .set_item("mcpgateway_rust.services.a2a_service", &a2a_module)?;

    // Add services submodule to root
    m.add_submodule(&services_module)?;

    // Register services in sys.modules for direct import
    m.py()
        .import("sys")?
        .getattr("modules")?
        .set_item("mcpgateway_rust.services", &services_module)?;

    // Future services can be added here

    Ok(())
}

/// MCP Gateway Rust module - exposes all Rust-accelerated services
#[pymodule]
fn mcpgateway_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("__doc__", "Rust-accelerated services for MCP Gateway")?;

    // Register all services
    register_services(m)?;

    Ok(())
}
