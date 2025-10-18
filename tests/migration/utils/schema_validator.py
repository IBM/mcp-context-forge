# -*- coding: utf-8 -*-
"""Location: ./tests/migration/utils/schema_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Schema validation utilities for migration testing.

This module provides comprehensive database schema comparison and validation
capabilities for ensuring migration integrity across MCP Gateway versions.
"""

# Standard
from dataclasses import dataclass
import difflib
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TableSchema:
    """Represents a database table schema."""

    name: str
    columns: Dict[str, str]  # column_name -> type
    constraints: List[str]
    indexes: List[str]
    foreign_keys: List[str]

    def __str__(self) -> str:
        return f"Table({self.name}, columns={len(self.columns)}, constraints={len(self.constraints)})"


@dataclass
class SchemaComparison:
    """Result of comparing two database schemas."""

    added_tables: List[str]
    removed_tables: List[str]
    modified_tables: List[str]
    added_columns: Dict[str, List[str]]  # table -> [columns]
    removed_columns: Dict[str, List[str]]
    modified_columns: Dict[str, List[str]]
    schema_diff: str
    compatibility_score: float
    breaking_changes: List[str]
    warnings: List[str]

    def is_compatible(self) -> bool:
        """Check if the schema change is backwards compatible."""
        return len(self.breaking_changes) == 0 and self.compatibility_score >= 0.8


