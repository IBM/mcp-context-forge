// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// PII Filter Plugin - Rust Implementation
//
// High-performance PII detection and masking using:
// - RegexSet for parallel pattern matching (5-10x faster)
// - Copy-on-write strings for zero-copy operations
// - Zero-copy JSON traversal with serde_json

pub mod config;
pub mod detector;
pub mod masking;
pub mod patterns;

pub use detector::PIIDetectorRust;
