from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_project_root
from app.core.config_validation import (
    validate_required_files,
    validate_model_chains,
    validate_env_safety,
    validate_runtime_setup,
)
from app.core.orchestration_roles import validate_orchestration_role_credentials

# Color ANSI escapes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def format_status(status: str) -> str:
    if status == "PASS":
        return f"[{GREEN}PASS{RESET}]"
    elif status == "WARN":
        return f"[{YELLOW}WARN{RESET}]"
    else:
        return f"[{RED}FAIL{RESET}]"


def main() -> int:
    print("=" * 60)
    print(" NestyAI Setup Diagnostics & Health Check (doctor)")
    print("=" * 60)

    # 1. Check Python Version
    print("\n1. System Environment Check:")
    py_ver = sys.version_info
    py_ver_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    if py_ver.major >= 3 and py_ver.minor >= 11:
        print(f"  {format_status('PASS')} Python version: {py_ver_str} (>= 3.11)")
        sys_pass = True
    else:
        print(f"  {format_status('FAIL')} Python version: {py_ver_str} is unsupported. Python 3.11+ is required.")
        sys_pass = False

    # 2. Check Package Imports
    required_packages = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("httpx", "httpx"),
        ("dotenv", "python-dotenv"),
        ("yaml", "PyYAML"),
        ("bs4", "beautifulsoup4"),
        ("trafilatura", "trafilatura"),
        ("idna", "idna"),
    ]

    import_failures = 0
    for pkg_import, pkg_name in required_packages:
        try:
            __import__(pkg_import)
        except ImportError:
            print(f"  {format_status('FAIL')} Package '{pkg_name}' is not installed or cannot be imported.")
            import_failures += 1

    if import_failures == 0:
        print(f"  {format_status('PASS')} All required core packages are importable.")
    else:
        print(f"  {format_status('FAIL')} Missing {import_failures} package(s). Please run: pip install -r requirements.txt")

    # 3. Required files
    print("\n2. Configuration & Required Files Check:")
    file_checks = validate_required_files(ROOT)
    for check in file_checks:
        print(f"  {format_status(check['status'])} {check['message']}")

    # 4. Model Chain Validation
    print("\n3. Model Strategy & Provider Chain Check:")
    model_checks = validate_model_chains(ROOT)
    for check in model_checks:
        print(f"  {format_status(check['status'])} {check['message']}")

    orchestration_checks = validate_orchestration_role_credentials()
    for check in orchestration_checks:
        print(f"  {format_status(check['status'])} {check['message']}")
    model_checks = model_checks + orchestration_checks

    # 5. Environment & Security Config
    print("\n4. Security & Environment Configuration Check:")
    env_checks = validate_env_safety()
    for check in env_checks:
        print(f"  {format_status(check['status'])} {check['message']}")

    # 6. Database and SQLite features
    print("\n5. Database & Runtime Setup Check:")
    runtime_checks = validate_runtime_setup()
    for check in runtime_checks:
        print(f"  {format_status(check['status'])} {check['message']}")

    # Collect status
    all_checks = file_checks + model_checks + env_checks + runtime_checks
    failed = [c for c in all_checks if c["status"] == "FAIL"]
    warned = [c for c in all_checks if c["status"] == "WARN"]

    print("\n" + "=" * 60)
    print(" Diagnostics Summary")
    print("=" * 60)
    print(f"  Critical Failures: {len(failed)}")
    print(f"  Warnings:          {len(warned)}")
    print(f"  System Check:      {'PASS' if sys_pass and import_failures == 0 else 'FAIL'}")

    if not sys_pass or import_failures > 0 or len(failed) > 0:
        print(f"\n{RED}STATUS: FAILED. Please resolve critical failures before running NestyAI in production.{RESET}")
        return 1

    if len(warned) > 0:
        print(f"\n{YELLOW}STATUS: PASSED (with warnings). Review warnings before running NestyAI in production.{RESET}")
        return 0

    print(f"\n{GREEN}STATUS: PASSED. Everything looks ready!{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
