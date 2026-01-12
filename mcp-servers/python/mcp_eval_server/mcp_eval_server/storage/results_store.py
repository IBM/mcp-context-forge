# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/storage/results_store.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Results storage system for MCP Eval Server.
"""

# Standard
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

import orjson

class ResultsStore:
    """SQLite-based storage for evaluation results."""

    def __init__(self, db_path: str = "evaluation_results.db"):
        """Initialize results store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    results_id TEXT UNIQUE NOT NULL,
                    suite_id TEXT,
                    suite_name TEXT,
                    overall_score REAL,
                    passed BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    execution_time REAL,
                    test_data_summary TEXT,
                    detailed_results TEXT,
                    metadata TEXT
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    results_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    score REAL,
                    execution_time REAL,
                    result_data TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (results_id) REFERENCES evaluation_results (results_id)
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS judge_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judge_model TEXT NOT NULL,
                    response_hash TEXT NOT NULL,
                    criteria_hash TEXT NOT NULL,
                    overall_score REAL,
                    confidence REAL,
                    reasoning TEXT,
                    scores TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    execution_time REAL
                )
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_results_suite ON evaluation_results(suite_id);
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_steps_results ON evaluation_steps(results_id);
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_judge_model ON judge_evaluations(judge_model);
            """
            )

    async def store_evaluation_result(self, result: Dict[str, Any]) -> str:
        """Store complete evaluation result.

        Args:
            result: Evaluation result dictionary

        Returns:
            Stored results_id
        """
        results_id = result["results_id"]

        with sqlite3.connect(self.db_path) as conn:
            # Store main result
            conn.execute(
                """
                INSERT OR REPLACE INTO evaluation_results (
                    results_id, suite_id, suite_name, overall_score, passed,
                    execution_time, test_data_summary, detailed_results, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    results_id,
                    result.get("suite_id"),
                    result.get("suite_name"),
                    result.get("overall_score"),
                    result.get("pass_fail_status", {}).get("passed"),
                    result.get("execution_info", {}).get("duration_seconds"),
                    orjson.dumps(result.get("test_data_summary", {})).decode(),
                    orjson.dumps(result).decode(),
                    orjson.dumps(result.get("metadata", {})).decode(),
                ),
            )

            # Store step results
            for step_result in result.get("step_results", []):
                conn.execute(
                    """
                    INSERT INTO evaluation_steps (
                        results_id, tool_name, success, score, execution_time,
                        result_data, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        results_id,
                        step_result.get("tool"),
                        step_result.get("success"),
                        self._extract_score(step_result.get("result", {})),
                        step_result.get("execution_time"),
                        orjson.dumps(step_result.get("result", {})).decode(),
                        step_result.get("error"),
                    ),
                )

        return results_id

    def _extract_score(self, result: Dict[str, Any]) -> Optional[float]:
        """Extract numeric score from result.

        Args:
            result: Dictionary containing result data that may have score fields.

        Returns:
            Optional[float]: Extracted score as float if found, None otherwise.
        """
        score_fields = ["overall_score", "score", "clarity_score", "coherence_score", "factuality_score", "completion_rate", "accuracy"]

        for field in score_fields:
            if field in result:
                score = result[field]
                if isinstance(score, (int, float)):
                    return float(score)

        return None

    async def get_evaluation_result(self, results_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve evaluation result by ID.

        Args:
            results_id: Unique result identifier

        Returns:
            Evaluation result or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get main result
            cursor = conn.execute(
                """
                SELECT * FROM evaluation_results WHERE results_id = ?
            """,
                (results_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            result = dict(row)
            result["detailed_results"] = orjson.loads(result["detailed_results"])
            result["test_data_summary"] = orjson.loads(result["test_data_summary"])
            result["metadata"] = orjson.loads(result["metadata"])

            return result

    async def list_evaluation_results(self, suite_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List evaluation results with optional filtering.

        Args:
            suite_id: Filter by suite ID
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of evaluation result summaries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if suite_id:
                cursor = conn.execute(
                    """
                    SELECT results_id, suite_id, suite_name, overall_score,
                           passed, created_at, execution_time
                    FROM evaluation_results
                    WHERE suite_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """,
                    (suite_id, limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT results_id, suite_id, suite_name, overall_score,
                           passed, created_at, execution_time
                    FROM evaluation_results
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """,
                    (limit, offset),
                )

            return [dict(row) for row in cursor.fetchall()]

    async def store_judge_evaluation(self, judge_model: str, response_hash: str, criteria_hash: str, evaluation: Dict[str, Any], execution_time: float) -> None:
        """Store judge evaluation result.

        Args:
            judge_model: Judge model used
            response_hash: Hash of response text
            criteria_hash: Hash of evaluation criteria
            evaluation: Judge evaluation result
            execution_time: Time taken for evaluation
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO judge_evaluations (
                    judge_model, response_hash, criteria_hash, overall_score,
                    confidence, reasoning, scores, execution_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    judge_model,
                    response_hash,
                    criteria_hash,
                    evaluation.get("overall_score"),
                    evaluation.get("confidence"),
                    orjson.dumps(evaluation.get("reasoning", {})).decode(),
                    orjson.dumps(evaluation.get("scores", {})).decode(),
                    execution_time,
                ),
            )

    async def get_evaluation_statistics(self) -> Dict[str, Any]:
        """Get overall evaluation statistics.

        Returns:
            Statistics dictionary
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total_evaluations,
                    AVG(overall_score) as avg_score,
                    SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed_count,
                    AVG(execution_time) as avg_execution_time,
                    MIN(created_at) as first_evaluation,
                    MAX(created_at) as last_evaluation
                FROM evaluation_results
            """
            )

            stats = dict(cursor.fetchone())

            # Get suite statistics
            cursor = conn.execute(
                """
                SELECT
                    suite_name,
                    COUNT(*) as count,
                    AVG(overall_score) as avg_score
                FROM evaluation_results
                WHERE suite_name IS NOT NULL
                GROUP BY suite_name
                ORDER BY count DESC
                LIMIT 10
            """
            )

            stats["top_suites"] = [dict(row) for row in cursor.fetchall()]

            return stats

    async def cleanup_old_results(self, days_old: int = 30) -> int:
        """Clean up old evaluation results.

        Args:
            days_old: Remove results older than this many days

        Returns:
            Number of results removed
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                DELETE FROM evaluation_results
                WHERE created_at < datetime('now', '-{days_old} days')
            """
            )

            # Steps are deleted automatically due to foreign key constraint

            return cursor.rowcount
