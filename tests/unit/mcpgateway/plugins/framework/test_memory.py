# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_memory.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for memory module.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.memory import copyonwrite, CopyOnWriteDict


class TestCopyOnWriteDict:
    """Test suite for CopyOnWriteDict class."""

    def test_is_dict_subclass(self):
        """Test that CopyOnWriteDict is a subclass of dict."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        assert isinstance(cow, dict)
        assert issubclass(CopyOnWriteDict, dict)

    def test_initialization(self):
        """Test that CopyOnWriteDict initializes correctly."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        # Verify all original keys are accessible
        assert cow["a"] == 1
        assert cow["b"] == 2
        assert cow["c"] == 3

        # Verify original is unchanged
        assert original == {"a": 1, "b": 2, "c": 3}

    def test_initialization_empty_dict(self):
        """Test initialization with an empty dictionary."""
        original = {}
        cow = CopyOnWriteDict(original)

        assert len(cow) == 0
        assert list(cow.keys()) == []

    def test_getitem_existing_key(self):
        """Test getting an existing key from the original dict."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        assert cow["a"] == 1
        assert cow["b"] == 2

    def test_getitem_nonexistent_key(self):
        """Test that getting a non-existent key raises KeyError."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        with pytest.raises(KeyError):
            _ = cow["nonexistent"]

    def test_getitem_deleted_key(self):
        """Test that getting a deleted key raises KeyError."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        with pytest.raises(KeyError):
            _ = cow["a"]

    def test_setitem_new_key(self):
        """Test setting a new key that doesn't exist in original."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2

        assert cow["b"] == 2
        assert "b" not in original  # Original unchanged
        assert original == {"a": 1}

    def test_setitem_override_existing_key(self):
        """Test overriding an existing key from the original dict."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10

        assert cow["a"] == 10
        assert original["a"] == 1  # Original unchanged

    def test_setitem_after_delete(self):
        """Test setting a key after it was deleted."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]
        cow["a"] = 10

        assert cow["a"] == 10
        assert "a" not in cow.get_deleted()

    def test_delitem_existing_key(self):
        """Test deleting an existing key from the original dict."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        assert "a" not in cow
        assert "a" in original  # Original unchanged
        assert original == {"a": 1, "b": 2}

    def test_delitem_modified_key(self):
        """Test deleting a key that was modified."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        del cow["a"]

        assert "a" not in cow
        assert original["a"] == 1  # Original unchanged

    def test_delitem_new_key(self):
        """Test deleting a key that was added to modifications."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2
        del cow["b"]

        assert "b" not in cow

    def test_delitem_nonexistent_key(self):
        """Test that deleting a non-existent key raises KeyError."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        with pytest.raises(KeyError):
            del cow["nonexistent"]

    def test_delitem_already_deleted(self):
        """Test that deleting an already deleted key raises KeyError."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        with pytest.raises(KeyError):
            del cow["a"]

    def test_contains_existing_key(self):
        """Test __contains__ for an existing key."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        assert "a" in cow
        assert "b" in cow

    def test_contains_new_key(self):
        """Test __contains__ for a newly added key."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2

        assert "b" in cow

    def test_contains_nonexistent_key(self):
        """Test __contains__ for a non-existent key."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        assert "nonexistent" not in cow

    def test_contains_deleted_key(self):
        """Test __contains__ for a deleted key."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        assert "a" not in cow
        assert "b" in cow

    def test_len_original_only(self):
        """Test __len__ with only original keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        assert len(cow) == 3

    def test_len_with_additions(self):
        """Test __len__ with added keys."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2
        cow["c"] = 3

        assert len(cow) == 3

    def test_len_with_deletions(self):
        """Test __len__ with deleted keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        del cow["a"]
        del cow["b"]

        assert len(cow) == 1

    def test_len_with_modifications(self):
        """Test __len__ with modifications (should not change length)."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10

        assert len(cow) == 2

    def test_len_empty(self):
        """Test __len__ when all keys are deleted."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        assert len(cow) == 0

    def test_iter_original_only(self):
        """Test __iter__ with only original keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        keys = list(cow)
        assert set(keys) == {"a", "b", "c"}

    def test_iter_with_additions(self):
        """Test __iter__ with added keys."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2
        cow["c"] = 3

        keys = list(cow)
        assert set(keys) == {"a", "b", "c"}

    def test_iter_with_deletions(self):
        """Test __iter__ with deleted keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        del cow["b"]

        keys = list(cow)
        assert set(keys) == {"a", "c"}

    def test_get_existing_key(self):
        """Test get() method for an existing key."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        assert cow.get("a") == 1
        assert cow.get("b") == 2

    def test_get_nonexistent_key_default_none(self):
        """Test get() method for non-existent key with default None."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        assert cow.get("nonexistent") is None

    def test_get_nonexistent_key_custom_default(self):
        """Test get() method for non-existent key with custom default."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        assert cow.get("nonexistent", "default") == "default"

    def test_get_deleted_key(self):
        """Test get() method for a deleted key returns default."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        assert cow.get("a") is None
        assert cow.get("a", "default") == "default"

    def test_keys_original_only(self):
        """Test keys() method with only original keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        keys = list(cow.keys())
        assert set(keys) == {"a", "b", "c"}

    def test_keys_with_modifications(self):
        """Test keys() method with modifications."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["c"] = 3
        del cow["a"]

        keys = list(cow.keys())
        assert set(keys) == {"b", "c"}

    def test_values_original_only(self):
        """Test values() method with only original values."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        values = list(cow.values())
        assert set(values) == {1, 2, 3}

    def test_values_with_modifications(self):
        """Test values() method with modifications."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        cow["c"] = 3
        del cow["b"]

        values = list(cow.values())
        assert set(values) == {10, 3}

    def test_items_original_only(self):
        """Test items() method with only original items."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        items = list(cow.items())
        assert set(items) == {("a", 1), ("b", 2), ("c", 3)}

    def test_items_with_modifications(self):
        """Test items() method with modifications."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        cow["c"] = 3
        del cow["b"]

        items = list(cow.items())
        assert set(items) == {("a", 10), ("c", 3)}

    def test_copy_original_only(self):
        """Test copy() method with only original data."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        copied = cow.copy()

        assert copied == {"a": 1, "b": 2, "c": 3}
        assert isinstance(copied, dict)
        assert copied is not original

    def test_copy_with_modifications(self):
        """Test copy() method with modifications."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        cow["c"] = 3
        del cow["b"]

        copied = cow.copy()

        assert copied == {"a": 10, "c": 3}
        assert isinstance(copied, dict)

    def test_get_modifications_no_changes(self):
        """Test get_modifications() with no changes."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        mods = cow.get_modifications()

        assert mods == {}

    def test_get_modifications_with_additions(self):
        """Test get_modifications() with added keys."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2
        cow["c"] = 3

        mods = cow.get_modifications()

        assert mods == {"b": 2, "c": 3}

    def test_get_modifications_with_overrides(self):
        """Test get_modifications() with overridden keys."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        cow["c"] = 3

        mods = cow.get_modifications()

        assert mods == {"a": 10, "c": 3}

    def test_get_modifications_with_deletions(self):
        """Test get_modifications() after deletions."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow["c"] = 3
        del cow["b"]

        mods = cow.get_modifications()

        # Deletions are not in modifications, only in deleted set
        assert mods == {"c": 3}

    def test_get_modifications_returns_copy(self):
        """Test that get_modifications() returns a copy, not the original."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2

        mods1 = cow.get_modifications()
        mods2 = cow.get_modifications()

        assert mods1 == mods2
        assert mods1 is not mods2

    def test_get_deleted_no_deletions(self):
        """Test get_deleted() with no deletions."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        deleted = cow.get_deleted()

        assert deleted == set()

    def test_get_deleted_with_deletions(self):
        """Test get_deleted() with deleted keys."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        del cow["a"]
        del cow["c"]

        deleted = cow.get_deleted()

        assert deleted == {"a", "c"}

    def test_get_deleted_returns_copy(self):
        """Test that get_deleted() returns a copy, not the original set."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        deleted1 = cow.get_deleted()
        deleted2 = cow.get_deleted()

        assert deleted1 == deleted2
        assert deleted1 is not deleted2

    def test_has_modifications_false(self):
        """Test has_modifications() returns False with no changes."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        assert not cow.has_modifications()

    def test_has_modifications_true_with_additions(self):
        """Test has_modifications() returns True with additions."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2

        assert cow.has_modifications()

    def test_has_modifications_true_with_overrides(self):
        """Test has_modifications() returns True with overrides."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10

        assert cow.has_modifications()

    def test_has_modifications_true_with_deletions(self):
        """Test has_modifications() returns True with deletions."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        del cow["a"]

        assert cow.has_modifications()

    def test_repr(self):
        """Test __repr__ method."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        repr_str = repr(cow)

        assert "CopyOnWriteDict" in repr_str
        assert "a" in repr_str or "1" in repr_str

    def test_repr_with_modifications(self):
        """Test __repr__ with modifications."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["b"] = 2
        del cow["a"]

        repr_str = repr(cow)

        assert "CopyOnWriteDict" in repr_str
        assert "b" in repr_str or "2" in repr_str

    def test_complex_workflow(self):
        """Test a complex workflow with multiple operations."""
        original = {"a": 1, "b": 2, "c": 3, "d": 4}
        cow = CopyOnWriteDict(original)

        # Perform various operations
        cow["a"] = 10  # Override
        cow["e"] = 5  # Add new
        del cow["b"]  # Delete
        cow["c"] = 30  # Override

        # Verify state
        assert cow["a"] == 10
        assert "b" not in cow
        assert cow["c"] == 30
        assert cow["d"] == 4
        assert cow["e"] == 5

        # Verify original unchanged
        assert original == {"a": 1, "b": 2, "c": 3, "d": 4}

        # Verify modifications
        assert cow.get_modifications() == {"a": 10, "c": 30, "e": 5}
        assert cow.get_deleted() == {"b"}
        assert cow.has_modifications()

        # Verify copy
        assert cow.copy() == {"a": 10, "c": 30, "d": 4, "e": 5}

    def test_original_dict_mutations_not_reflected(self):
        """Test that mutations to the original dict after COW creation are visible."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        # Mutate original - this WILL be visible in COW since ChainMap references the original
        original["c"] = 3

        # ChainMap references the original, so this change is visible
        assert cow["c"] == 3

    def test_nested_values(self):
        """Test that nested values work correctly."""
        original = {"a": {"nested": 1}, "b": [1, 2, 3]}
        cow = CopyOnWriteDict(original)

        # Read nested values
        assert cow["a"] == {"nested": 1}
        assert cow["b"] == [1, 2, 3]

        # Modify nested value
        cow["a"] = {"nested": 10}

        assert cow["a"] == {"nested": 10}
        assert original["a"] == {"nested": 1}

    def test_duplicate_operations(self):
        """Test duplicate operations on the same key."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        # Multiple modifications to same key
        cow["a"] = 10
        cow["a"] = 20
        cow["a"] = 30

        assert cow["a"] == 30
        assert cow.get_modifications() == {"a": 30}

    def test_delete_and_recreate(self):
        """Test deleting a key and then recreating it."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        del cow["a"]
        assert "a" not in cow

        cow["a"] = 10
        assert cow["a"] == 10
        assert "a" not in cow.get_deleted()

    def test_update_with_dict(self):
        """Test update() method with a dictionary."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow.update({"b": 2, "c": 3})

        assert cow["a"] == 1
        assert cow["b"] == 2
        assert cow["c"] == 3
        assert original == {"a": 1}

    def test_update_with_kwargs(self):
        """Test update() method with keyword arguments."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow.update(b=2, c=3)

        assert cow["b"] == 2
        assert cow["c"] == 3

    def test_update_with_both(self):
        """Test update() method with both dict and kwargs."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow.update({"b": 2}, c=3, d=4)

        assert cow["b"] == 2
        assert cow["c"] == 3
        assert cow["d"] == 4

    def test_update_with_iterable(self):
        """Test update() method with an iterable of pairs."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow.update([("b", 2), ("c", 3)])

        assert cow["b"] == 2
        assert cow["c"] == 3

    def test_update_overwrites_existing(self):
        """Test that update() overwrites existing keys."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow.update({"a": 10, "c": 3})

        assert cow["a"] == 10
        assert cow["b"] == 2
        assert cow["c"] == 3
        assert original["a"] == 1

    def test_pop_existing_key(self):
        """Test pop() method with existing key."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        value = cow.pop("a")

        assert value == 1
        assert "a" not in cow
        assert original == {"a": 1, "b": 2}

    def test_pop_nonexistent_key_with_default(self):
        """Test pop() method with non-existent key and default."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        value = cow.pop("nonexistent", "default")

        assert value == "default"

    def test_pop_nonexistent_key_no_default(self):
        """Test pop() method with non-existent key and no default raises KeyError."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        with pytest.raises(KeyError):
            cow.pop("nonexistent")

    def test_pop_too_many_args(self):
        """Test pop() with too many arguments raises TypeError."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        with pytest.raises(TypeError, match="pop\\(\\) accepts 1 or 2 arguments"):
            cow.pop("a", "default1", "default2")

    def test_pop_modified_key(self):
        """Test pop() on a key that was modified."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        cow["a"] = 10
        value = cow.pop("a")

        assert value == 10
        assert "a" not in cow

    def test_setdefault_existing_key(self):
        """Test setdefault() with an existing key."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        value = cow.setdefault("a", 10)

        assert value == 1
        assert cow["a"] == 1
        assert original == {"a": 1}

    def test_setdefault_new_key(self):
        """Test setdefault() with a new key."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        value = cow.setdefault("b", 2)

        assert value == 2
        assert cow["b"] == 2
        assert original == {"a": 1}

    def test_setdefault_default_none(self):
        """Test setdefault() with default None."""
        original = {"a": 1}
        cow = CopyOnWriteDict(original)

        value = cow.setdefault("b")

        assert value is None
        assert cow["b"] is None

    def test_clear(self):
        """Test clear() method."""
        original = {"a": 1, "b": 2, "c": 3}
        cow = CopyOnWriteDict(original)

        cow["d"] = 4
        cow.clear()

        assert len(cow) == 0
        assert list(cow.keys()) == []
        assert original == {"a": 1, "b": 2, "c": 3}

    def test_clear_empty_dict(self):
        """Test clear() on an empty dict."""
        original = {}
        cow = CopyOnWriteDict(original)

        cow.clear()

        assert len(cow) == 0

    def test_update_after_clear(self):
        """Test that update works after clear."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        cow.clear()
        cow.update({"c": 3, "d": 4})

        assert len(cow) == 2
        assert cow["c"] == 3
        assert cow["d"] == 4
        assert "a" not in cow
        assert "b" not in cow

    def test_iter_modifications_before_original(self):
        """Test that __iter__ yields modifications before original keys."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        # Modify existing key
        cow["a"] = 10

        keys = list(cow)
        # Should have both keys, but modifications take precedence
        assert set(keys) == {"a", "b"}
        # First key should be from modifications (a), since we modified it
        assert keys[0] == "a"

    def test_iter_skips_deleted_keys_in_modifications(self):
        """Test that __iter__ skips keys that are in modifications but marked deleted."""
        original = {"a": 1, "b": 2}
        cow = CopyOnWriteDict(original)

        # Modify a key (adds to modifications layer)
        cow["a"] = 10
        # Add a new key (also in modifications layer)
        cow["c"] = 3
        # Delete the modified key (marks as deleted but it's still in modifications layer)
        del cow["a"]

        keys = list(cow)
        # Should only have b (from original) and c (from modifications, not deleted)
        assert set(keys) == {"b", "c"}
        assert "a" not in keys


