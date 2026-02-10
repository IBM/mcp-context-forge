mod error;
mod http {
    pub mod streamable;
}

use pyo3::prelude::*;

#[pyfunction]
fn start_streamable_http_transport(scope: Bound<'_, PyAny>) -> PyResult<bool> {
    let scope_json = scope
        .repr()?
        .extract::<String>()
        .map_err(|_| error::runtime_error("failed to serialize scope for rust transport scaffold"))?;

    Ok(http::streamable::start_streamable_http_transport(&scope_json))
}

#[pymodule]
fn mcpgateway_transport_rs(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(start_streamable_http_transport, m)?)?;
    Ok(())
}