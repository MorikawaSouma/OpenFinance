from __future__ import annotations

import argparse
from pathlib import Path


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".mmd",
    ".svg",
}


def _should_check(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    # Some docs files may be extension-less.
    return path.name.lower().startswith(("readme", "license"))


def _check_utf8(path: Path) -> str | None:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 BOM detected (prefer UTF-8 without BOM)"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"Invalid UTF-8: {exc}"
    return None


def scan_roots(roots: list[Path]) -> list[tuple[Path, str]]:
    issues: list[tuple[Path, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not _should_check(path):
                continue
            err = _check_utf8(path)
            if err:
                issues.append((path, err))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check UTF-8 encoding for docs/scripts text files.")
    parser.add_argument(
        "--roots",
        nargs="*",
        default=["docs", "scripts"],
        help="Directories to scan (default: docs scripts)",
    )
    args = parser.parse_args()

    roots = [Path(item).resolve() for item in args.roots]
    issues = scan_roots(roots)
    if issues:
        print("[check_utf8] FAILED")
        for path, err in issues:
            print(f" - {path}: {err}")
        return 1

    print("[check_utf8] OK")
    for root in roots:
        print(f" - scanned: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
