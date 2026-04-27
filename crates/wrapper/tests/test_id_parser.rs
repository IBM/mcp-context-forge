use jsonrpc_core::Id;
use jsonrpc_core::Id::Num;
use mcp_stdio_wrapper::json_rpc_id::parse_id;
use mcp_stdio_wrapper::json_rpc_id_fast::parse_id_fast;
use std::fmt::Write;
use std::time::Instant;

#[cfg(test)]
#[test]
/// test id parsing
/// # Errors
/// errors mean test failure
fn test_parse_id_performance() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Setup Short Input
    let short_json = r#"{"jsonrpc": "2.0", "method": "test","asdf":{"asdf":{}}, "id": 123}"#;

    // Huge Input (Simulating a several MB payload)
    let mut large_data = String::with_capacity(20 * 1024 * 1024); // 20MB
    large_data.push_str(r#"{"jsonrpc": "2.0", "asdf":{"asdf":{}}, "id": 999, "data": ["#);

    for i in 0..314_159 {
        if i > 0 {
            large_data.push(',');
        }
        let _ = write!(
            large_data,
            r#"{{"index": {i}, "payload": "some repeated data"}}"#
        );
    }

    large_data.push_str("]}");

    println!("Large JSON size: {} MB", large_data.len() / 1_024 / 1_024);
    //println!("Large JSON: {}", large_data);

    // --- Benchmark Short
    let start_short = Instant::now();
    let id_short = parse_id(short_json)?;
    let duration_short = start_short.elapsed();
    assert_eq!(id_short, 123);
    println!("Short JSON parse time: {duration_short:?}");

    // --- Benchmark Short actson
    let start_short_fast = Instant::now();
    let id_short_fast = parse_id_fast(short_json.as_bytes());
    let duration_short_fast = start_short_fast.elapsed();
    assert_eq!(id_short_fast, Num(123));
    println!("Short JSON parse time (actson): {duration_short_fast:?}");

    // --- Benchmark Large
    let start_large = Instant::now();
    let id_large = parse_id(&large_data)?;
    let duration_large = start_large.elapsed();
    assert_eq!(id_large, 999);
    println!("Large JSON parse time: {duration_large:?}");

    // --- Benchmark Large with actson
    let start_large_actson = Instant::now();
    let id_large_actson = parse_id_fast(large_data.as_bytes());
    let duration_large_actson = start_large_actson.elapsed();
    assert_eq!(id_large_actson, Num(999));
    println!("Large JSON parse time (actson): {duration_large_actson:?}");

    let found = parse_id_fast("{}".as_bytes());
    assert_eq!(found, Id::Null);

    let found = parse_id_fast("".as_bytes());
    assert_eq!(found, Id::Null);

    let false_id = r#"{"some_key": "this value contains \"id\": 123", "id": 456}"#;
    let found = parse_id_fast(false_id.as_bytes());
    assert_eq!(found, Num(456));

    let simple = r#"{"id":1}"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Num(1));

    let simple = r#"{"test":{},"id":null}"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Id::Null);

    let simple = r#"{"test":{},"id":{}}"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Id::Null);

    let simple = r#"{"id":}"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Id::Null);

    let simple = r#"{"id":"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Id::Null);

    let simple = r#"{"id":}}"#;
    let found = parse_id_fast(simple.as_bytes());
    assert_eq!(found, Id::Null);

    Ok(())
}
