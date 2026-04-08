fn main() {
    let protoc = protoc_bin_vendored::protoc_bin_path().expect("vendored protoc");
    // SAFETY: build scripts run in a dedicated process before crate compilation.
    unsafe {
        std::env::set_var("PROTOC", protoc);
    }

    tonic_prost_build::compile_protos("proto/contextforge/auth/v1/auth.proto")
        .expect("compile auth proto");
}