class TestCopyOnWriteFunction:
    """Test suite for copyonwrite() factory function."""

    def test_copyonwrite_with_dict(self):
        """Test copyonwrite() function with a dictionary."""
        original = {"a": 1, "b": 2}
        cow = copyonwrite(original)

        assert isinstance(cow, CopyOnWriteDict)
        assert isinstance(cow, dict)
        assert cow["a"] == 1
        assert cow["b"] == 2

    def test_copyonwrite_returns_copyonwritedict(self):
        """Test that copyonwrite() returns a CopyOnWriteDict instance."""
        original = {"x": 10}
        result = copyonwrite(original)

        assert type(result).__name__ == "CopyOnWriteDict"
        assert result["x"] == 10

    def test_copyonwrite_with_empty_dict(self):
        """Test copyonwrite() function with an empty dictionary."""
        original = {}
        cow = copyonwrite(original)

        assert isinstance(cow, CopyOnWriteDict)
        assert len(cow) == 0

    def test_copyonwrite_preserves_original(self):
        """Test that copyonwrite() doesn't modify the original dict."""
        original = {"a": 1}
        cow = copyonwrite(original)

        cow["a"] = 10
        cow["b"] = 2

        assert original == {"a": 1}
        assert cow["a"] == 10

    def test_copyonwrite_with_non_dict_raises_typeerror(self):
        """Test that copyonwrite() raises TypeError for non-dict types."""
        with pytest.raises(TypeError, match="No copy-on-write wrapper available"):
            copyonwrite([1, 2, 3])

        with pytest.raises(TypeError, match="No copy-on-write wrapper available"):
            copyonwrite("string")

        with pytest.raises(TypeError, match="No copy-on-write wrapper available"):
            copyonwrite(42)

        with pytest.raises(TypeError, match="No copy-on-write wrapper available"):
            copyonwrite({1, 2, 3})

        with pytest.raises(TypeError, match="No copy-on-write wrapper available"):
            copyonwrite(None)
