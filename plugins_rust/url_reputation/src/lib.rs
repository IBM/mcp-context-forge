use pyo3::prelude::*;
mod engine;
pub mod filters;
mod types;

#[pymodule]
fn url_reputation(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<types::URLReputationConfig>()?;
    m.add_class::<engine::URLReputationPlugin>()?;
    m.add_class::<types::URLPluginResult>()?;
    Ok(())
}
