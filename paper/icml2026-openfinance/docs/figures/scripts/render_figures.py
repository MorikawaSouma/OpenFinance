#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_dot() -> str:
    env_dot = os.environ.get("GRAPHVIZ_DOT")
    if env_dot and Path(env_dot).exists():
        return env_dot

    which_dot = shutil.which("dot")
    if which_dot:
        return which_dot

    candidates = [
        Path(r"C:\Program Files\Graphviz\bin\dot.exe"),
        Path(r"C:\Program Files (x86)\Graphviz\bin\dot.exe"),
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand)

    raise FileNotFoundError(
        "dot executable not found. Install Graphviz or set GRAPHVIZ_DOT."
    )


def render(dot_bin: str, src: Path, dst: Path, fmt: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [dot_bin, "-T" + fmt, str(src), "-o", str(dst)]
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src_dir = root / "src"
    out_dir = root

    figures = [
        ("fig1a_system_layers.dot", "fig1a_system_layers"),
        ("fig3a_multi_agent_topology.dot", "fig3a_multi_agent_topology"),
    ]

    dot_bin = resolve_dot()
    print(f"[render] using dot: {dot_bin}")

    for src_name, stem in figures:
        src = src_dir / src_name
        if not src.exists():
            raise FileNotFoundError(f"missing source: {src}")

        svg_out = out_dir / f"{stem}.svg"
        pdf_out = out_dir / f"{stem}.pdf"
        print(f"[render] {src_name} -> {svg_out.name}, {pdf_out.name}")
        render(dot_bin, src, svg_out, "svg")
        render(dot_bin, src, pdf_out, "pdf")

    print("[render] done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[render] failed: {exc}", file=sys.stderr)
        raise
