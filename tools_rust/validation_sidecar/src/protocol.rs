// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Framing and request/response envelopes for the validation sidecar.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::fmt::Display;
use thiserror::Error;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

pub const FRAME_PREFIX_LEN: usize = 4;
pub const MAX_FRAME_SIZE: usize = 16 * 1024 * 1024;
pub const MAX_RAW_BODY_SIZE: usize = 1024 * 1024;

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
    #[error("invalid base64 request body: {0}")]
    InvalidBase64(#[from] base64::DecodeError),
    #[error("{0}")]
    InvalidEnvelope(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationRequestEnvelope {
    pub request_body_b64: String,
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
    pub fn into_request(self) -> Result<ValidationRequest, ProtocolError> {
        if self.max_param_length == 0 {
            return Err(ProtocolError::InvalidEnvelope(
                "max_param_length must be greater than zero".to_owned(),
            ));
        }

        let raw_body = STANDARD.decode(self.request_body_b64.as_bytes())?;
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
            request_body_b64: STANDARD.encode(self.raw_body.as_slice()),
            max_param_length: self.max_param_length,
            dangerous_patterns: self.dangerous_patterns.clone(),
            request_id: self.request_id.clone(),
            healthcheck: self.healthcheck,
        }
    }
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
    writer.flush().await?;
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

pub fn invalid_envelope<M: Display>(message: M) -> ProtocolError {
    ProtocolError::InvalidEnvelope(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn request_envelope_round_trip_base64_encodes_raw_body() {
        let request =
            ValidationRequest::from_raw_body(br#"{"hello":"world"}"#, 32, &default_patterns())
                .expect("request");
        let encoded = serde_json::to_vec(&request.to_envelope()).expect("json");
        let decoded: ValidationRequestEnvelope =
            serde_json::from_slice(&encoded).expect("decode envelope");
        let round_trip = decoded.into_request().expect("into request");

        assert_eq!(round_trip.raw_body, br#"{"hello":"world"}"#);
        assert_eq!(round_trip.dangerous_patterns, default_patterns());
    }

    #[test]
    fn request_envelope_rejects_invalid_json_and_oversized_bodies() {
        let invalid_json = br#"{"request_body_b64":"***","max_param_length":1}"#;
        let envelope: ValidationRequestEnvelope =
            serde_json::from_slice(invalid_json).expect("envelope");
        assert!(matches!(
            envelope.into_request(),
            Err(ProtocolError::InvalidBase64(_))
        ));

        let oversized = ValidationRequestEnvelope {
            request_body_b64: STANDARD.encode(vec![b'a'; MAX_RAW_BODY_SIZE + 1]),
            max_param_length: 8,
            dangerous_patterns: Vec::new(),
            request_id: None,
            healthcheck: false,
        };
        assert!(matches!(
            oversized.into_request(),
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
}
