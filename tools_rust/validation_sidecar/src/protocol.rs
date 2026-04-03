// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Framing and request/response envelopes for the validation sidecar.

use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::fmt::Display;
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

pub const FRAME_PREFIX_LEN: usize = 4;
pub const METADATA_PREFIX_LEN: usize = 4;
pub const MAX_FRAME_SIZE: usize = 16 * 1024 * 1024;
pub const MAX_RAW_BODY_SIZE: usize = 1024 * 1024;
pub const OK_RESPONSE_BYTES: &[u8] = br#"{"ok":true}"#;

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("framed payload is too short to contain a length prefix")]
    ShortFrame,
    #[error("frame payload length mismatch: expected {expected} bytes, received {received} bytes")]
    LengthMismatch { expected: usize, received: usize },
    #[error("frame payload exceeds maximum size of {MAX_FRAME_SIZE} bytes")]
    FrameTooLarge,
    #[error("request body exceeds maximum size of {MAX_RAW_BODY_SIZE} bytes")]
    RawBodyTooLarge,
    #[error("invalid JSON envelope: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("{0}")]
    InvalidEnvelope(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationRequestEnvelope {
    pub raw_body_len: usize,
    pub max_param_length: usize,
    #[serde(default)]
    pub dangerous_patterns: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(default)]
    pub healthcheck: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationRequest {
    pub raw_body: Vec<u8>,
    pub max_param_length: usize,
    pub dangerous_patterns: Vec<String>,
    pub request_id: Option<String>,
    pub healthcheck: bool,
}

impl ValidationRequestEnvelope {
    pub fn into_request(self, raw_body: Vec<u8>) -> Result<ValidationRequest, ProtocolError> {
        if self.max_param_length == 0 {
            return Err(ProtocolError::InvalidEnvelope(
                "max_param_length must be greater than zero".to_owned(),
            ));
        }

        if self.raw_body_len != raw_body.len() {
            return Err(ProtocolError::InvalidEnvelope(
                "raw_body_len does not match attached request body".to_owned(),
            ));
        }
        if raw_body.len() > MAX_RAW_BODY_SIZE {
            return Err(ProtocolError::RawBodyTooLarge);
        }

        Ok(ValidationRequest {
            raw_body,
            max_param_length: self.max_param_length,
            dangerous_patterns: self.dangerous_patterns,
            request_id: self.request_id,
            healthcheck: self.healthcheck,
        })
    }
}

impl ValidationRequest {
    pub fn from_raw_body(
        raw_body: &[u8],
        max_param_length: usize,
        dangerous_patterns: &[String],
    ) -> Result<Self, ProtocolError> {
        if raw_body.len() > MAX_RAW_BODY_SIZE {
            return Err(ProtocolError::RawBodyTooLarge);
        }

        Ok(Self {
            raw_body: raw_body.to_vec(),
            max_param_length,
            dangerous_patterns: dangerous_patterns.to_vec(),
            request_id: None,
            healthcheck: false,
        })
    }

    pub fn to_envelope(&self) -> ValidationRequestEnvelope {
        ValidationRequestEnvelope {
            raw_body_len: self.raw_body.len(),
            max_param_length: self.max_param_length,
            dangerous_patterns: self.dangerous_patterns.clone(),
            request_id: self.request_id.clone(),
            healthcheck: self.healthcheck,
        }
    }
}

pub fn encode_request_payload(request: &ValidationRequest) -> Result<Vec<u8>, ProtocolError> {
    let metadata = serde_json::to_vec(&request.to_envelope())?;
    if metadata.len() > MAX_FRAME_SIZE {
        return Err(ProtocolError::FrameTooLarge);
    }

    let total_len = METADATA_PREFIX_LEN + metadata.len() + request.raw_body.len();
    if total_len > MAX_FRAME_SIZE {
        return Err(ProtocolError::FrameTooLarge);
    }

    let mut payload = Vec::with_capacity(total_len);
    payload.extend_from_slice(&(metadata.len() as u32).to_be_bytes());
    payload.extend_from_slice(&metadata);
    payload.extend_from_slice(&request.raw_body);
    Ok(payload)
}

pub fn decode_request_payload(payload: &[u8]) -> Result<ValidationRequest, ProtocolError> {
    if payload.len() < METADATA_PREFIX_LEN {
        return Err(ProtocolError::ShortFrame);
    }

    let metadata_len =
        u32::from_be_bytes(payload[..METADATA_PREFIX_LEN].try_into().expect("prefix length"))
            as usize;
    let metadata_start = METADATA_PREFIX_LEN;
    let metadata_end = metadata_start + metadata_len;
    if metadata_end > payload.len() {
        return Err(ProtocolError::LengthMismatch {
            expected: metadata_end,
            received: payload.len(),
        });
    }

    let envelope: ValidationRequestEnvelope =
        serde_json::from_slice(&payload[metadata_start..metadata_end])?;
    envelope.into_request(payload[metadata_end..].to_vec())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationResponseEnvelope {
    pub ok: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl ValidationResponseEnvelope {
    pub fn ok() -> Self {
        Self {
            ok: true,
            key: None,
            error_type: None,
            detail: None,
        }
    }

    pub fn rejected(
        key: impl Into<String>,
        error_type: impl Into<String>,
        detail: impl Into<String>,
    ) -> Self {
        Self {
            ok: false,
            key: Some(key.into()),
            error_type: Some(error_type.into()),
            detail: Some(detail.into()),
        }
    }

    pub fn validate(self) -> Result<Self, ProtocolError> {
        if self.ok {
            return Ok(self);
        }

        if self.key.is_none() || self.error_type.is_none() || self.detail.is_none() {
            return Err(ProtocolError::InvalidEnvelope(
                "rejected responses must include key, error_type, and detail".to_owned(),
            ));
        }

        Ok(self)
    }
}

pub fn encode_frame(payload: &[u8]) -> Result<Vec<u8>, ProtocolError> {
    if payload.len() > MAX_FRAME_SIZE {
        return Err(ProtocolError::FrameTooLarge);
    }

    let mut framed = Vec::with_capacity(FRAME_PREFIX_LEN + payload.len());
    framed.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    framed.extend_from_slice(payload);
    Ok(framed)
}

pub fn decode_frame(frame: &[u8]) -> Result<Vec<u8>, ProtocolError> {
    if frame.len() < FRAME_PREFIX_LEN {
        return Err(ProtocolError::ShortFrame);
    }

    let expected =
        u32::from_be_bytes(frame[..FRAME_PREFIX_LEN].try_into().expect("prefix length")) as usize;
    let payload = &frame[FRAME_PREFIX_LEN..];
    if payload.len() != expected {
        return Err(ProtocolError::LengthMismatch {
            expected,
            received: payload.len(),
        });
    }
    if expected > MAX_FRAME_SIZE {
        return Err(ProtocolError::FrameTooLarge);
    }
    Ok(payload.to_vec())
}

pub fn encode_json_frame<T: Serialize>(value: &T) -> Result<Vec<u8>, ProtocolError> {
    encode_frame(&serde_json::to_vec(value)?)
}

pub fn decode_json_frame<T: DeserializeOwned>(frame: &[u8]) -> Result<T, ProtocolError> {
    let payload = decode_frame(frame)?;
    Ok(serde_json::from_slice(&payload)?)
}

pub async fn read_frame<R>(reader: &mut R) -> Result<Vec<u8>, ProtocolError>
where
    R: AsyncRead + Unpin,
{
    let mut prefix = [0_u8; FRAME_PREFIX_LEN];
    reader.read_exact(&mut prefix).await?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length > MAX_FRAME_SIZE {
        return Err(ProtocolError::FrameTooLarge);
    }

    let mut payload = vec![0_u8; length];
    reader.read_exact(&mut payload).await?;
    Ok(payload)
}

pub async fn write_frame<W>(writer: &mut W, payload: &[u8]) -> Result<(), ProtocolError>
where
    W: AsyncWrite + Unpin,
{
    let framed = encode_frame(payload)?;
    writer.write_all(&framed).await?;
    Ok(())
}

pub async fn write_json_frame<W, T>(writer: &mut W, value: &T) -> Result<(), ProtocolError>
where
    W: AsyncWrite + Unpin,
    T: Serialize,
{
    let payload = serde_json::to_vec(value)?;
    write_frame(writer, &payload).await
}

pub async fn write_ok_frame<W>(writer: &mut W) -> Result<(), ProtocolError>
where
    W: AsyncWrite + Unpin,
{
    write_frame(writer, OK_RESPONSE_BYTES).await
}

pub fn invalid_envelope<M: Display>(message: M) -> ProtocolError {
    ProtocolError::InvalidEnvelope(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        pin::Pin,
        task::{Context, Poll},
    };
    use tokio::io::AsyncWrite;

    #[derive(Default)]
    struct RecordingWriter {
        written: Vec<u8>,
        flush_calls: usize,
    }

    impl AsyncWrite for RecordingWriter {
        fn poll_write(
            mut self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
            buf: &[u8],
        ) -> Poll<Result<usize, std::io::Error>> {
            self.written.extend_from_slice(buf);
            Poll::Ready(Ok(buf.len()))
        }

        fn poll_flush(
            mut self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
        ) -> Poll<Result<(), std::io::Error>> {
            self.flush_calls += 1;
            Poll::Ready(Ok(()))
        }

        fn poll_shutdown(
            self: Pin<&mut Self>,
            _cx: &mut Context<'_>,
        ) -> Poll<Result<(), std::io::Error>> {
            Poll::Ready(Ok(()))
        }
    }

    fn default_patterns() -> Vec<String> {
        vec![
            r"[;&|`$(){}\[\]<>]".to_owned(),
            r"\.\.[\\/]".to_owned(),
            r"[\x00-\x1f\x7f-\x9f]".to_owned(),
        ]
    }

    #[test]
    fn frame_round_trip_uses_big_endian_length_prefix() {
        let payload = b"\x00\x01hello";
        let frame = encode_frame(payload).expect("frame");

        assert_eq!(
            &frame[..FRAME_PREFIX_LEN],
            &(payload.len() as u32).to_be_bytes()
        );
        assert_eq!(decode_frame(&frame).expect("decode"), payload);
    }

    #[test]
    fn request_payload_round_trip_preserves_raw_body_outside_metadata() {
        let request =
            ValidationRequest::from_raw_body(br#"{"hello":"world"}"#, 32, &default_patterns())
                .expect("request");
        let encoded = encode_request_payload(&request).expect("payload");
        let round_trip = decode_request_payload(&encoded).expect("into request");

        assert_eq!(round_trip.raw_body, br#"{"hello":"world"}"#);
        assert_eq!(round_trip.dangerous_patterns, default_patterns());
    }

    #[test]
    fn request_envelope_rejects_invalid_json_and_oversized_bodies() {
        let invalid_json = br#"{"raw_body_len":1,"max_param_length":1}"#;
        let envelope: ValidationRequestEnvelope =
            serde_json::from_slice(invalid_json).expect("envelope");
        assert!(matches!(
            envelope.into_request(vec![]),
            Err(ProtocolError::InvalidEnvelope(message)) if message.contains("raw_body_len")
        ));

        let oversized = ValidationRequestEnvelope {
            raw_body_len: MAX_RAW_BODY_SIZE + 1,
            max_param_length: 8,
            dangerous_patterns: Vec::new(),
            request_id: None,
            healthcheck: false,
        };
        assert!(matches!(
            oversized.into_request(vec![b'a'; MAX_RAW_BODY_SIZE + 1]),
            Err(ProtocolError::RawBodyTooLarge)
        ));
    }

    #[test]
    fn response_envelope_rejects_invalid_failure_shapes() {
        let payload = br#"{"ok":false,"key":"payload"}"#;
        let response: ValidationResponseEnvelope =
            serde_json::from_slice(payload).expect("response");
        assert!(matches!(
            response.validate(),
            Err(ProtocolError::InvalidEnvelope(message)) if message.contains("rejected responses")
        ));
    }

    #[tokio::test]
    async fn write_frame_does_not_force_flush_per_response() {
        let mut writer = RecordingWriter::default();

        write_frame(&mut writer, br#"{"ok":true}"#)
            .await
            .expect("write frame");

        assert_eq!(
            writer.written,
            encode_frame(br#"{"ok":true}"#).expect("encoded frame")
        );
        assert_eq!(writer.flush_calls, 0);
    }

    #[tokio::test]
    async fn write_ok_frame_uses_compact_preencoded_payload() {
        let mut writer = RecordingWriter::default();

        write_ok_frame(&mut writer).await.expect("write ok frame");

        assert_eq!(
            writer.written,
            encode_frame(OK_RESPONSE_BYTES).expect("encoded frame")
        );
    }
}
