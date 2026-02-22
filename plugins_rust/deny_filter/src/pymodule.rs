pub use crate::deny_list::DenyList;
pub use crate::deny_list_rs::DenyListRs;
use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;

#[pymodule]
/// python module compose
/// # Errors
/// * methods not found
pub fn deny_filter(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<DenyList>()?;
    m.add_class::<DenyListRs>()?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);
