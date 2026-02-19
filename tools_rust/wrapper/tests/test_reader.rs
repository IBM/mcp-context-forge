use bytes::Bytes;
use mcp_stdio_wrapper::logger::init_logger;
use mcp_stdio_wrapper::stdio_reader::spawn_reader;
#[tokio::test]
///
/// # Errors
///
/// Returns an error if reading from the channel fails.
///
/// # Panics
///
/// Panics if the received line does not match the expected data.
async fn test_reader() {
    init_logger(Some("debug"), None);
    for i in [true, false] {
        let (tx, rx) = flume::unbounded::<Bytes>();

        let stdio = tokio_test::io::Builder::new()
            .read(b"line1\n")
            .wait(std::time::Duration::from_millis(10)) // Give us time to drop
            .read(b"line2\n")
            .build();

        let handle = spawn_reader(tx, stdio);

        let first = rx.recv_async().await.expect("Should receive line1");
        assert_eq!(first, Bytes::from("line1"));

        if i {
            // test termination
            drop(rx);
        } else {
            // test eof
            let second = rx.recv_async().await.expect("Should receive line2");
            assert_eq!(second, Bytes::from("line2"));
        }

        let _ = handle.await;
    }
}
