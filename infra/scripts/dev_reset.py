from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset local OpenFinance development artifacts."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply destructive reset. Without this flag the script only prints targets.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    targets = [
        repo_root / ".openfinance" / "data",
        repo_root / ".openfinance" / "registry",
        repo_root / ".openfinance" / "artifacts",
        repo_root / ".runlogs",
    ]

    print("OpenFinance dev reset targets:")
    for item in targets:
        print(f" - {item}")

    if not args.yes:
        print("Dry run only. Re-run with --yes to delete these paths.")
        return 0

    for item in targets:
        _remove_path(item)

    # Recreate base directories expected by services.
    (repo_root / ".openfinance").mkdir(parents=True, exist_ok=True)
    print("Reset complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
