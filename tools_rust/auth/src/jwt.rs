// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JwtVerificationConfig {
    pub secret: String,
    pub algorithm: String,
    pub audience: String,
    pub issuer: String,
    pub verify_audience: bool,
    pub verify_issuer: bool,
    pub require_expiration: bool,
    pub require_jti: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JwtVerifyError {
    MissingRequiredExpiration,
    MissingRequiredJti,
    ExpiredToken,
    InvalidToken,
}

pub fn verify_jwt_token(
    token: &str,
    config: &JwtVerificationConfig,
) -> Result<Value, JwtVerifyError> {
    let algorithm = match config.algorithm.as_str() {
        "HS256" => Algorithm::HS256,
        _ => return Err(JwtVerifyError::InvalidToken),
    };

    let mut validation = Validation::new(algorithm);
    validation.validate_aud = config.verify_audience;
    validation.validate_exp = config.require_expiration;
    validation.validate_nbf = false;

    if config.require_expiration {
        validation.required_spec_claims.insert("exp".to_string());
    } else {
        validation.required_spec_claims.remove("exp");
    }

    if config.verify_audience {
        validation.set_audience(&[config.audience.as_str()]);
    }

    if config.verify_issuer {
        validation.set_issuer(&[config.issuer.as_str()]);
    }

    let payload = decode::<Value>(
        token,
        &DecodingKey::from_secret(config.secret.as_bytes()),
        &validation,
    )
    .map(|data| data.claims)
    .map_err(|err| match err.kind() {
        jsonwebtoken::errors::ErrorKind::ExpiredSignature => JwtVerifyError::ExpiredToken,
        jsonwebtoken::errors::ErrorKind::MissingRequiredClaim(claim) if claim == "exp" => {
            JwtVerifyError::MissingRequiredExpiration
        }
        _ => JwtVerifyError::InvalidToken,
    })?;

    if config.require_jti
        && !payload
            .as_object()
            .is_some_and(|payload| payload.contains_key("jti"))
    {
        return Err(JwtVerifyError::MissingRequiredJti);
    }

    Ok(payload)
}
