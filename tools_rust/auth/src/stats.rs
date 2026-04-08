// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use serde::{Deserialize, Serialize};
use std::{
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AuthStatsSnapshot {
    pub authenticate_requests: u64,
    pub direct_auth_responses: u64,
    pub proxied_auth_responses: u64,
    pub revocation_cache_hits: u64,
    pub revocation_cache_misses: u64,
    pub user_snapshot_cache_hits: u64,
    pub user_snapshot_cache_misses: u64,
    pub api_token_cache_hits: u64,
    pub api_token_cache_misses: u64,
    pub session_auth_snapshot_cache_hits: u64,
    pub session_auth_snapshot_cache_misses: u64,
    pub api_token_auth_snapshot_cache_hits: u64,
    pub api_token_auth_snapshot_cache_misses: u64,
    pub backend_round_trips: u64,
    pub backend_round_trip_total_ms: u64,
    pub backend_round_trip_max_ms: u64,
    pub backend_failures: u64,
    pub shadow_compare_requests: u64,
    pub shadow_compare_mismatches: u64,
}

#[derive(Debug, Default)]
pub struct AuthStats {
    authenticate_requests: AtomicU64,
    direct_auth_responses: AtomicU64,
    proxied_auth_responses: AtomicU64,
    revocation_cache_hits: AtomicU64,
    revocation_cache_misses: AtomicU64,
    user_snapshot_cache_hits: AtomicU64,
    user_snapshot_cache_misses: AtomicU64,
    api_token_cache_hits: AtomicU64,
    api_token_cache_misses: AtomicU64,
    session_auth_snapshot_cache_hits: AtomicU64,
    session_auth_snapshot_cache_misses: AtomicU64,
    api_token_auth_snapshot_cache_hits: AtomicU64,
    api_token_auth_snapshot_cache_misses: AtomicU64,
    backend_round_trips: AtomicU64,
    backend_round_trip_total_ms: AtomicU64,
    backend_round_trip_max_ms: AtomicU64,
    backend_failures: AtomicU64,
    shadow_compare_requests: AtomicU64,
    shadow_compare_mismatches: AtomicU64,
}

impl AuthStats {
    pub fn snapshot(&self) -> AuthStatsSnapshot {
        AuthStatsSnapshot {
            authenticate_requests: self.authenticate_requests.load(Ordering::Relaxed),
            direct_auth_responses: self.direct_auth_responses.load(Ordering::Relaxed),
            proxied_auth_responses: self.proxied_auth_responses.load(Ordering::Relaxed),
            revocation_cache_hits: self.revocation_cache_hits.load(Ordering::Relaxed),
            revocation_cache_misses: self.revocation_cache_misses.load(Ordering::Relaxed),
            user_snapshot_cache_hits: self.user_snapshot_cache_hits.load(Ordering::Relaxed),
            user_snapshot_cache_misses: self.user_snapshot_cache_misses.load(Ordering::Relaxed),
            api_token_cache_hits: self.api_token_cache_hits.load(Ordering::Relaxed),
            api_token_cache_misses: self.api_token_cache_misses.load(Ordering::Relaxed),
            session_auth_snapshot_cache_hits: self
                .session_auth_snapshot_cache_hits
                .load(Ordering::Relaxed),
            session_auth_snapshot_cache_misses: self
                .session_auth_snapshot_cache_misses
                .load(Ordering::Relaxed),
            api_token_auth_snapshot_cache_hits: self
                .api_token_auth_snapshot_cache_hits
                .load(Ordering::Relaxed),
            api_token_auth_snapshot_cache_misses: self
                .api_token_auth_snapshot_cache_misses
                .load(Ordering::Relaxed),
            backend_round_trips: self.backend_round_trips.load(Ordering::Relaxed),
            backend_round_trip_total_ms: self.backend_round_trip_total_ms.load(Ordering::Relaxed),
            backend_round_trip_max_ms: self.backend_round_trip_max_ms.load(Ordering::Relaxed),
            backend_failures: self.backend_failures.load(Ordering::Relaxed),
            shadow_compare_requests: self.shadow_compare_requests.load(Ordering::Relaxed),
            shadow_compare_mismatches: self.shadow_compare_mismatches.load(Ordering::Relaxed),
        }
    }

    pub fn record_authenticate_request(&self) {
        self.authenticate_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_backend_round_trip(&self, elapsed: Duration, failed: bool) {
        self.backend_round_trips.fetch_add(1, Ordering::Relaxed);
        let elapsed_ms = elapsed.as_millis().min(u128::from(u64::MAX)) as u64;
        self.backend_round_trip_total_ms
            .fetch_add(elapsed_ms, Ordering::Relaxed);
        update_max_counter(&self.backend_round_trip_max_ms, elapsed_ms);
        if failed {
            self.backend_failures.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn record_direct_auth_response(&self) {
        self.direct_auth_responses.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_proxied_auth_response(&self) {
        self.proxied_auth_responses.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_revocation_cache_hit(&self) {
        self.revocation_cache_hits.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_revocation_cache_miss(&self) {
        self.revocation_cache_misses.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_user_snapshot_cache_hit(&self) {
        self.user_snapshot_cache_hits
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_user_snapshot_cache_miss(&self) {
        self.user_snapshot_cache_misses
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_api_token_cache_hit(&self) {
        self.api_token_cache_hits.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_api_token_cache_miss(&self) {
        self.api_token_cache_misses.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_session_auth_snapshot_cache_hit(&self) {
        self.session_auth_snapshot_cache_hits
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_session_auth_snapshot_cache_miss(&self) {
        self.session_auth_snapshot_cache_misses
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_api_token_auth_snapshot_cache_hit(&self) {
        self.api_token_auth_snapshot_cache_hits
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_api_token_auth_snapshot_cache_miss(&self) {
        self.api_token_auth_snapshot_cache_misses
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_shadow_compare(&self, mismatch: bool) {
        self.shadow_compare_requests.fetch_add(1, Ordering::Relaxed);
        if mismatch {
            self.shadow_compare_mismatches
                .fetch_add(1, Ordering::Relaxed);
        }
    }
}

fn update_max_counter(counter: &AtomicU64, candidate: u64) {
    let mut current = counter.load(Ordering::Relaxed);
    while candidate > current {
        match counter.compare_exchange_weak(
            current,
            candidate,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}
