from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

import mistune


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DIST_DIR = DOCS_DIR / "dist"
FIGURES_DIR = DOCS_DIR / "figures"
ASSETS_DIR = DOCS_DIR / "assets"


def _slugify(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    if not base:
        base = "section"
    slug = base
    idx = 2
    while slug in used:
        slug = f"{base}-{idx}"
        idx += 1
    used.add(slug)
    return slug


def _inject_heading_ids(markdown_text: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = markdown_text.splitlines()
    used: set[str] = set()
    toc: list[tuple[int, str, str]] = []
    out: list[str] = []
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    for line in lines:
        m = heading_pattern.match(line)
        if not m:
            out.append(line)
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        slug = _slugify(title, used)
        out.append(f'{m.group(1)} {title} <a id="{slug}"></a>')
        toc.append((level, title, slug))
    return "\n".join(out), toc


def _build_toc(toc: list[tuple[int, str, str]]) -> str:
    rows = [item for item in toc if item[0] in {2, 3}]
    if not rows:
        return ""
    parts = ['<nav class="toc"><h2>目录</h2><ul>']
    for level, title, slug in rows:
        cls = "toc-l2" if level == 2 else "toc-l3"
        parts.append(f'<li class="{cls}"><a href="#{html.escape(slug)}">{html.escape(title)}</a></li>')
    parts.append("</ul></nav>")
    return "\n".join(parts)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _build_html(manual_md: Path) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    markdown_raw = manual_md.read_text(encoding="utf-8")
    markdown_with_ids, toc = _inject_heading_ids(markdown_raw)
    renderer = mistune.create_markdown(escape=False, plugins=["table", "strikethrough", "url"])
    body_html = renderer(markdown_with_ids)
    toc_html = _build_toc(toc)

    template = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenFinance 项目说明书（中文）</title>
  <link rel="stylesheet" href="./assets/figure.css">
  <style>
    @font-face {{
      font-family: "Noto Sans SC";
      font-style: normal;
      font-weight: 400;
      src: url("./assets/fonts/NotoSansSC-CN-400.woff2") format("woff2");
      font-display: swap;
    }}
    @font-face {{
      font-family: "Noto Sans SC";
      font-style: normal;
      font-weight: 700;
      src: url("./assets/fonts/NotoSansSC-CN-700.woff2") format("woff2");
      font-display: swap;
    }}
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #5b6475;
      --line: #dde3ee;
      --primary: #2d6cdf;
      --accent: #7b61ff;
      --ok: #22a06b;
      --warn: #f59e0b;
      --shadow: 0 10px 32px rgba(31, 41, 55, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background: radial-gradient(circle at top left, #eef4ff 0%, var(--bg) 45%, #f8fafd 100%);
      font-family: Inter, "Noto Sans SC", system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.75;
    }}
    .layout {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 20px;
    }}
    .toc {{
      position: sticky;
      top: 20px;
      align-self: start;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 14px 16px;
      max-height: calc(100vh - 40px);
      overflow: auto;
    }}
    .toc h2 {{ margin: 4px 0 10px 0; font-size: 16px; }}
    .toc ul {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }}
    .toc-l2 a {{ font-size: 13px; color: var(--text); text-decoration: none; }}
    .toc-l3 {{ padding-left: 12px; }}
    .toc-l3 a {{ font-size: 12px; color: var(--muted); text-decoration: none; }}
    .toc a:hover {{ color: var(--primary); text-decoration: underline; }}
    .article {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 30px 38px;
    }}
    h1, h2, h3, h4 {{
      line-height: 1.35;
      margin-top: 1.35em;
      margin-bottom: 0.6em;
      letter-spacing: 0.01em;
    }}
    h1 {{ font-size: 34px; margin-top: 0.2em; }}
    h2 {{
      font-size: 24px;
      border-left: 5px solid var(--primary);
      padding-left: 10px;
    }}
    h3 {{ font-size: 19px; color: #23395d; }}
    h4 {{ font-size: 16px; color: #3b4e70; }}
    p, li, td, th {{ font-size: 15px; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      background: #f0f4fa;
      color: #1e3a8a;
      border: 1px solid #dfe7f5;
      border-radius: 5px;
      padding: 1px 5px;
    }}
    pre {{
      background: #0f172a;
      color: #e5e7eb;
      border-radius: 10px;
      padding: 14px;
      overflow-x: auto;
    }}
    pre code {{
      background: transparent;
      color: inherit;
      border: 0;
      padding: 0;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin: 14px 0;
      border-radius: 10px;
      overflow: hidden;
    }}
    thead tr {{ background: #edf3ff; }}
    th, td {{
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      padding: 10px;
    }}
    img {{ max-width: 100%; }}
    blockquote {{
      margin: 12px 0;
      border-left: 4px solid var(--accent);
      background: #f7f4ff;
      padding: 8px 12px;
      color: #403063;
    }}
    hr {{
      border: 0;
      border-top: 1px dashed #cad6ec;
      margin: 20px 0;
    }}
    .typography-check {{
      margin-top: 24px;
      padding: 14px;
      border-radius: 12px;
      border: 1px solid #d7e3f9;
      background: #f7fbff;
    }}
    .typography-check .sample {{
      margin-top: 8px;
      font-size: 16px;
      font-weight: 500;
      letter-spacing: 0.01em;
    }}
    .footer {{
      margin-top: 24px;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 1080px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
      .toc {{
        position: relative;
        top: 0;
        max-height: unset;
      }}
      .article {{
        padding: 22px;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    {toc_html}
    <article class="article">
      {body_html}
      <section class="typography-check">
        <h3>Typography Check</h3>
        <p>Expected font stack: Inter, "Noto Sans SC", system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif.</p>
        <div class="sample">中文验证样例：量化研究平台 / 审计追踪 / 风控门禁。 English Sample: OpenFinance Research Workbench.</div>
        <p>如果你看到方块字，请确认 <code>docs/dist/assets/fonts/NotoSansSC-CN-400.woff2</code> 和 <code>NotoSansSC-CN-700.woff2</code> 存在。</p>
      </section>
      <p class="footer">Generated by scripts/build_docs.py</p>
    </article>
  </div>
</body>
</html>
"""
    out_path = DIST_DIR / "PROJECT_MANUAL_CN.html"
    out_path.write_text(template, encoding="utf-8")
    return out_path


def _build_index() -> Path:
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenFinance Docs</title>
</head>
<body>
  <h1>OpenFinance Documentation</h1>
  <ul>
    <li><a href="./PROJECT_MANUAL_CN.html">PROJECT_MANUAL_CN.html</a></li>
    <li><a href="./figure_gallery.html">figure_gallery.html</a></li>
  </ul>
</body>
</html>
"""
    out = DIST_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def _build_gallery() -> Path:
    figures = [
        ("Figure 1", "fig01_system_overview.svg", "fig-lg"),
        ("Figure 2", "fig02_object_lifecycle.svg", "fig-md"),
        ("Figure 3", "fig03_multi_agent_topology.svg", "fig-lg"),
        ("Figure 4", "fig04_orchestration_sequence.svg", "fig-lg"),
        ("Figure 5", "fig05_reasoning_trace_schema.svg", "fig-sm"),
        ("Figure 6", "fig06_evidence_flow.svg", "fig-md"),
        ("Figure 7", "fig07_factor_pipeline.svg", "fig-sm"),
        ("Figure 8", "fig08_strategy_tradeoff.svg", "fig-md"),
        ("Figure 9", "fig09_risk_approval_state_machine.svg", "fig-sm"),
        ("Figure 10", "fig10_multi_market_migration.svg", "fig-md"),
    ]
    blocks: list[str] = []
    for title, src, cls in figures:
        blocks.append(
            f"""
    <figure class="fig {cls}">
      <img src="./figures/{src}" alt="{title}">
      <figcaption><b>{title}.</b> Gallery preview for layout regression test.</figcaption>
    </figure>
"""
        )

    html_page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenFinance Figure Gallery</title>
  <link rel="stylesheet" href="./assets/figure.css">
  <style>
    body {{
      margin: 0;
      font-family: Inter, "Noto Sans SC", system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: #f5f7fb;
      color: #1f2937;
    }}
    .wrap {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 24px 20px 40px 20px;
    }}
    h1 {{
      margin: 0 0 8px 0;
      font-size: 30px;
    }}
    p {{
      margin: 0 0 16px 0;
      color: #5b6475;
    }}
    .hint {{
      background: #eef4ff;
      border: 1px solid #d5e3ff;
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 12px;
      color: #2a497f;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <h1>Figure Gallery</h1>
    <p>Regression page for spacing, scaling, and non-cropping checks.</p>
    <div class="hint">Check both wide and narrow viewports. All figures should keep margins and readable captions.</div>
    {''.join(blocks)}
  </main>
</body>
</html>
"""
    out = DIST_DIR / "figure_gallery.html"
    out.write_text(html_page, encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build docs HTML to docs/dist with UTF-8 and local CJK fonts.")
    parser.add_argument("--manual", default=str(DOCS_DIR / "PROJECT_MANUAL_CN.md"), help="Source markdown file.")
    args = parser.parse_args()

    manual_md = Path(args.manual)
    if not manual_md.exists():
        raise FileNotFoundError(f"Manual markdown not found: {manual_md}")

    _copy_tree(FIGURES_DIR, DIST_DIR / "figures")
    _copy_tree(ASSETS_DIR, DIST_DIR / "assets")
    manual_html = _build_html(manual_md)
    index_html = _build_index()
    gallery_html = _build_gallery()

    print("[build_docs] OK")
    print(f" - manual: {manual_html}")
    print(f" - index:  {index_html}")
    print(f" - gallery:{gallery_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
