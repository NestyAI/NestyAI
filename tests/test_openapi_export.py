"""tests/test_openapi_export.py

Tests for scripts/export_openapi.py:
- --stdout outputs valid JSON.
- Default mode writes docs/openapi.json.
- --check passes when the file is up to date.
- --check fails when the file is missing.
- --check fails when the file is stale.

No real providers are called. The script only calls app.openapi().
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_openapi.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    """Helper: run export_openapi.py with the given args and capture output."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


# ---------------------------------------------------------------------------
# --stdout flag
# ---------------------------------------------------------------------------

def test_stdout_flag_outputs_valid_json() -> None:
    result = run_script("--stdout")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Must be parseable JSON.
    schema = json.loads(result.stdout)
    # Basic OpenAPI shape checks.
    assert "openapi" in schema
    assert "paths" in schema
    assert "info" in schema


def test_stdout_schema_has_chat_endpoint() -> None:
    result = run_script("--stdout")
    assert result.returncode == 0
    schema = json.loads(result.stdout)
    paths = schema.get("paths", {})
    assert "/v1/chat/completions" in paths, (
        "/v1/chat/completions must be in the OpenAPI schema paths"
    )


def test_stdout_schema_has_health_endpoint() -> None:
    result = run_script("--stdout")
    assert result.returncode == 0
    schema = json.loads(result.stdout)
    paths = schema.get("paths", {})
    assert "/health" in paths or "/ready" in paths, (
        "At least one health endpoint must appear in the OpenAPI schema"
    )


# ---------------------------------------------------------------------------
# Default (file-write) mode
# ---------------------------------------------------------------------------

def test_default_mode_writes_openapi_json(tmp_path, monkeypatch) -> None:
    """The default mode writes docs/openapi.json inside the project root.

    We verify the file exists and is valid JSON after the script runs.
    (The script always overwrites this path relative to ROOT.)
    """
    result = run_script()
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out_file = ROOT / "docs" / "openapi.json"
    assert out_file.exists(), "docs/openapi.json must exist after default export"
    schema = json.loads(out_file.read_text(encoding="utf-8"))
    assert "openapi" in schema


# ---------------------------------------------------------------------------
# --check flag: up-to-date
# ---------------------------------------------------------------------------

def test_check_flag_passes_when_file_is_current() -> None:
    """--check should exit 0 when docs/openapi.json matches the live schema."""
    # First generate the file.
    gen = run_script()
    assert gen.returncode == 0

    # Then --check should pass.
    check = run_script("--check")
    assert check.returncode == 0, (
        f"--check should pass when file is up to date.\nstdout: {check.stdout}\nstderr: {check.stderr}"
    )
    assert "PASS" in check.stdout


# ---------------------------------------------------------------------------
# --check flag: missing file
# ---------------------------------------------------------------------------

def test_check_flag_fails_when_file_missing(tmp_path, monkeypatch) -> None:
    """--check should exit 1 when docs/openapi.json is missing.

    We monkey-patch the ROOT-relative out_path by temporarily renaming the file.
    """
    out_file = ROOT / "docs" / "openapi.json"
    backup = ROOT / "docs" / "openapi.json.bak"

    existed = out_file.exists()
    if existed:
        out_file.rename(backup)

    try:
        check = run_script("--check")
        assert check.returncode == 1, (
            "--check should fail (exit 1) when docs/openapi.json is missing"
        )
    finally:
        if existed:
            backup.rename(out_file)
        elif backup.exists():
            backup.unlink()


# ---------------------------------------------------------------------------
# --check flag: stale file
# ---------------------------------------------------------------------------

def test_check_flag_fails_when_file_stale(tmp_path) -> None:
    """--check should exit 1 when docs/openapi.json has different content."""
    out_file = ROOT / "docs" / "openapi.json"
    backup = tmp_path / "openapi_backup.json"

    existed = out_file.exists()
    if existed:
        backup.write_bytes(out_file.read_bytes())

    try:
        # Write intentionally wrong content.
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text('{"openapi": "stale-version"}', encoding="utf-8")

        check = run_script("--check")
        assert check.returncode == 1, (
            "--check should fail (exit 1) when docs/openapi.json is stale"
        )
    finally:
        if existed:
            out_file.write_bytes(backup.read_bytes())
        elif out_file.exists():
            out_file.unlink()
