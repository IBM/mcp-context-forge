use pyo3::exceptions::PyRuntimeError;
use pyo3::PyErr;

pub fn runtime_error(message: &str) -> PyErr {
    PyRuntimeError::new_err(message.to_string())
}