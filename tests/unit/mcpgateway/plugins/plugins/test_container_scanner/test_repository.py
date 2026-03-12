#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_repository.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for ScanResultRepository.
"""

from __future__ import annotations

import datetime

import pytest

from plugins.container_scanner.storage.repository import ScanResultRepository
from plugins.container_scanner.types import ScanResult, Summary


DIGEST_V1 = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST_V2 = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST_V3 = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
DIGEST_UNKNOWN = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def make_result(image_digest: str = DIGEST_V1, image_ref: str = "ghcr.io/org/app:v1") -> ScanResult:
    return ScanResult(
        image_ref=image_ref,
        image_digest=image_digest,
        scanners="trivy",
        scan_time=datetime.datetime.now(datetime.timezone.utc),
        duration_ms=100,
        vulnerabilities=[],
        summary=Summary(critical_count=0, high_count=0, medium_count=0, low_count=0),
        blocked=False,
    )


class TestScanResultRepositorySaveAndGet:
    def test_save_and_get_round_trip(self):
        repo = ScanResultRepository()
        result = make_result(DIGEST_V1)
        repo.save(result)
        assert repo.get(DIGEST_V1) is result

    def test_get_unknown_digest_returns_none(self):
        repo = ScanResultRepository()
        assert repo.get(DIGEST_UNKNOWN) is None

    def test_save_overwrites_previous_result(self):
        repo = ScanResultRepository()
        first = make_result(DIGEST_V1)
        second = make_result(DIGEST_V1)
        repo.save(first)
        repo.save(second)
        assert repo.get(DIGEST_V1) is second

    def test_update_does_not_grow_store(self):
        repo = ScanResultRepository()
        repo.save(make_result(DIGEST_V1))
        repo.save(make_result(DIGEST_V1))
        assert len(repo) == 1


class TestScanResultRepositoryEviction:
    def test_evicts_oldest_when_at_capacity(self):
        repo = ScanResultRepository(max_entries=2)
        repo.save(make_result(DIGEST_V1))
        repo.save(make_result(DIGEST_V2))
        repo.save(make_result(DIGEST_V3))  # triggers eviction of DIGEST_V1
        assert repo.get(DIGEST_V1) is None
        assert repo.get(DIGEST_V2) is not None
        assert repo.get(DIGEST_V3) is not None

    def test_len_does_not_exceed_max(self):
        repo = ScanResultRepository(max_entries=3)
        for i in range(10):
            digest = f"sha256:{i:064x}"
            repo.save(make_result(digest))
        assert len(repo) == 3

    def test_update_existing_does_not_evict(self):
        repo = ScanResultRepository(max_entries=3)
        repo.save(make_result(DIGEST_V1))
        repo.save(make_result(DIGEST_V2))
        # Update existing — should not evict
        repo.save(make_result(DIGEST_V1))
        assert repo.get(DIGEST_V2) is not None
        assert repo.get(DIGEST_V1) is not None
        assert len(repo) == 2


class TestScanResultRepositoryClear:
    def test_clear_removes_all_entries(self):
        repo = ScanResultRepository()
        repo.save(make_result(DIGEST_V1))
        repo.save(make_result(DIGEST_V2))
        repo.clear()
        assert len(repo) == 0
        assert repo.get(DIGEST_V1) is None

    def test_len_after_clear_is_zero(self):
        repo = ScanResultRepository()
        repo.save(make_result(DIGEST_V1))
        repo.clear()
        assert len(repo) == 0
