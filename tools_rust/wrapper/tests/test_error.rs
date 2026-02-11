use bytes::Bytes;
use flume::Receiver;
use jsonrpc_core::{ErrorCode, Failure, Id, Version};
use contextforge_stdio_wrapper::logger::init_logger;
use contextforge_stdio_wrapper::streamer_error::{mcp_error, rpc_error};
use serde::de::Error;
use serde_json::{Value, json};

struct TestCase {
    input_json: String,
    error_message: &'static str,
    expected_output: Value,
}

#[tokio::test]
/// test id parsing
/// # Errors
/// returns error when test fails
/// # Panics
/// code panics when test fails
async fn test_error() -> Result<(), Box<dyn std::error::Error>> {
    init_logger(Some("debug"), None);
    let (tx, rx) = flume::unbounded();
    let worker: usize = 1;
    let test_cases = vec![
        TestCase {
            input_json: json!({"jsonrpc":"2.0","id":1,"method":"tools/list"}).to_string(),
            error_message: "error1",
            expected_output: json!({
                "jsonrpc":"2.0",
                "error":{"code":ErrorCode::InternalError,"message":"error1"},
                "id":1
            }),
        },
        TestCase {
            input_json: json!({"jsonrpc":"2.0","id":"id_2","method":"tools/list"}).to_string(),
            error_message: "error2",
            expected_output: json!({
                "jsonrpc":"2.0",
                "error":{"code":ErrorCode::InternalError,"message":"error2"},
                "id":"id_2"
            }),
        },
        TestCase {
            input_json: String::new(),
            error_message: "error3",
            expected_output: json!({
                "jsonrpc":"2.0",
                "error":{"code":ErrorCode::InternalError,"message":"error3"},
                "id":null
            }),
        },
    ];

    // Run tests in a loop
    for case in test_cases {
        mcp_error(&worker, case.input_json.as_bytes(), case.error_message, &tx).await;
        verify(&rx, &case.expected_output).await;
    }
    Ok(())
}

async fn verify(rx: &Receiver<Bytes>, expected: &Value) {
    let msg = rx.recv_async().await.expect("receiving error");
    let msg_str = String::from_utf8_lossy(&msg);
    let actual = serde_json::from_str::<Value>(&msg_str).expect("deserializing error");
    println!("{actual}");
    assert_eq!(actual, *expected);

    let response = Failure {
        jsonrpc: Some(Version::V2),
        error: jsonrpc_core::Error {
            code: ErrorCode::InternalError,
            message: String::new(),
            data: None,
        },
        id: Id::Null,
    };
    let _ = rpc_error(&response, &serde_json::Error::custom("Aha"));
}
