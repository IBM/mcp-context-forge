# -*- coding: utf-8 -*-
"""This module is used to dowload and pre-cache tokenizers to the skillet server."""

try:
    # Third-Party
    import nltk

    nltk.download("punkt")
    nltk.download("punkt_tab")
except ImportError:
    print("Skipping download of nltk tokenizers")


try:
    # Third-Party
    import llm_guard
    from llm_guard.vault import Vault

    llm_guard.input_scanners.PromptInjection()
    llm_guard.input_scanners.TokenLimit()
    llm_guard.input_scanners.Toxicity()
    config = {"vault": Vault()}
    llm_guard.input_scanners.Anonymize(config)
    llm_guard.output_scanners.Deanonymize(config)
    config = ({"patterns": ["Bearer [A-Za-z0-9-._~+/]+"]},)
    llm_guard.output_scanners.Regex(patterns=[r"Bearer [A-Za-z0-9-._~+/]+"])
    llm_guard.output_scanners.Toxicity()

except ImportError:
    print("Skipping download of llm-guard models")
