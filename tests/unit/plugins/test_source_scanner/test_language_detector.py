#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_language_detector.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for language detection.
"""

# First-Party
from plugins.source_scanner.language_detector import LanguageDetector


class TestLanguageDetection:
    """Test language detection in repositories."""

    def test_detect_python(self, tmp_path) -> None:
        """Test Python language detection."""
        (tmp_path / "script.py").write_text("print('hello')")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" in languages

    def test_detect_javascript(self, tmp_path) -> None:
        """Test JavaScript language detection."""
        (tmp_path / "app.js").write_text("console.log('hello');")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "javascript" in languages

    def test_detect_go(self, tmp_path) -> None:
        """Test Go language detection."""
        (tmp_path / "main.go").write_text("package main")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "go" in languages

    def test_detect_java_maven(self, tmp_path) -> None:
        """Test Java (Maven) language detection."""
        (tmp_path / "Main.java").write_text("public class Main {}")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "java" in languages

    def test_detect_ruby(self, tmp_path) -> None:
        """Test Ruby language detection."""
        (tmp_path / "app.rb").write_text("puts 'hello'")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "ruby" in languages

    def test_detect_php(self, tmp_path) -> None:
        """Test PHP language detection."""
        (tmp_path / "index.php").write_text("<?php echo 'hello'; ?>")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "php" in languages

    def test_detect_multiple_languages(self, tmp_path) -> None:
        """Test detection of multiple languages."""
        (tmp_path / "app.py").write_text("# Python")
        (tmp_path / "index.js").write_text("// JavaScript")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" in languages
        assert "javascript" in languages
        assert len(languages) >= 2

    def test_detect_empty_directory(self, tmp_path) -> None:
        """Test detection in directory with no code."""
        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert languages == []

    def test_detect_returns_sorted_list(self, mixed_project_dir) -> None:
        """Test that detected languages are returned sorted."""
        detector = LanguageDetector()
        languages = detector.detect(str(mixed_project_dir))

        assert languages == sorted(languages)

    def test_detects_typescript(self, tmp_path) -> None:
        """Test TypeScript language detection."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("const app = express();")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "typescript" in languages

    def test_detects_jsx(self, tmp_path) -> None:
        """Test JSX language detection."""
        jsx_file = tmp_path / "component.jsx"
        jsx_file.write_text("const Component = () => <div>Hello</div>;")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "javascript" in languages

    def test_detects_cpp(self, tmp_path) -> None:
        """Test C++ language detection."""
        cpp_file = tmp_path / "main.cpp"
        cpp_file.write_text("#include <iostream>")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "cpp" in languages

    def test_detects_csharp(self, tmp_path) -> None:
        """Test C# language detection."""
        cs_file = tmp_path / "Program.cs"
        cs_file.write_text("using System;")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "csharp" in languages

    def test_skips_hidden_directories(self, tmp_path) -> None:
        """Test that hidden directories are skipped."""
        # Create files in hidden directory
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()
        py_file = hidden_dir / "object.py"
        py_file.write_text("# Python file in .git should not be detected")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" not in languages

    def test_skips_node_modules(self, tmp_path) -> None:
        """Test that node_modules directory is skipped."""
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        py_file = node_modules / "unusual.py"
        py_file.write_text("# Python in node_modules should not be detected")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" not in languages

    def test_skips_pycache(self, tmp_path) -> None:
        """Test that __pycache__ directory is skipped."""
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        py_file = pycache / "module.py"
        py_file.write_text("# Python in __pycache__ should not be detected")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" not in languages

    def test_skips_venv(self, tmp_path) -> None:
        """Test that venv directory is skipped."""
        venv = tmp_path / "venv"
        venv.mkdir()
        py_file = venv / "site.py"
        py_file.write_text("# Python in venv should not be detected")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" not in languages

    def test_skips_build_and_dist(self, tmp_path) -> None:
        """Test that build and dist directories are skipped."""
        build = tmp_path / "build"
        build.mkdir()
        dist = tmp_path / "dist"
        dist.mkdir()

        py_file1 = build / "artifact.py"
        py_file2 = dist / "package.py"
        py_file1.write_text("# Build artifact")
        py_file2.write_text("# Dist artifact")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" not in languages

    def test_ignores_file_extensions_case(self, tmp_path) -> None:
        """Test that extension matching is case-insensitive."""
        # Create files with uppercase extensions
        py_upper = tmp_path / "script.PY"
        js_upper = tmp_path / "app.JS"
        py_upper.write_text("print('hello')")
        js_upper.write_text("console.log('hello')")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        assert "python" in languages
        assert "javascript" in languages

    def test_detects_multiple_files_same_language(self, tmp_path) -> None:
        """Test detection with multiple files of same language."""
        (tmp_path / "app.py").write_text("# Python")
        (tmp_path / "utils.py").write_text("# More Python")
        (tmp_path / "test.py").write_text("# Tests")

        detector = LanguageDetector()
        languages = detector.detect(str(tmp_path))

        # Should still only report python once
        assert languages.count("python") == 1
        assert languages == ["python"]
