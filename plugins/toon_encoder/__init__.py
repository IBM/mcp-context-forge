# -*- coding: utf-8 -*-
"""TOON Encoder Plugin.

Converts JSON tool results to TOON (Token-Oriented Object Notation) format
for reduced token consumption when sending responses to LLM agents.

SPDX-License-Identifier: Apache-2.0
"""

from plugins.toon_encoder.toon import decode as toon_decode
from plugins.toon_encoder.toon import encode as toon_encode
from plugins.toon_encoder.toon_encoder import ToonEncoderPlugin

__all__ = ["ToonEncoderPlugin", "toon_encode", "toon_decode"]
