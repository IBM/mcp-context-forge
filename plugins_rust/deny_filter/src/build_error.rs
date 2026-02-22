use pyo3::PyErr;
use pyo3::exceptions::PyValueError;
/// common funcion to test errors
/// # Errors
/// * when ac-corasic or regex set fails to build
pub fn build_error<E: std::fmt::Display>(e: E) -> PyErr {
    PyValueError::new_err(format!("Invalid patterns: {e}"))
}
