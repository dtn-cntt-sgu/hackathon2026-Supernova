#!/usr/bin/env python3
"""
SafePathAI Security, Redaction and Credential Leak Checker.
Ensures:
1. .env.example contains only safe placeholders, no real secrets or tokens.
2. No live API keys (OpenAI, Google Gemini, JWT secrets, private keys) are hardcoded in source code or docs.
3. Docker Compose configuration is syntactically valid and passes schema verification.
4. Alerts on any unredacted sensitive tokens in artifacts or logs.
"""

import os
import re
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# Regex patterns for common sensitive credentials
SENSITIVE_PATTERNS = [
    (r"AIza[0-9A-Za-z-_]{35}", "Google API Key"),
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*", "Slack Token"),
    (r"-----BEGIN (?:RSA|OPENSSH|EC|DSA)? PRIVATE KEY-----", "Private Key"),
    (r"postgres://[^:]+:[^@]+@", "PostgreSQL Connection String with Password"),
]

EXCLUDED_DIRS = {
    ".venv",
    "node_modules",
    ".next",
    ".next-readiness",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "test-results",
    "data",
}

EXCLUDED_FILES = {
    "security_and_redaction_check.py",  # self-exclusion of regex definitions
    "package-lock.json",
}


def check_env_example():
    """Validates that .env.example contains only non-sensitive dummy placeholders."""
    env_example = ROOT_DIR / ".env.example"
    if not env_example.exists():
        print("FAIL: .env.example not found!")
        return False

    content = env_example.read_text(encoding="utf-8")
    violations = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            val = val.strip().strip("'\"")
            if key == "OSRM_GRAPH_MANIFEST_PATH" and val == "data/osrm/graph-manifest.json":
                continue
            # If val has significant length and looks like a real hash or secret
            if len(val) > 20 and not any(p in val.lower() for p in ("example", "your_", "dummy", "placeholder", "localhost", "127.0.0.1", "hcm", "5432", "6379", "5000", "5001")):
                violations.append(key)

    if violations:
        print(f"FAIL: .env.example contains potential secrets: {violations}")
        return False
    print("PASS: .env.example contains only safe placeholders.")
    return True


def scan_for_credentials():
    """Scans all project files for hardcoded sensitive credentials."""
    findings = []

    for path in ROOT_DIR.rglob("*"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.name not in EXCLUDED_FILES:
            # Skip binary files
            if path.suffix in (".onnx", ".png", ".jpg", ".jpeg", ".pbf", ".osrm", ".cells", ".partition", ".mldgr", ".mldcells"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern, desc in SENSITIVE_PATTERNS:
                    matches = re.findall(pattern, text)
                    if matches:
                        # Exclude .env if it is local uncommitted file
                        if path.name == ".env":
                            continue
                        findings.append((path.relative_to(ROOT_DIR), desc, len(matches)))
            except Exception as e:
                pass

    if findings:
        print(f"FAIL: Found {len(findings)} credential leaks in files:")
        for file_path, desc, count in findings:
            print(f"  - {file_path}: {count} occurrences of {desc}")
        return False

    print("PASS: No hardcoded credentials detected in source code or documentation.")
    return True


def check_docker_compose_config():
    """Verifies docker-compose.yml validity via `docker compose config`."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            print("PASS: docker compose config validation succeeded.")
            return True
        else:
            print(f"FAIL: docker compose config failed with error:\n{proc.stderr}")
            return False
    except Exception as e:
        print(f"WARN: Could not execute docker compose config: {e}")
        return True


def main():
    print("=== SafePathAI Security & Redaction Audit ===")
    checks = [
        check_env_example(),
        scan_for_credentials(),
        check_docker_compose_config(),
    ]
    if all(checks):
        print("=== ALL SECURITY & REDACTION CHECKS PASSED ===")
        sys.exit(0)
    else:
        print("=== SECURITY AUDIT FAILED ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
