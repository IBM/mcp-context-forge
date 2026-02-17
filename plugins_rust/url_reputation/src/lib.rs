use pyo3::prelude::*;
pub mod filters;
mod engine;
use engine::validate_url;

#[pymodule]
fn url_reputation(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<engine::URLReputationConfig>()?;
    m.add_function(wrap_pyfunction!(validate_url, m)?)?;
    Ok(())
}
