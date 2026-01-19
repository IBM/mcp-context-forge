# -*- coding: utf-8 -*-
"""Tests for secrets detection plugin regex patterns."""

import pytest

from plugins.secrets_detection.secrets_detection import PATTERNS


class TestAwsSecretPattern:
    """Test AWS secret access key pattern for correctness."""

    @pytest.fixture
    def pattern(self):
        """Get the AWS secret pattern."""
        return PATTERNS["aws_secret_access_key"]

    def test_matches_standard_format(self, pattern):
        """Pattern should match standard AWS secret key format."""
        text = "AWS_SECRET_ACCESS_KEY=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        assert pattern.search(text) is not None

    def test_matches_with_separators(self, pattern):
        """Pattern should match with various separators."""
        assert pattern.search("aws_secret_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("aws-access-key=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("AWS_SECRET=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")

    def test_case_insensitive(self, pattern):
        """Pattern should be case-insensitive for the prefix."""
        assert pattern.search("aws_secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("AWS_SECRET=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("Aws_Secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")

    def test_no_match_short_secret(self, pattern):
        """Pattern should not match secrets shorter than 40 chars."""
        # Too short
        assert pattern.search("aws_secret=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh") is None

    def test_no_match_missing_equals(self, pattern):
        """Pattern should not match without = sign."""
        assert pattern.search("aws_secret ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd") is None

    def test_no_match_unrelated_text(self, pattern):
        """Pattern should not match unrelated text."""
        assert pattern.search("This is just some random text") is None
        assert pattern.search("aws is a cloud provider") is None

    def test_captures_secret_value(self, pattern):
        """Pattern should capture the 40-char secret value."""
        text = "AWS_SECRET_ACCESS_KEY=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        match = pattern.search(text)
        assert match is not None
        assert match.group(1) == "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
