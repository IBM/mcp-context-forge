// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Experimental core-owned Rust auth service.

pub mod rpc {
    tonic::include_proto!("contextforge.auth.v1");
}

pub mod config;
pub mod core_auth_policy;

mod db;
mod error;
mod flow;
mod jwt;
mod normalize;
mod server;
mod state;
mod stats;
mod types;

pub use db::{
    ApiTokenLookupChecker, ApiTokenLookupRecord, RevocationChecker, UserAuthSnapshot,
    UserAuthSnapshotChecker, UserLookupChecker, UserLookupRecord,
};
pub use error::SidecarError;
pub use jwt::{JwtVerificationConfig, JwtVerifyError, verify_jwt_token};
pub use server::{build_router, run};
pub use state::AppState;
pub use types::{
    AuthContext, AuthenticateRequest, AuthenticateResponse, DenyResponse, HealthResponse,
};

#[cfg(test)]
pub(crate) use flow::{
    INTERNAL_RUNTIME_AUTH_HEADER, RUNTIME_HEADER, RUNTIME_NAME, proxy_authenticate,
};
#[cfg(test)]
pub(crate) use normalize::normalize_auth_context;
#[cfg(test)]
pub(crate) use server::verify_backend_readiness;

#[cfg(test)]
mod tests;
