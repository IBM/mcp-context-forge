use mcp_stdio_wrapper::config::Config;
use mcp_stdio_wrapper::main_loop::main_loop;
use mockito::Server;
use std::io::Cursor;
use std::sync::Arc;

const INIT: &str = r#"{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"prompts":{},"resources":{},"tools":{}},"serverInfo":{"name":"rmcp","version":"0.13.0"},"instructions":"This server provides counter tools and prompts. Tools: increment, decrement, get_value, say_hello, echo, sum. Prompts: example_prompt (takes a message), counter_analysis (analyzes counter state with a goal)."}}"#;
const INIT_OUT: &str = r#"data:
id: 0
retry: 3000

data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"prompts":{},"resources":{},"tools":{}},"serverInfo":{"name":"rmcp","version":"0.13.0"},"instructions":"This server provides counter tools and prompts. Tools: increment, decrement, get_value, say_hello, echo, sum. Prompts: example_prompt (takes a message), counter_analysis (analyzes counter state with a goal)."}}
"#;

struct MockWriter {
    data: Arc<std::sync::Mutex<Vec<u8>>>,
}

impl tokio::io::AsyncWrite for MockWriter {
    fn poll_write(
        self: std::pin::Pin<&mut Self>,
        _cx: &mut std::task::Context<'_>,
        buf: &[u8],
    ) -> std::task::Poll<std::io::Result<usize>> {
        self.data.lock().unwrap().extend_from_slice(buf);
        std::task::Poll::Ready(Ok(buf.len()))
    }
    fn poll_flush(
        self: std::pin::Pin<&mut Self>,
        _cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::task::Poll::Ready(Ok(()))
    }
    fn poll_shutdown(
        self: std::pin::Pin<&mut Self>,
        _cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        std::task::Poll::Ready(Ok(()))
    }
}

#[tokio::test]
async fn test_main_loop() {
    let mut server = Server::new_async().await;
    let url = server.url();

    let config = Config::from_cli(["test", "--url", url.as_str()]);

    let _mock_init = server
        .mock("POST", "/mcp/")
        .with_status(200)
        .with_header("mcp-session-id", "9cb62a01-2523-4380-964e-2e3efd1d135a")
        .with_body(INIT_OUT)
        .create_async()
        .await;

    let input = INIT.as_bytes();

    let output_vec = Arc::new(std::sync::Mutex::new(Vec::new()));
    let output = MockWriter {
        data: Arc::clone(&output_vec),
    };

    main_loop(config, input, output).await;
    let out = output_vec.lock().unwrap();
    let out_str = String::from_utf8_lossy(&out);
    println!("{out_str}");
}

#[tokio::test]
//#[should_panic(expected = "Failed")]
async fn test_main_loop_fail() {
    let config = Config::from_cli(["test", "--url", "file://tmp", "-c", "bad\x0ff"]);
    let input = Cursor::new(b"input");
    let output = vec![];

    main_loop(config, input, output).await;
}
