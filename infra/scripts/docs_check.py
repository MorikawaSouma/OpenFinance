from __future__ import annotations

import re
import sys
from pathlib import Path


def _load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _assert_contains(haystack: str, needle: str, label: str, errors: list[str]) -> None:
    if needle not in haystack:
        errors.append(f"Missing {label}: {needle}")


def _assert_regex(haystack: str, pattern: str, label: str, errors: list[str]) -> None:
    if re.search(pattern, haystack, flags=re.MULTILINE) is None:
        errors.append(f"Missing {label}: /{pattern}/")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    user_guide = repo_root / "docs" / "USER_GUIDE.md"
    runbook = repo_root / "docs" / "DEV_RUNBOOK.md"
    readme = repo_root / "README.md"

    errors: list[str] = []

    for path in (user_guide, runbook, readme):
        if not path.exists():
            errors.append(f"File not found: {path}")

    if errors:
        for item in errors:
            print(f"[docs-check] {item}")
        return 1

    user_text = _load_text(user_guide)
    runbook_text = _load_text(runbook)
    docs_text = f"{user_text}\n{runbook_text}"
    readme_text = _load_text(readme)

    required_user_sections = [
        "## 0. 系统概览",
        "## 1. 环境准备",
        "## 2. 一键启动",
        "## 3. 按模块操作",
        "## 4. 结果与产物在哪里查看",
        "## 5. FAQ 与排障",
        "## 《从零跑通一次完整研究→回测→报告→重跑→对比→纸交易》",
    ]
    for section in required_user_sections:
        _assert_contains(user_text, section, "USER_GUIDE section", errors)

    required_runbook_sections = [
        "## 1. 本地开发环境与依赖",
        "## 2. 启动、停止、重置",
        "## 3. 测试矩阵（Backend / Frontend / Smoke）",
        "## 4. 数据与产物目录",
        "## 5. 调试与排障手册",
        "## 6. docs-check（文档自检）",
    ]
    for section in required_runbook_sections:
        _assert_contains(runbook_text, section, "DEV_RUNBOOK section", errors)

    # README should stay concise and include doc links.
    _assert_contains(readme_text, "## Quick Start", "README quick start", errors)
    _assert_contains(readme_text, "docs/USER_GUIDE.md", "README docs link", errors)
    _assert_contains(readme_text, "docs/DEV_RUNBOOK.md", "README docs link", errors)

    makefile_text = _load_text(repo_root / "Makefile")
    _assert_regex(makefile_text, r"^dev:\s*$", "Makefile target", errors)
    _assert_regex(makefile_text, r"^backend-test:\s*$", "Makefile target", errors)
    _assert_regex(makefile_text, r"^docs-check:\s*$", "Makefile target", errors)
    _assert_regex(makefile_text, r"^dev-reset:\s*$", "Makefile target", errors)

    # Validate command-related scripts exist.
    script_checks = [
        ("start_dev.bat", ["start_dev.bat"]),
        ("infra/scripts/start_dev.ps1", ["infra/scripts/start_dev.ps1"]),
        ("infra/scripts/stop_dev.ps1", ["infra/scripts/stop_dev.ps1"]),
        ("infra/scripts/dev_runner.py", ["infra/scripts/dev_runner.py"]),
        ("infra/scripts/acceptance_backend.ps1", ["infra/scripts/acceptance_backend.ps1"]),
        ("infra/scripts/dev_reset.py", ["infra/scripts/dev_reset.py"]),
        (
            "backend/apps/e2e_smoke_pr19.py",
            ["backend/apps/e2e_smoke_pr19.py", "python apps/e2e_smoke_pr19.py"],
        ),
        (
            "backend/apps/e2e_smoke_pr20.py",
            ["backend/apps/e2e_smoke_pr20.py", "python apps/e2e_smoke_pr20.py"],
        ),
        (
            "backend/apps/e2e_smoke_pr21.py",
            ["backend/apps/e2e_smoke_pr21.py", "python apps/e2e_smoke_pr21.py"],
        ),
        ("frontend/playwright.config.ts", ["frontend/playwright.config.ts"]),
    ]
    for script_path, doc_tokens in script_checks:
        full_path = repo_root / script_path
        if not full_path.exists():
            errors.append(f"Script/file missing: {script_path}")
        else:
            if not any(token in docs_text for token in doc_tokens):
                errors.append(f"Missing docs script reference: {script_path}")

    # Validate key commands are documented.
    for command_snippet in [
        "make dev",
        "make backend-test",
        "make docs-check",
        "make dev-reset",
        "python infra/scripts/dev_runner.py",
        "python infra/scripts/dev_reset.py --yes",
        "python -m pytest -q",
        "python apps/e2e_smoke_pr19.py",
        "python apps/e2e_smoke_pr20.py",
        "python apps/e2e_smoke_pr21.py",
        "npm run test:e2e",
    ]:
        _assert_contains(docs_text, command_snippet, "docs command reference", errors)

    # Validate documented API endpoints exist in source.
    api_source = []
    for path in sorted((repo_root / "backend" / "openfinance" / "api").glob("*.py")):
        api_source.append(_load_text(path))
    source_text = "\n".join(api_source)
    key_endpoints = [
        "/healthz",
        "/events/stream",
        "/chat/message",
        "/chat/sessions",
        "/plan",
        "/run",
        "/pipeline/run",
        "/knowledge/evidence/packs",
        "/workbench/factors/run",
        "/workbench/factor/multi_market_compare",
        "/workbench/reports/robustness/run",
        "/workbench/reports/multi-market/compare",
        "/workbench/runs",
        "/workbench/audit",
        "/trading/status",
        "/trading/approvals",
        "/trading/paper/orders",
        "/trading/live/orders",
        "/trading/risk/events",
        "/trace/{trace_id}/restore",
    ]
    for endpoint in key_endpoints:
        _assert_contains(docs_text, endpoint, "docs endpoint reference", errors)
        if f'"{endpoint}"' in source_text:
            continue
        normalized = endpoint.strip("/")
        parts = normalized.split("/")
        if len(parts) >= 2:
            prefix = f'prefix="/{parts[0]}"'
            suffix = "/" + "/".join(parts[1:])
            if (prefix not in source_text) or (f'"{suffix}"' not in source_text):
                errors.append(f"Missing source endpoint: {endpoint}")
            continue
        if endpoint not in source_text:
            errors.append(f"Missing source endpoint: {endpoint}")

    if errors:
        print("[docs-check] FAILED")
        for item in errors:
            print(f" - {item}")
        return 1

    print("[docs-check] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
