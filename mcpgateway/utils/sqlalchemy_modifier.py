# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sqlalchemy_modifier.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

SQLAlchemy modifiers

- json_contains_expr: handles json_contains logic for different dialects
- json_contains_tag_expr: handles tag filtering for dict-format tags [{id, label}]
"""

# Standard
from typing import Any, Iterable, List, Union
import uuid

# Third-Party
import orjson
from sqlalchemy import and_, func, or_, text


def _ensure_list(values: Union[str, Iterable[str]]) -> List[str]:
    """
    Normalize input into a list of strings.

    Args:
        values: A single string or any iterable of strings. If `None`, an empty
            list is returned.

    Returns:
        A list of strings. If `values` is a string it will be wrapped in a
        single-item list; if it's already an iterable, it will be converted to
        a list. If `values` is `None`, returns an empty list.
    """
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return list(values)


def json_contains_tag_expr(session, col, values: Union[str, Iterable[str]], match_any: bool = True) -> Any:
    """
    Return a SQLAlchemy expression that is True when JSON column `col`
    contains tags matching the given values. Handles both legacy List[str]
    and new List[Dict[str, str]] (with 'id' field) tag formats.

    Args:
        session: database session
        col: column that contains JSON array of tags
        values: list of tag IDs to match against
        match_any: Boolean to set OR (True) or AND (False) matching

    Returns:
        Any: SQLAlchemy boolean expression suitable for use in .where()

    Raises:
        RuntimeError: If dialect is not supported
        ValueError: If values is empty
    """
    values_list = _ensure_list(values)
    if not values_list:
        raise ValueError("values must be non-empty")

    dialect = session.get_bind().dialect.name

    # ---------- MySQL ----------
    # For dict-format tags: use JSON_SEARCH to find tags with matching id
    # JSON_SEARCH returns path if found, NULL otherwise
    if dialect == "mysql":
        # Build conditions that check for both string tags and dict tags with matching id
        conditions = []
        for tag_value in values_list:
            # Check if tag exists as plain string OR as dict with matching id
            # JSON_SEARCH(col, 'one', value) finds plain string value
            # JSON_CONTAINS with path $.*.id checks dict format
            string_match = func.json_search(col, "one", tag_value).isnot(None)
            dict_match = func.json_contains(col, orjson.dumps([{"id": tag_value}]).decode()) == 1
            conditions.append(or_(string_match, dict_match))

        if match_any:
            return or_(*conditions)
        return and_(*conditions)

    # ---------- PostgreSQL ----------
    # For dict-format tags: use jsonb_path_query_array to extract ids
    if dialect == "postgresql":
        # Build conditions for each tag value
        conditions = []
        for tag_value in values_list:
            # Check if any element is the string OR has id matching the value
            # This handles both ["tag"] and [{"id": "tag", "label": "Tag"}] formats
            string_match = col.contains([tag_value])
            dict_match = col.contains([{"id": tag_value}])
            conditions.append(or_(string_match, dict_match))

        if match_any:
            return or_(*conditions)
        return and_(*conditions)

    # ---------- SQLite (json1) ----------
    # For dict-format tags: use json_extract to get the 'id' field
    # Use CASE WHEN type = 'object' to avoid "malformed JSON" error on string elements
    if dialect == "sqlite":
        table_name = getattr(getattr(col, "table", None), "name", None)
        column_name = getattr(col, "name", None) or str(col)
        col_ref = f"{table_name}.{column_name}" if table_name else column_name

        if match_any:
            # Build placeholders with unique param names
            params = {}
            placeholders = []
            for i, t in enumerate(values_list):
                pname = f"t_{uuid.uuid4().hex[:8]}_{i}"
                placeholders.append(f":{pname}")
                params[pname] = t
            placeholders_sql = ",".join(placeholders)
            # Check string values directly, extract $.id only from objects (type='object')
            sql = f"EXISTS (SELECT 1 FROM json_each({col_ref}) WHERE value IN ({placeholders_sql}) OR (CASE WHEN type = 'object' THEN json_extract(value, '$.id') END) IN ({placeholders_sql}))"  # nosec B608
            sq = text(sql)
            return sq.bindparams(**params)

        # all-of: return AND of EXISTS for each value
        exists_clauses = []
        for t in values_list:
            pname = f"t_{uuid.uuid4().hex[:8]}"
            # Check string values directly, extract $.id only from objects (type='object')
            sql = f"EXISTS (SELECT 1 FROM json_each({col_ref}) WHERE value = :{pname} OR (CASE WHEN type = 'object' THEN json_extract(value, '$.id') END) = :{pname})"  # nosec B608
            clause = text(sql).bindparams(**{pname: t})
            exists_clauses.append(clause)
        if len(exists_clauses) == 1:
            return exists_clauses[0]
        return and_(*exists_clauses)

    raise RuntimeError(f"Unsupported dialect for json_contains_tag: {dialect}")


def json_contains_expr(session, col, values: Union[str, Iterable[str]], match_any: bool = True) -> Any:
    """
    Return a SQLAlchemy expression that is True when JSON column `col`
    contains the scalar `value`. `session` is used to detect dialect.
    Assumes `col` is a JSON/JSONB column (array-of-strings case).

    Args:
        session: database session
        col: column that contains JSON
        values: list of values to check for in json
        match_any: Boolean to set OR or AND matching

    Returns:
        Any: SQLAlchemy boolean expression suitable for use in .where()

    Raises:
        RuntimeError: If dialect is not supported
        ValueError: If values is empty
    """
    values_list = _ensure_list(values)
    if not values_list:
        raise ValueError("values must be non-empty")

    dialect = session.get_bind().dialect.name

    # ---------- MySQL ----------
    # - all-of: JSON_CONTAINS(col, '["a","b"]') == 1
    # - any-of: prefer JSON_OVERLAPS (MySQL >= 8.0.17), otherwise OR of JSON_CONTAINS for each value
    if dialect == "mysql":
        try:
            if match_any:
                # JSON_OVERLAPS exists in modern MySQL; SQLAlchemy will emit func.json_overlaps(...)
                return func.json_overlaps(col, orjson.dumps(values_list).decode()) == 1
            else:
                return func.json_contains(col, orjson.dumps(values_list).decode()) == 1
        except Exception:
            # Fallback: compose OR of json_contains for each scalar
            if match_any:
                return or_(*[func.json_contains(col, orjson.dumps(t).decode()) == 1 for t in values_list])
            else:
                return and_(*[func.json_contains(col, orjson.dumps(t).decode()) == 1 for t in values_list])

    # ---------- PostgreSQL ----------
    # - all-of: col.contains(list)  (works if col is JSONB)
    # - any-of: use OR of col.contains([value]) (or use ?| operator if you prefer)
    if dialect == "postgresql":
        # prefer JSONB .contains for all-of
        if not match_any:
            return col.contains(values_list)
        # match_any: use OR over element-containment
        return or_(*[col.contains([t]) for t in values_list])

    # ---------- SQLite (json1) ----------
    # SQLite doesn't have JSON_CONTAINS. We build safe SQL:
    # - any-of: single EXISTS ... WHERE value IN (:p0,:p1,...)
    # - all-of: multiple EXISTS with unique bind params (one EXISTS per value) => AND semantics
    if dialect == "sqlite":
        table_name = getattr(getattr(col, "table", None), "name", None)
        column_name = getattr(col, "name", None) or str(col)
        col_ref = f"{table_name}.{column_name}" if table_name else column_name

        if match_any:
            # Build placeholders with unique param names and pass *values* to bindparams
            params = {}
            placeholders = []
            for i, t in enumerate(values_list):
                pname = f"t_{uuid.uuid4().hex[:8]}_{i}"
                placeholders.append(f":{pname}")
                params[pname] = t
            placeholders_sql = ",".join(placeholders)
            sq = text(f"EXISTS (SELECT 1 FROM json_each({col_ref}) WHERE value IN ({placeholders_sql}))")  # nosec B608 - Safe: uses parameterized queries with bindparams()
            # IMPORTANT: pass plain values as kwargs to bindparams
            return sq.bindparams(**params)

        # all-of: return AND of EXISTS(... = :pX) with plain values
        exists_clauses = []
        for t in values_list:
            pname = f"t_{uuid.uuid4().hex[:8]}"
            clause = text(f"EXISTS (SELECT 1 FROM json_each({col_ref}) WHERE value = :{pname})").bindparams(**{pname: t})  # nosec B608 - Safe: uses parameterized queries with bindparams()
            exists_clauses.append(clause)
        if len(exists_clauses) == 1:
            return exists_clauses[0]
        return and_(*exists_clauses)

    raise RuntimeError(f"Unsupported dialect for json_contains: {dialect}")
