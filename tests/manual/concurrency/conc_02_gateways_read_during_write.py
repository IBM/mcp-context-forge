#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/manual/concurrency/conc_02_gateways_read_during_write.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CONC-02 manual concurrency check: read during write for /gateways/{id}.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections import Counter
import os
import time

# Third-Party
import httpx


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return value


def _build_config() -> dict[str, object]:
    token = os.getenv("CONC_TOKEN", "").strip()
    if not token:
        raise ValueError("CONC_TOKEN is required")

    return {
        "base_url": os.getenv("CONC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        "token": token,
        "name_prefix": os.getenv("CONC_NAME_PREFIX", "conc-gw").strip() or "conc-gw",
        "gateway_url": os.getenv("CONC_GATEWAY_URL", "http://127.0.0.1:9000/sse").strip(),
        "duration_sec": _env_int("CONC_RW_DURATION_SEC", 20),
        "reader_workers": _env_int("CONC_RW_READERS", 5),
        "writer_workers": _env_int("CONC_RW_WRITERS", 1),
        "req_timeout_sec": _env_int("CONC_RW_TIMEOUT_SEC", 20),
    }


def _is_valid_read_payload(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, f"payload_type={type(payload).__name__}"
    required = ("id", "name", "url")
    for key in required:
        if key not in payload:
            return False, f"missing_field={key}"
    url = payload.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False, f"invalid_url={url!r}"
    return True, "ok"


async def _create_baseline_gateway(client: httpx.AsyncClient, base_url: str, token: str, gateway_name: str, gateway_url: str) -> str:
    response = await client.post(
        f"{base_url}/gateways",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": gateway_name, "url": gateway_url, "visibility": "public"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected create response payload type: {type(payload).__name__}")
    gateway_id = payload.get("id")
    if not isinstance(gateway_id, str) or not gateway_id:
        raise ValueError(f"Could not find gateway id in create response: {payload}")
    return gateway_id


async def _writer(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    gateway_id: str,
    gateway_name: str,
    base_gateway_url: str,
    stop_time: float,
    worker_id: int,
) -> Counter:
    counts: Counter = Counter()
    i = 0
    while time.monotonic() < stop_time:
        i += 1
        next_url = f"{base_gateway_url}?rw={worker_id}-{i}-{int(time.time() * 1000)}"
        try:
            response = await client.put(
                f"{base_url}/gateways/{gateway_id}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"name": gateway_name, "url": next_url, "visibility": "public"},
            )
            counts[response.status_code] += 1
        except Exception as exc:  # pragma: no cover - manual script behavior
            counts[f"EXC:{type(exc).__name__}"] += 1
        await asyncio.sleep(0.01)
    return counts


async def _reader(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    gateway_id: str,
    stop_time: float,
    read_errors: list[str],
) -> Counter:
    counts: Counter = Counter()
    while time.monotonic() < stop_time:
        try:
            response = await client.get(
                f"{base_url}/gateways/{gateway_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            counts[response.status_code] += 1
            if response.status_code == 200:
                try:
                    payload = response.json()
                except Exception as exc:  # pragma: no cover - manual script behavior
                    read_errors.append(f"json_decode_error:{type(exc).__name__}")
                    continue
                ok, reason = _is_valid_read_payload(payload)
                if not ok:
                    read_errors.append(reason)
        except Exception as exc:  # pragma: no cover - manual script behavior
            counts[f"EXC:{type(exc).__name__}"] += 1
        await asyncio.sleep(0.01)
    return counts


async def _run() -> int:
    try:
        cfg = _build_config()
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    base_url = str(cfg["base_url"])
    token = str(cfg["token"])
    name_prefix = str(cfg["name_prefix"])
    gateway_url = str(cfg["gateway_url"])
    duration_sec = int(cfg["duration_sec"])
    reader_workers = int(cfg["reader_workers"])
    writer_workers = int(cfg["writer_workers"])
    timeout = httpx.Timeout(int(cfg["req_timeout_sec"]))

    run_id = int(time.time() * 1000)
    gateway_name = f"{name_prefix}-read-write-{run_id}"

    print("CONC-02 Read During Write (Gateways)")
    print(f"Target read: GET {base_url}/gateways/{{id}}")
    print(f"Target write: PUT {base_url}/gateways/{{id}}")
    print(f"Duration: {duration_sec}s")
    print(f"Readers: {reader_workers}")
    print(f"Writers: {writer_workers}")
    print(f"Gateway name: {gateway_name}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            gateway_id = await _create_baseline_gateway(client, base_url, token, gateway_name, gateway_url)
        except Exception as exc:
            print(f"SETUP ERROR: failed to create baseline gateway: {type(exc).__name__}: {exc}")
            return 1

        print(f"Baseline gateway id: {gateway_id}")
        stop_time = time.monotonic() + duration_sec
        read_errors: list[str] = []

        writer_tasks = [_writer(client, base_url, token, gateway_id, gateway_name, gateway_url, stop_time, idx + 1) for idx in range(writer_workers)]
        reader_tasks = [_reader(client, base_url, token, gateway_id, stop_time, read_errors) for _ in range(reader_workers)]

        task_results = await asyncio.gather(*writer_tasks, *reader_tasks)

        final_read = await client.get(
            f"{base_url}/gateways/{gateway_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        final_payload_ok = False
        final_payload_reason = "not_checked"
        if final_read.status_code == 200:
            final_payload_ok, final_payload_reason = _is_valid_read_payload(final_read.json())
        else:
            final_payload_reason = f"final_status={final_read.status_code}"

    write_counts: Counter = Counter()
    read_counts: Counter = Counter()
    for idx, result in enumerate(task_results):
        if idx < writer_workers:
            write_counts.update(result)
        else:
            read_counts.update(result)

    print("\nStatus/Error distribution:")
    print("Write path (PUT /gateways/{id}):")
    for key, value in sorted(write_counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {key}: {value}")

    print("Read path (GET /gateways/{id}):")
    for key, value in sorted(read_counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {key}: {value}")

    write_5xx = sum(v for k, v in write_counts.items() if isinstance(k, int) and 500 <= k <= 599)
    read_5xx = sum(v for k, v in read_counts.items() if isinstance(k, int) and 500 <= k <= 599)

    print("\nAssertions:")
    print(f"  write_5xx == 0 -> {write_5xx}")
    print(f"  read_5xx == 0 -> {read_5xx}")
    print(f"  malformed_read_payloads == 0 -> {len(read_errors)}")
    print(f"  final_read_status == 200 -> {final_read.status_code}")
    print(f"  final_payload_valid == True -> {final_payload_ok} ({final_payload_reason})")

    if read_errors:
        print("\nMalformed read payload examples (up to 10):")
        for item in read_errors[:10]:
            print(f"  - {item}")

    passed = write_5xx == 0 and read_5xx == 0 and len(read_errors) == 0 and final_read.status_code == 200 and final_payload_ok
    if passed:
        print("\nPASS: CONC-02 read-during-write consistency checks passed.")
        return 0

    print("\nFAIL: CONC-02 read-during-write checks failed.")
    return 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
