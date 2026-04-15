use request_logging_masking_native_extension::stub_info;

fn main() {
    let stub_info = stub_info().expect("Failed to get stub info");
    stub_info.generate().expect("Failed to generate stub file");
    println!("Generated stub files successfully");
}
