# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/validation/tags.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tag validation and normalization utilities.
This module provides validation and normalization for tags used across
all MCP Gateway entities (tools, resources, prompts, servers, gateways).
"""

# Standard
import re
from typing import Dict, List, Optional


class TagValidator:
    """Validator and normalizer for entity tags.

    Ensures tags follow consistent formatting rules:
    - Minimum length: 2 characters
    - Maximum length: 50 characters
    - Allowed characters: lowercase letters, numbers, hyphens, colons, dots
    - Must start and end with alphanumeric characters
    - Automatic normalization to lowercase, trimmed

    Examples:
        >>> TagValidator.normalize("Finance")
        'finance'
        >>> TagValidator.normalize("  ANALYTICS  ")
        'analytics'
        >>> TagValidator.validate("ml")
        True
        >>> TagValidator.validate("a")
        False
        >>> TagValidator.validate_list(["Finance", "FINANCE", " finance "])
        [{'id': 'finance', 'label': 'Finance'}]

    Attributes:
        MIN_LENGTH (int): Minimum allowed tag length (2).
        MAX_LENGTH (int): Maximum allowed tag length (50).
        ALLOWED_PATTERN (str): Regular expression pattern for valid tags.
    """

    MIN_LENGTH = 2
    MAX_LENGTH = 50
    # Pattern: start with alphanumeric, middle can have hyphen/colon/dot, end with alphanumeric
    # Single character tags are allowed if they are alphanumeric
    ALLOWED_PATTERN = r"^[a-z0-9]([a-z0-9\-\:\.]*[a-z0-9])?$"

    @staticmethod
    def normalize(tag: str) -> str:
        """Normalize a tag to standard format.

        Converts to lowercase, strips whitespace, and replaces spaces with hyphens.

        Args:
            tag: The tag string to normalize.

        Returns:
            The normalized tag string.

        Examples:
            >>> TagValidator.normalize("Machine-Learning")
            'machine-learning'
            >>> TagValidator.normalize("  API  ")
            'api'
            >>> TagValidator.normalize("data  processing")
            'data-processing'
            >>> TagValidator.normalize("Machine Learning")
            'machine-learning'
            >>> TagValidator.normalize("under_score")
            'under-score'
        """
        # Strip whitespace and convert to lowercase
        normalized = tag.strip().lower()
        # Replace multiple spaces with single hyphen
        normalized = "-".join(normalized.split())
        # Replace underscores with hyphens for consistency
        normalized = normalized.replace("_", "-")
        return normalized

    @staticmethod
    def validate(tag: str) -> bool:
        """Validate a single tag.

        Checks if the tag meets all requirements. Tags with spaces are considered
        invalid in their raw form, even though they would be normalized to valid tags.

        Args:
            tag: The tag to validate.

        Returns:
            True if the tag is valid, False otherwise.

        Examples:
            >>> TagValidator.validate("analytics")
            True
            >>> TagValidator.validate("ml-models")
            True
            >>> TagValidator.validate("v2.0")
            True
            >>> TagValidator.validate("team:backend")
            True
            >>> TagValidator.validate("")
            False
            >>> TagValidator.validate("a")
            False
            >>> TagValidator.validate("-invalid")
            False
            >>> TagValidator.validate("invalid tag")
            False
        """
        # First check raw input for spaces (invalid in raw form)
        if " " in tag:
            return False

        normalized = TagValidator.normalize(tag)

        # Check length constraints
        if len(normalized) < TagValidator.MIN_LENGTH:
            return False
        if len(normalized) > TagValidator.MAX_LENGTH:
            return False

        # Check pattern
        if not re.match(TagValidator.ALLOWED_PATTERN, normalized):
            return False

        return True

    @staticmethod
    def validate_list(tags: Optional[List[str]]) -> List[Dict[str, str]]:
        """Validate and normalize a list of tags.

        Filters out invalid tags, removes duplicates, and handles edge cases.

        Args:
            tags: List of tags to validate and normalize.

        Returns:
            List of valid tag dicts with `id` (normalized tag) and `label` (original string).

        Examples:
            >>> TagValidator.validate_list(["Analytics", "ANALYTICS", "ml"])
            [{'id': 'analytics', 'label': 'Analytics'}, {'id': 'ml', 'label': 'ml'}]
            >>> TagValidator.validate_list(["", "a", "valid-tag"])
            [{'id': 'valid-tag', 'label': 'valid-tag'}]
            >>> TagValidator.validate_list(None)
            []
            >>> TagValidator.validate_list([" Finance ", "FINANCE", "  finance  "])
            [{'id': 'finance', 'label': 'Finance'}]
            >>> TagValidator.validate_list(["API", None, "", "  ", "api"])
            [{'id': 'api', 'label': 'API'}]
            >>> TagValidator.validate_list(["Machine Learning", "machine-learning"])
            [{'id': 'machine-learning', 'label': 'Machine Learning'}]
        """
        if not tags:
            return []

        # Filter out None values and convert everything to strings
        string_tags = [str(tag) for tag in tags if tag is not None]

        # Normalize all tags while preserving the original input for the label
        normalized_pairs: List[tuple[str, str]] = []
        for tag in string_tags:
            # Skip empty strings or strings with only whitespace
            if tag and tag.strip():
                original = tag.strip()
                normalized = TagValidator.normalize(original)
                normalized_pairs.append((normalized, original))

        # Filter valid tags and remove duplicates while preserving order
        seen = set()
        valid_tags: List[Dict[str, str]] = []
        for normalized, original in normalized_pairs:
            # Validate and check for duplicates (use normalized value for uniqueness)
            if normalized and TagValidator.validate(normalized) and normalized not in seen:
                seen.add(normalized)
                valid_tags.append({"id": normalized, "label": original})

        return valid_tags

    @staticmethod
    def get_validation_errors(tags: List[str]) -> List[str]:
        """Get validation errors for a list of tags.

        Returns specific error messages for invalid tags.

        Args:
            tags: List of tags to check.

        Returns:
            List of error messages for invalid tags.

        Examples:
            >>> TagValidator.get_validation_errors(["", "a", "valid-tag", "-invalid"])
            ['Tag "" is too short (minimum 2 characters)', 'Tag "a" is too short (minimum 2 characters)', 'Tag "-invalid" contains invalid characters or format']
        """
        errors = []

        for tag in tags:
            normalized = TagValidator.normalize(tag)

            if len(normalized) < TagValidator.MIN_LENGTH:
                if len(normalized) == 0:
                    errors.append(f'Tag "{tag}" is too short (minimum {TagValidator.MIN_LENGTH} characters)')
                else:
                    errors.append(f'Tag "{normalized}" is too short (minimum {TagValidator.MIN_LENGTH} characters)')
            elif len(normalized) > TagValidator.MAX_LENGTH:
                errors.append(f'Tag "{normalized}" is too long (maximum {TagValidator.MAX_LENGTH} characters)')
            elif not re.match(TagValidator.ALLOWED_PATTERN, normalized):
                errors.append(f'Tag "{normalized}" contains invalid characters or format')

        return errors


def validate_tags_field(tags: Optional[List[str]]) -> List[str]:
    """Pydantic field validator for tags.

    Use this function as a field validator in Pydantic models.
    Silently filters out invalid tags and returns only valid ones.
    Ensures tags are unique, normalized, and valid.

    Args:
        tags: The tags list to validate.

    Returns:
        Validated and normalized list of unique tags (invalid tags are filtered out).

    Examples:
        >>> validate_tags_field(["Analytics", "ml"])
        [{'id': 'analytics', 'label': 'Analytics'}, {'id': 'ml', 'label': 'ml'}]
        >>> validate_tags_field(["valid", "", "a", "invalid-"])
        [{'id': 'valid', 'label': 'valid'}]
        >>> validate_tags_field(None)
        []
        >>> validate_tags_field(["API", "api", "  API  "])
        [{'id': 'api', 'label': 'API'}]
        >>> validate_tags_field(["machine learning", "Machine-Learning", "ML"])
        [{'id': 'machine-learning', 'label': 'machine learning'}, {'id': 'ml', 'label': 'ML'}]
    """
    # Handle None, empty lists, and any other falsy values
    if not tags:
        return []

    # Ensure we have a list (could be a single string by mistake)
    if isinstance(tags, str):
        tags = [tags]

    # Handle case where tags might contain comma-separated values
    # This helps if someone passes "tag1,tag2,tag3" as a single string
    expanded_tags = []
    for tag in tags:
        if tag and isinstance(tag, str) and "," in tag:
            # Split by comma and add individual tags
            expanded_tags.extend(t.strip() for t in tag.split(",") if t.strip())
        else:
            expanded_tags.append(tag)

    # Validate and normalize, filtering out invalid tags
    valid_tags = TagValidator.validate_list(expanded_tags)

    return valid_tags
