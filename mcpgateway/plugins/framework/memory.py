# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/memory.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Memory management utilities for plugin framework.

This module provides copy-on-write data structures for efficient memory management
in plugin contexts.
"""

# Standard
from typing import Any, Iterator, Optional, TypeVar

T = TypeVar("T")


class CopyOnWriteDict(dict):
    """
    A dictionary subclass that implements copy-on-write behavior.

    Inherits from dict and layers modifications over an original dictionary
    without mutating the original. The dict itself stores modifications, while
    reads check the modifications first, then fall back to the original.

    This is useful for plugin contexts where you want to isolate modifications
    without copying the entire original dictionary upfront. Since it subclasses
    dict, it's compatible with type checking and validation frameworks like Pydantic.

    Example:
        >>> original = {"a": 1, "b": 2, "c": 3}
        >>> cow = CopyOnWriteDict(original)
        >>> isinstance(cow, dict)
        True
        >>> cow["a"] = 10  # Modification stored in dict
        >>> cow["d"] = 4   # New key stored in dict
        >>> del cow["b"]   # Deletion tracked separately
        >>> cow["a"]
        10
        >>> "b" in cow
        False
        >>> original  # Original unchanged
        {'a': 1, 'b': 2, 'c': 3}
        >>> cow.get_modifications()
        {'a': 10, 'd': 4}
    """

    def __init__(self, original: dict):
        """
        Initialize a copy-on-write dictionary wrapper.

        Args:
            original: The original dictionary to wrap. This will not be modified.
        """
        # Initialize parent dict without any data
        # The parent dict (self via super()) will store modifications only
        super().__init__()
        self._original = original
        self._deleted = set()  # Track keys that have been deleted

    def __getitem__(self, key: Any) -> Any:
        """
        Get an item from the dictionary.

        Args:
            key: The key to look up.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If the key is not found or has been deleted.
        """
        if key in self._deleted:
            raise KeyError(key)
        # Check modifications first (via super()), then original
        if super().__contains__(key):
            return super().__getitem__(key)
        if key in self._original:
            return self._original[key]
        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Set an item in the dictionary.

        The modification is stored in the wrapper layer, not the original dict.

        Args:
            key: The key to set.
            value: The value to associate with the key.
        """
        super().__setitem__(key, value)  # Store in modifications (parent dict)
        self._deleted.discard(key)  # If we're setting it, it's not deleted

    def __delitem__(self, key: Any) -> None:
        """
        Delete an item from the dictionary.

        The key is marked as deleted in the wrapper layer.

        Args:
            key: The key to delete.

        Raises:
            KeyError: If the key doesn't exist in the dictionary.
        """
        if key not in self:
            raise KeyError(key)
        self._deleted.add(key)
        if super().__contains__(key):
            super().__delitem__(key)  # Remove from modifications if present

    def __contains__(self, key: Any) -> bool:
        """
        Check if a key exists in the dictionary.

        Args:
            key: The key to check.

        Returns:
            True if the key exists and hasn't been deleted, False otherwise.
        """
        if key in self._deleted:
            return False
        return super().__contains__(key) or key in self._original

    def __len__(self) -> int:
        """
        Get the number of items in the dictionary.

        Returns:
            The count of non-deleted keys.
        """
        # Get all keys from both modifications and original, excluding deleted
        all_keys = set(super().keys()) | set(self._original.keys())
        return len(all_keys - self._deleted)

    def __iter__(self) -> Iterator:
        """
        Iterate over keys in the dictionary.

        Yields keys in insertion order: first keys from the original dict (in their
        original order), then new keys from modifications (in their insertion order).

        Yields:
            Keys that haven't been deleted.
        """
        # First, yield keys from original (in original order)
        for key in self._original:
            if key not in self._deleted:
                yield key

        # Then yield new keys from modifications (not in original)
        for key in super().__iter__():
            if key not in self._original and key not in self._deleted:
                yield key

    def __repr__(self) -> str:
        """
        Get a string representation of the dictionary.

        Returns:
            A string representation showing the current state.
        """
        return f"CopyOnWriteDict({dict(self.items())})"

    def get(self, key: Any, default: Optional[Any] = None) -> Any:
        """
        Get an item with a default fallback.

        Args:
            key: The key to look up.
            default: The value to return if the key is not found.

        Returns:
            The value associated with the key, or default if not found/deleted.
        """
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self):
        """
        Get all non-deleted keys.

        Returns:
            A generator of keys.
        """
        return iter(self)

    def values(self):
        """
        Get all values for non-deleted keys.

        Returns:
            A generator of values.
        """
        return (self[k] for k in self)

    def items(self):
        """
        Get all key-value pairs for non-deleted keys.

        Returns:
            A generator of (key, value) tuples.
        """
        return ((k, self[k]) for k in self)

    def copy(self) -> dict:
        """
        Create a regular dictionary with all current key-value pairs.

        Returns:
            A new dict containing the current state (original + modifications - deletions).
        """
        return dict(self.items())

    def get_modifications(self) -> dict:
        """
        Get only the modifications made to the wrapper.

        This returns only the keys that were added or changed in the modification layer,
        not including values from the original dictionary that weren't modified.

        Returns:
            A copy of the modifications dictionary.
        """
        # The parent dict (super()) contains only modifications
        return dict(super().items())

    def get_deleted(self) -> set:
        """
        Get the set of deleted keys.

        Returns:
            A copy of the deleted keys set.
        """
        return self._deleted.copy()

    def has_modifications(self) -> bool:
        """
        Check if any modifications have been made.

        Returns:
            True if there are any modifications or deletions, False otherwise.
        """
        # Check if parent dict has any entries (modifications) or if anything was deleted
        return super().__len__() > 0 or len(self._deleted) > 0

    def update(self, other=None, **kwargs) -> None:
        """
        Update the dictionary with key-value pairs from another mapping or iterable.

        Args:
            other: A mapping or iterable of key-value pairs.
            **kwargs: Additional key-value pairs to update.

        Examples:
            >>> cow = CopyOnWriteDict({"a": 1})
            >>> cow.update({"b": 2, "c": 3})
            >>> cow.update(d=4, e=5)
            >>> dict(cow.items())
            {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}
        """
        if other is not None:
            if hasattr(other, "items"):
                for key, value in other.items():
                    self[key] = value
            else:
                for key, value in other:
                    self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def pop(self, key: Any, *args) -> Any:
        """
        Remove and return the value for a key.

        Args:
            key: The key to remove.
            *args: Optional default value if key is not found.

        Returns:
            The value associated with the key.

        Raises:
            KeyError: If key is not found and no default is provided.
            TypeError: If more than one default argument is provided.

        Examples:
            >>> cow = CopyOnWriteDict({"a": 1, "b": 2})
            >>> cow.pop("a")
            1
            >>> cow.pop("c", "default")
            'default'
        """
        if len(args) > 1:
            raise TypeError(f"pop() accepts 1 or 2 arguments ({len(args) + 1} given)")

        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            if args:
                return args[0]
            raise

    def setdefault(self, key: Any, default: Any = None) -> Any:
        """
        Get a value, setting it to a default if not present.

        Args:
            key: The key to look up.
            default: The default value to set if key is not present.

        Returns:
            The value associated with the key (existing or newly set).

        Examples:
            >>> cow = CopyOnWriteDict({"a": 1})
            >>> cow.setdefault("a", 10)
            1
            >>> cow.setdefault("b", 2)
            2
            >>> cow["b"]
            2
        """
        if key in self:
            return self[key]
        self[key] = default
        return default

    def clear(self) -> None:
        """
        Remove all items from the dictionary.

        This marks all keys (from original and modifications) as deleted.

        Examples:
            >>> cow = CopyOnWriteDict({"a": 1, "b": 2})
            >>> cow.clear()
            >>> len(cow)
            0
        """
        # Mark all current keys as deleted
        for key in list(self.keys()):
            self._deleted.add(key)
        # Clear modifications from parent dict
        super().clear()


def copyonwrite(o: T) -> T:
    """
    Returns a copy-on-write wrapper of the original object.

    Args:
        o: The object to wrap. Currently only supports dict objects.

    Returns:
        A copy-on-write wrapper around the object.

    Raises:
        TypeError: If the object type is not supported for copy-on-write wrapping.
    """
    if isinstance(o, dict):
        return CopyOnWriteDict(o)
    raise TypeError(f"No copy-on-write wrapper available for {type(o)}")
