# Filesystem Server

A secure MCP (Model Context Protocol) server written in Rust that provides comprehensive filesystem operations with sandboxing, atomic writes, and pattern-matching edits. Uses the official [Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk).

## Features

- **Memory-safe**: Zero unsafe code, fully clippy-clean, MUSL-compatible static binaries (~4 MB)
- **Sandboxed**: All operations confined to configured root directories; symlink traversal blocked
- **Atomic writes**: Safe file modifications via atomic operations with dry-run support
- **10 filesystem tools**: read, write, edit, search, move, list, info, and more
- **Production-ready**: Docker images <10 MB, Kubernetes-deployable, comprehensive test coverage
- **High-performance**: Async tokio-based with streaming support

## Tools

All tools operate within sandboxed root directories. Operations outside configured roots return errors.

| Tool | Purpose | Key Inputs | Notes / Best Practice |
|------|---------|-----------|----------------------|
| `read_file` | Return full UTF-8 text of a file | `path: string` | Fails if file not readable; size cap 1 MiB. |
| `read_multiple_files` | Get several files at once | `paths: string[]` | Streams results; failed paths are reported but do not abort the batch. |
| `write_file` | Create or overwrite a file | `path: string, content: string` | Performs atomic write via temp-file + rename. |
| `edit_file` | Targeted edits with diff preview | `path: string, edits: [{ oldText, newText }], dryRun: bool` | Supports multi-line & pattern matching, keeps indentation style; returns git-style diff in dry-run mode. Always dry-run first. |
| `create_directory` | Ensure directory exists | `path: string` | Creates parents (mkdir -p behaviour). |
| `list_directory` | List items with [FILE] / [DIR] tags | `path: string` | Sorted alphabetically. |
| `move_file` | Move / rename files or dirs | `source: string, destination: string` | Overwrites destination if exists. |
| `search_files` | Recursive glob search | `path, pattern, excludePatterns[]` | Case-insensitive; returns full paths. |
| `get_file_info` | Stat + metadata | `path: string` | Size, times, perms, type. |
| `list_allowed_directories` | Reveal sandbox roots | (none) | Returns array of allowed roots. |

## Quick Start

### Requirements

- Rust ≥ 1.77
- `make` (optional, for convenience)
- Docker (optional, for containerized deployment)

### Using Make

```bash
# Show available targets
make help

# Run with custom roots (space-separated)
make run ROOTS="/tmp /var/www"

# Or release build
make run-release ROOTS="/tmp /var/www"

# Run tests
make test
make test-lib
make test-integration

# Build
make build          # Debug
make release        # Optimized
make install        # Install to ~/.cargo/bin
```

### Using Cargo Directly

```bash
# Run with roots
cargo run -- --roots /tmp /var/www /home/user/projects

# Test
cargo test
```

### Using docker

```bash
# Single root
docker run \
  -p 8084:8084 \
  -v /tmp:/tmp \
  filesystem-server --roots /tmp

# Multiple roots - mount and pass as arguments
docker run \
  -p 8084:8084 \
  -v /var/www:/www \
  -v /tmp:/tmp \
  filesystem-server --roots "/www /tmp"
```
Image size: ~10 MB (binary: 3.2 MB + Debian slim base)


## Make Targets

```bash
filesystem-server - Makefile targets:
  build              - Build debug binary
  release            - Build optimized release binary
  debug              - Build and run debug binary
  test               - Run all tests
  test-lib           - Run library tests only
  test-integration   - Run integration tests
  coverage           - Generate coverage report
  fmt                - Format code with rustfmt
  clippy             - Run clippy linter
  check              - Run cargo check
  clean              - Remove build artifacts
  install            - Install binary to ~/.cargo/bin
  run                - Run debug binary (ROOTS=/folder1 /folder2 ...)
  run-release        - Run release binary (ROOTS=/folder1 /folder2 ...)
  container-build    - Build container image
  container-run      - Run container
  container-stop     - Stop container
```

## Testing

### Run Tests

```bash
make test           # All tests
make test-lib       # Library tests
make test-integration  # Integration tests
make coverage       # Coverage report (HTML)
```
### Test coverage

| Filename       | Function Coverage | Line Coverage | Region Coverage | Branch Coverage |
|----------------|-----------------|---------------|----------------|----------------|
| lib.rs         | 60.00% (3/5)    | 46.88% (15/32) | 67.44% (29/43) | - (0/0)        |
| main.rs        | 0.00% (0/3)     | 0.00% (0/17)   | 0.00% (0/27)   | - (0/0)        |
| sandbox.rs     | 97.06% (33/34)  | 99.04% (206/208) | 98.89% (357/361) | - (0/0)    |
| server.rs      | 72.09% (31/43)  | 78.65% (350/445) | 83.03% (494/595) | - (0/0)    |
| tools/edit.rs  | 87.10% (27/31)  | 98.34% (237/241) | 95.50% (446/467) | - (0/0)    |
| tools/info.rs  | 92.86% (13/14)  | 98.80% (82/83)   | 96.45% (163/169) | - (0/0)    |
| tools/read.rs  | 87.50% (21/24)  | 98.22% (166/169) | 95.93% (283/295) | - (0/0)    |
| tools/search.rs| 95.12% (39/41)  | 98.52% (267/271) | 97.48% (581/596) | - (0/0)    |
| tools/write.rs | 93.75% (45/48)  | 94.17% (323/343) | 92.74% (626/675) | - (0/0)    |
| **Totals**     | 87.24% (212/243)| 90.99% (1646/1809)| 92.29% (2979/3228)| - (0/0)   |


## Architecture

```
src/
├── main.rs         # Axum server, CLI parsing, shutdown
├── lib.rs          # Module exports, constants
├── server.rs       # Tool handlers, MCP trait impl
├── sandbox.rs      # Path resolution and security
└── tools/
    ├── mod.rs      # Module exports
    ├── read.rs     # read_file, read_multiple_files
    ├── write.rs    # write_file, create_directory
    ├── edit.rs     # edit_file, move_file
    ├── search.rs   # search_files, list_directory
    └── info.rs     # get_file_info
tests/
└── integration_test.rs  # Comprehensive test suite
Dockerfile         # Multi-stage build
Makefile           # Build & test automation
```

## Security

- **Sandbox**: All paths resolved against configured roots only
- **Symlink blocking**: Traversal across symlinks blocked
- **Atomic writes**: File modifications are atomic via temporary files
- **Dry-run support**: `edit_file` with `dry_run=true` previews changes without modifying


## Binary Sizes

| Profile | Size |
|---------|------|
| Release | ~3.3 MB |
| Release MUSL | ~3.3 MB |

## License

Apache 2.0
