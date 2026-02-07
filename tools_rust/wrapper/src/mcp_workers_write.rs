use crate::post_result::PostResult;
use bytes::Bytes;
use flume::Sender;
use tracing::error;

const DATA: &[u8] = b"data:";
const DATA_LEN: usize = DATA.len();
const EMPTY: Bytes = Bytes::new();
/// Trims leading and trailing ASCII whitespace from input.
fn trim_ascii_whitespace(bytes: &Bytes) -> Bytes {
    let start = bytes
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .unwrap_or(bytes.len());

    let end = bytes
        .iter()
        .rposition(|b| !b.is_ascii_whitespace())
        .map_or(start, |pos| pos + 1);

    if start >= end {
        EMPTY
    } else {
        bytes.slice(start..end)
    }
}

fn strip_data_prefix(b: &Bytes) -> Bytes {
    if b.starts_with(DATA) {
        trim_ascii_whitespace(&b.slice(DATA_LEN..))
    } else {
        EMPTY
    }
}
/// writes worker output to stdout channel
pub async fn write_output(i: usize, tx: &Sender<Bytes>, res: PostResult) {
    for line in res.out {
        let out_line = if res.sse {
            // For SSE, strip "data:"
            strip_data_prefix(&line)
        } else {
            trim_ascii_whitespace(&line)
        };

        if !out_line.is_empty() {
            if let Err(e) = tx.send_async(out_line).await {
                error!("Worker {i}: failed to send: {e}");
                break;
            }
        }
    }
}
