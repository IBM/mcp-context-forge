# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/test_makefile_rust_targets.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
RUST_RUNTIME_DEVELOPING = Path(__file__).resolve().parents[2] / "crates" / "mcp_runtime" / "DEVELOPING.md"


def _target_body(target: str) -> str:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith("\t") and not line.startswith(" "):
            break
        body.append(line)
    return "\n".join(body)


def _target_commands(target: str) -> list[str]:
    return [line.strip().removeprefix("@") for line in _target_body(target).splitlines()]


def test_rust_coverage_generates_html_xml_and_terminal_report() -> None:
    body = _target_body("rust-coverage")
    commands = _target_commands("rust-coverage")

    assert "--html" in body
    assert "--output-dir coverage/rust" in body
    assert "--cobertura --output-path coverage/cobertura.xml" in body
    assert "cargo llvm-cov report" in commands
    assert "coverage/rust/html/index.html" in body


def test_rust_diff_cover_uses_rust_cobertura_xml() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    body = _target_body("rust-diff-cover")

    assert "rust-diff-cover" in makefile
    assert "rust-diff-cover: rust-ensure-deps" not in makefile
    assert "coverage/cobertura.xml" in body
    assert "No coverage/cobertura.xml found - running rust-coverage first" in body
    assert "$(MAKE) --no-print-directory rust-coverage" in body
    assert "diff-cover coverage/cobertura.xml --compare-branch=main --fail-under=90" in body


def test_rust_runtime_developing_doc_mentions_root_coverage_targets() -> None:
    docs = RUST_RUNTIME_DEVELOPING.read_text(encoding="utf-8")

    assert "make rust-coverage" in docs
    assert "make rust-diff-cover" in docs
