use pyo3::prelude::*;
pub mod filters;
mod engine;
mod types;

#[pymodule]
fn url_reputation(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<types::URLReputationConfig>()?;
    m.add_class::<engine::URLReputationPlugin>()?;
    Ok(())
}
