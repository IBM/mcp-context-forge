#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render JMeter plans by inlining shared REST/MCP fragments.

Usage:
  python3 tests/jmeter/render_fragments.py --out /tmp/jmeter-rendered
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List

TEMPLATES = [
    Path("tests/jmeter/rest_api_baseline.jmx"),
    Path("tests/jmeter/load_test.jmx"),
    Path("tests/jmeter/soak_test.jmx"),
    Path("tests/jmeter/stress_test.jmx"),
    Path("tests/jmeter/spike_test.jmx"),
    Path("tests/jmeter/mcp_jsonrpc_baseline.jmx"),
]

REST_FRAGMENT = Path("tests/jmeter/fragments/rest_mix.jmx")
MCP_FRAGMENT = Path("tests/jmeter/fragments/mcp_mix.jmx")

REST_CONTROLLER = "REST Mix Root"
MCP_CONTROLLER = "MCP Mix Root"

REST_MARKER = "<!-- Shared REST Mix -->"
MCP_MARKER = "<!-- Shared MCP Mix -->"


def _strip_common_indent(lines: List[str]) -> List[str]:
    indents = []
    for line in lines:
        if line.strip():
            indents.append(len(line) - len(line.lstrip(" ")))
    if not indents:
        return lines
    trim = min(indents)
    return [line[trim:] if len(line) >= trim else "" for line in lines]


def extract_controller_block(path: Path, controller_name: str) -> List[str]:
    lines = path.read_text().splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if "<GenericController" in line and f'testname="{controller_name}"' in line:
            start_idx = i
            break
    if start_idx is None:
        raise ValueError(f"Controller {controller_name} not found in {path}")

    # Find the hashTree that belongs to this controller
    hash_start = None
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip() == "<hashTree>":
            hash_start = i
            break
    if hash_start is None:
        raise ValueError(f"hashTree for {controller_name} not found in {path}")

    depth = 0
    end_idx = None
    for i in range(hash_start, len(lines)):
        line = lines[i].strip()
        if line == "<hashTree>":
            depth += 1
        elif line == "</hashTree>":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx is None:
        raise ValueError(f"Closing hashTree for {controller_name} not found in {path}")

    block = lines[start_idx : end_idx + 1]
    return _strip_common_indent(block)


def replace_marker_block(
    lines: List[str],
    marker: str,
    block_lines: List[str],
) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == marker:
            indent = line.split("<")[0]
            out.append(line)
            out.extend([indent + l if l else "" for l in block_lines])
            # Skip until after the IncludeController hashTree
            i += 1
            while i < len(lines):
                if lines[i].strip() == "<hashTree/>":
                    i += 1
                    break
                i += 1
            continue
        out.append(line)
        i += 1
    return out


def render_template(template_path: Path, out_dir: Path, rest_block: List[str], mcp_block: List[str]) -> None:
    lines = template_path.read_text().splitlines()
    if REST_MARKER in template_path.read_text():
        lines = replace_marker_block(lines, REST_MARKER, rest_block)
    if MCP_MARKER in template_path.read_text():
        lines = replace_marker_block(lines, MCP_MARKER, mcp_block)

    out_path = out_dir / template_path.name
    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render JMeter plans with shared fragments.")
    parser.add_argument("--out", required=True, help="Output directory for rendered JMX files")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rest_block = extract_controller_block(REST_FRAGMENT, REST_CONTROLLER)
    mcp_block = extract_controller_block(MCP_FRAGMENT, MCP_CONTROLLER)

    for template in TEMPLATES:
        render_template(template, out_dir, rest_block, mcp_block)


if __name__ == "__main__":
    main()
