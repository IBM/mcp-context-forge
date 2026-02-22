use deny_filter::pymodule::stub_info;
use pyo3_stub_gen::Result;
/// creates .pyi file for pyo3 package
/// # Errors
/// * invalid package
fn main() -> Result<()> {
    let stub = stub_info()?;
    stub.generate()?;
    Ok(())
}
