cargo install cargo-llvm-cov
rustup component add llvm-tools-preview

time cargo llvm-cov --html --ignore-filename-regex "src/bin/test_stream.rs"

firefox /home/dz/prj/mcp-stdio-wrapper/target/llvm-cov/html/index.html