class SchemaValidator:
    """Validates and compares database schemas across migrations.

    Provides comprehensive schema analysis including:
    - Table structure comparison
    - Column type validation
    - Constraint and index tracking
    - Breaking change detection
    - Compatibility scoring
    """

    def __init__(self):
        """Initialize schema validator."""
        self.schema_cache: Dict[str, Dict[str, TableSchema]] = {}
        logger.info("🔍 Initialized SchemaValidator")

    def parse_sqlite_schema(self, schema_sql: str) -> Dict[str, TableSchema]:
        """Parse SQLite schema SQL into structured format.

        Args:
            schema_sql: Raw SQLite schema dump

        Returns:
            Dictionary mapping table names to TableSchema objects
        """
        logger.info(f"🔍 Parsing SQLite schema ({len(schema_sql)} characters)")

        tables = {}

        # Split schema into individual CREATE statements
        statements = self._split_sql_statements(schema_sql)

        for statement in statements:
            if statement.strip().upper().startswith("CREATE TABLE"):
                table = self._parse_create_table_statement(statement)
                if table:
                    tables[table.name] = table
                    logger.debug(f"📋 Parsed table: {table}")

        logger.info(f"✅ Parsed {len(tables)} tables from schema")
        return tables

    def _split_sql_statements(self, sql: str) -> List[str]:
        """Split SQL dump into individual statements."""
        # Remove comments and normalize whitespace
        lines = []
        for line in sql.split("\n"):
            line = line.strip()
            if line and not line.startswith("--") and not line.startswith("/*"):
                lines.append(line)

        sql_clean = "\n".join(lines)

        # Split on semicolons, but be careful about semicolons in strings
        statements = []
        current_statement = []
        in_string = False
        string_char = None

        i = 0
        while i < len(sql_clean):
            char = sql_clean[i]

            if not in_string and char in ['"', "'"]:
                in_string = True
                string_char = char
            elif in_string and char == string_char:
                # Check if it's escaped
                if i == 0 or sql_clean[i - 1] != "\\":
                    in_string = False
                    string_char = None
            elif not in_string and char == ";":
                statement = "".join(current_statement).strip()
                if statement:
                    statements.append(statement)
                current_statement = []
                i += 1
                continue

            current_statement.append(char)
            i += 1

        # Add final statement
        statement = "".join(current_statement).strip()
        if statement:
            statements.append(statement)

        return statements

    def _parse_create_table_statement(self, statement: str) -> Optional[TableSchema]:
        """Parse a CREATE TABLE statement into TableSchema."""
        try:
            # Extract table name
            match = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(["`]?)(\w+)\\1', statement, re.IGNORECASE)
            if not match:
                logger.debug(f"Could not extract table name from: {statement[:100]}")
                return None

            table_name = match.group(2)

            # Extract column definitions between parentheses
            paren_start = statement.find("(")
            paren_end = statement.rfind(")")

            if paren_start == -1 or paren_end == -1:
                logger.debug(f"Could not find parentheses in CREATE TABLE: {table_name}")
                return None

            column_section = statement[paren_start + 1 : paren_end]

            columns = {}
            constraints = []
            indexes = []
            foreign_keys = []

            # Parse column definitions and constraints
            column_defs = self._split_column_definitions(column_section)

            for col_def in column_defs:
                col_def = col_def.strip()
                if not col_def:
                    continue

                # Check if it's a constraint or column definition
                if self._is_constraint_definition(col_def):
                    constraints.append(col_def)
                    if "FOREIGN KEY" in col_def.upper():
                        foreign_keys.append(col_def)
                else:
                    # Parse column definition
                    col_parts = col_def.split()
                    if len(col_parts) >= 2:
                        col_name = col_parts[0].strip('"`')
                        col_type = col_parts[1]

                        # Include constraints in column type
                        if len(col_parts) > 2:
                            col_type += " " + " ".join(col_parts[2:])

                        columns[col_name] = col_type

            return TableSchema(name=table_name, columns=columns, constraints=constraints, indexes=indexes, foreign_keys=foreign_keys)

        except Exception as e:
            logger.warning(f"Error parsing CREATE TABLE statement: {e}")
            logger.debug(f"Statement: {statement}")
            return None

    def _split_column_definitions(self, column_section: str) -> List[str]:
        """Split column definitions, respecting nested parentheses."""
        definitions = []
        current_def = []
        paren_depth = 0
        in_string = False
        string_char = None

        for char in column_section:
            if not in_string and char in ['"', "'"]:
                in_string = True
                string_char = char
            elif in_string and char == string_char:
                in_string = False
                string_char = None
            elif not in_string:
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                elif char == "," and paren_depth == 0:
                    definitions.append("".join(current_def))
                    current_def = []
                    continue

            current_def.append(char)

        # Add final definition
        if current_def:
            definitions.append("".join(current_def))

        return definitions

    def _is_constraint_definition(self, definition: str) -> bool:
        """Check if a definition is a table constraint rather than column."""
        constraint_keywords = ["PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "CONSTRAINT", "INDEX"]

        def_upper = definition.upper().strip()
        return any(keyword in def_upper for keyword in constraint_keywords)

    def compare_schemas(self, schema_before: Dict[str, TableSchema], schema_after: Dict[str, TableSchema]) -> SchemaComparison:
        """Compare two database schemas and identify changes.

        Args:
            schema_before: Schema before migration
            schema_after: Schema after migration

        Returns:
            Detailed schema comparison result
        """
        logger.info(f"🔍 Comparing schemas: {len(schema_before)} → {len(schema_after)} tables")

        # Find table-level changes
        before_tables = set(schema_before.keys())
        after_tables = set(schema_after.keys())

        added_tables = list(after_tables - before_tables)
        removed_tables = list(before_tables - after_tables)
        common_tables = before_tables & after_tables

        logger.info(f"📊 Table changes: +{len(added_tables)}, -{len(removed_tables)}, ~{len(common_tables)}")

        # Analyze column changes in common tables
        modified_tables = []
        added_columns = {}
        removed_columns = {}
        modified_columns = {}

        for table_name in common_tables:
            before_table = schema_before[table_name]
            after_table = schema_after[table_name]

            before_cols = set(before_table.columns.keys())
            after_cols = set(after_table.columns.keys())

            table_added_cols = list(after_cols - before_cols)
            table_removed_cols = list(before_cols - after_cols)
            common_cols = before_cols & after_cols

            # Check for modified columns
            table_modified_cols = []
            for col_name in common_cols:
                if before_table.columns[col_name] != after_table.columns[col_name]:
                    table_modified_cols.append(col_name)

            # Record changes if any exist
            if table_added_cols or table_removed_cols or table_modified_cols:
                modified_tables.append(table_name)

                if table_added_cols:
                    added_columns[table_name] = table_added_cols
                if table_removed_cols:
                    removed_columns[table_name] = table_removed_cols
                if table_modified_cols:
                    modified_columns[table_name] = table_modified_cols

        # Generate detailed diff
        schema_diff = self._generate_schema_diff(schema_before, schema_after)

        # Identify breaking changes and warnings
        breaking_changes, warnings = self._analyze_breaking_changes(added_tables, removed_tables, removed_columns, modified_columns)

        # Calculate compatibility score
        compatibility_score = self._calculate_compatibility_score(schema_before, schema_after, breaking_changes)

        comparison = SchemaComparison(
            added_tables=added_tables,
            removed_tables=removed_tables,
            modified_tables=modified_tables,
            added_columns=added_columns,
            removed_columns=removed_columns,
            modified_columns=modified_columns,
            schema_diff=schema_diff,
            compatibility_score=compatibility_score,
            breaking_changes=breaking_changes,
            warnings=warnings,
        )

        logger.info(f"✅ Schema comparison completed: compatibility={compatibility_score:.2f}")
        logger.info(f"🚨 Breaking changes: {len(breaking_changes)}, Warnings: {len(warnings)}")

        return comparison

    def _generate_schema_diff(self, schema_before: Dict[str, TableSchema], schema_after: Dict[str, TableSchema]) -> str:
        """Generate a unified diff of the schemas."""

        def schema_to_lines(schema: Dict[str, TableSchema]) -> List[str]:
            lines = []
            for table_name in sorted(schema.keys()):
                table = schema[table_name]
                lines.append(f"TABLE {table_name}:")
                for col_name in sorted(table.columns.keys()):
                    lines.append(f"  {col_name}: {table.columns[col_name]}")
                for constraint in sorted(table.constraints):
                    lines.append(f"  CONSTRAINT: {constraint}")
                lines.append("")
            return lines

        before_lines = schema_to_lines(schema_before)
        after_lines = schema_to_lines(schema_after)

        diff_lines = list(difflib.unified_diff(before_lines, after_lines, fromfile="schema_before", tofile="schema_after", lineterm=""))

        return "\n".join(diff_lines)

    def _analyze_breaking_changes(
        self, added_tables: List[str], removed_tables: List[str], removed_columns: Dict[str, List[str]], modified_columns: Dict[str, List[str]]
    ) -> Tuple[List[str], List[str]]:
        """Identify breaking changes and warnings."""
        breaking_changes = []
        warnings = []

        # Removed tables are always breaking
        for table in removed_tables:
            breaking_changes.append(f"Table '{table}' was removed")

        # Removed columns are breaking
        for table, columns in removed_columns.items():
            for column in columns:
                breaking_changes.append(f"Column '{table}.{column}' was removed")

        # Modified columns might be breaking (depends on the change)
        for table, columns in modified_columns.items():
            for column in columns:
                # For now, treat all column modifications as warnings
                # In a production system, we'd analyze the specific type changes
                warnings.append(f"Column '{table}.{column}' was modified")

        # Added tables are usually safe
        for table in added_tables:
            warnings.append(f"Table '{table}' was added")

        return breaking_changes, warnings

    def _calculate_compatibility_score(self, schema_before: Dict[str, TableSchema], schema_after: Dict[str, TableSchema], breaking_changes: List[str]) -> float:
        """Calculate a compatibility score between 0.0 and 1.0."""
        if not schema_before:
            return 1.0  # No baseline to compare

        total_elements = sum(len(table.columns) + len(table.constraints) for table in schema_before.values())

        if total_elements == 0:
            return 1.0

        # Each breaking change reduces compatibility
        penalty_per_breaking_change = 0.1
        compatibility = 1.0 - (len(breaking_changes) * penalty_per_breaking_change)

        return max(0.0, min(1.0, compatibility))

    def validate_schema_evolution(self, container_id: str, container_manager, expected_tables: Set[str] = None) -> Dict[str, any]:
        """Validate that schema evolution follows expected patterns.

        Args:
            container_id: Container to validate
            container_manager: Container manager instance
            expected_tables: Set of expected table names

        Returns:
            Validation results
        """
        logger.info(f"🔍 Validating schema evolution in {container_id[:12]}")

        try:
            # Get current schema
            schema_sql = container_manager.get_database_schema(container_id, "sqlite")
            current_schema = self.parse_sqlite_schema(schema_sql)

            validation_results = {"valid": True, "errors": [], "warnings": [], "table_count": len(current_schema), "tables": list(current_schema.keys())}

            # Check expected tables if provided
            if expected_tables:
                current_tables = set(current_schema.keys())
                missing_tables = expected_tables - current_tables
                extra_tables = current_tables - expected_tables

                if missing_tables:
                    validation_results["errors"].append(f"Missing expected tables: {missing_tables}")
                    validation_results["valid"] = False

                if extra_tables:
                    validation_results["warnings"].append(f"Unexpected tables found: {extra_tables}")

            # Validate table structures
            for table_name, table_schema in current_schema.items():
                table_errors = self._validate_table_structure(table_schema)
                if table_errors:
                    validation_results["errors"].extend(table_errors)
                    validation_results["valid"] = False

            # Check for common MCP Gateway tables
            core_tables = {"tools", "servers", "gateways", "alembic_version"}
            current_tables = set(current_schema.keys())

            missing_core = core_tables - current_tables
            if missing_core:
                validation_results["warnings"].append(f"Missing core MCP Gateway tables: {missing_core}")

            logger.info(f"✅ Schema validation completed: valid={validation_results['valid']}")
            return validation_results

        except Exception as e:
            logger.error(f"❌ Schema validation failed: {e}")
            return {"valid": False, "errors": [f"Validation exception: {str(e)}"], "warnings": [], "table_count": 0, "tables": []}

    def _validate_table_structure(self, table_schema: TableSchema) -> List[str]:
        """Validate individual table structure."""
        errors = []

        # Check for required columns based on table type
        if table_schema.name == "tools":
            required_cols = {"id", "name"}
            missing = required_cols - set(table_schema.columns.keys())
            if missing:
                errors.append(f"Table 'tools' missing required columns: {missing}")

        elif table_schema.name == "servers":
            required_cols = {"id", "name"}
            missing = required_cols - set(table_schema.columns.keys())
            if missing:
                errors.append(f"Table 'servers' missing required columns: {missing}")

        # Check for suspicious column types
        for col_name, col_type in table_schema.columns.items():
            if "BLOB" in col_type.upper() and col_name not in ["data", "content", "binary_data"]:
                errors.append(f"Suspicious BLOB column: {table_schema.name}.{col_name}")

        return errors

    def save_schema_snapshot(self, schema: Dict[str, TableSchema], version: str, output_dir: str) -> Path:
        """Save schema snapshot to file for future comparison.

        Args:
            schema: Schema to save
            version: Version identifier
            output_dir: Directory to save snapshot

        Returns:
            Path to saved snapshot file
        """
        output_path = Path(output_dir) / f"schema_v{version.replace('.', '_')}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert schema to serializable format
        schema_data = {}
        for table_name, table_schema in schema.items():
            schema_data[table_name] = {"columns": table_schema.columns, "constraints": table_schema.constraints, "indexes": table_schema.indexes, "foreign_keys": table_schema.foreign_keys}

        # Standard
        import json

        with open(output_path, "w") as f:
            json.dump({"version": version, "timestamp": time.time(), "tables": schema_data}, f, indent=2)

        logger.info(f"💾 Saved schema snapshot: {output_path}")
        return output_path

    def load_schema_snapshot(self, snapshot_file: Path) -> Dict[str, TableSchema]:
        """Load schema snapshot from file.

        Args:
            snapshot_file: Path to snapshot file

        Returns:
            Loaded schema
        """
        logger.info(f"📂 Loading schema snapshot: {snapshot_file}")

        # Standard
        import json

        with open(snapshot_file, "r") as f:
            data = json.load(f)

        schema = {}
        for table_name, table_data in data["tables"].items():
            schema[table_name] = TableSchema(
                name=table_name, columns=table_data["columns"], constraints=table_data["constraints"], indexes=table_data["indexes"], foreign_keys=table_data["foreign_keys"]
            )

        logger.info(f"✅ Loaded {len(schema)} tables from snapshot")
        return schema
