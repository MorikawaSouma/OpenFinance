from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle


ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "docs" / "figures"


@dataclass(frozen=True)
class Palette:
    blue: str = "#2D6CDF"
    blue_soft: str = "#EAF1FF"
    purple: str = "#7B61FF"
    purple_soft: str = "#F1EDFF"
    green: str = "#2EAD6B"
    green_soft: str = "#E9F8EF"
    orange: str = "#F59E0B"
    orange_soft: str = "#FFF5E6"
    rose: str = "#E44D7A"
    rose_soft: str = "#FFEAF1"
    teal: str = "#1E9AA6"
    teal_soft: str = "#E6F8FA"
    gray: str = "#5B6475"
    line: str = "#B7C3D8"
    shadow: str = "#DCE5F2"
    bg: str = "#FFFFFF"


P = Palette()


def _new_canvas(title: str, subtitle: str = ""):
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor(P.bg)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.text(50, 96, title, ha="center", va="center", fontsize=20, fontweight="bold", color="#1F2937")
    if subtitle:
        ax.text(50, 92.8, subtitle, ha="center", va="center", fontsize=11, color=P.gray)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.94, bottom=0.06)
    return fig, ax


def _box(ax, x, y, w, h, text, fc, ec, lw=1.6, fs=10.5, weight="normal", round_size=0.08):
    shadow = FancyBboxPatch(
        (x + 0.6, y - 0.6),
        w,
        h,
        boxstyle=f"round,pad=0.02,rounding_size={round_size}",
        linewidth=0,
        facecolor=P.shadow,
        alpha=0.35,
        zorder=1,
    )
    ax.add_patch(shadow)
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.02,rounding_size={round_size}",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color="#1F2937", fontweight=weight, zorder=3)


def _arrow(ax, start, end, color=P.line, lw=1.5, rad=0.0, alpha=0.9, style="-|>"):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle=style,
        mutation_scale=12,
        linewidth=lw,
        color=color,
        alpha=alpha,
        connectionstyle=f"arc3,rad={rad}",
        zorder=2.5,
    )
    ax.add_patch(arr)


def _circle(ax, x, y, r, text, fc, ec, fs=10, weight="normal"):
    c = Circle((x, y), r, facecolor=fc, edgecolor=ec, linewidth=1.6, zorder=2)
    ax.add_patch(c)
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color="#1F2937", fontweight=weight, zorder=3)


def _save(fig, path: Path):
    fig.savefig(path, format="svg", bbox_inches=None, pad_inches=0.35)
    plt.close(fig)


def fig01_system_overview(path: Path):
    fig, ax = _new_canvas("Figure 1. System Overview", "Layered Architecture of OpenFinance")
    layers = [
        ("Frontend Workspace", "Chat / Pipeline / Reports / Risk", P.blue_soft, P.blue, 79),
        ("Backend API", "FastAPI routes + orchestration endpoints", P.purple_soft, P.purple, 64),
        ("Research & Quant Layer", "Agents / Factors / Strategy / Backtest", P.green_soft, P.green, 49),
        ("Data & Storage Layer", "JSONL + SQLite + artifact files", P.orange_soft, P.orange, 34),
        ("Audit & Event Layer", "trace_id audit log + SSE event bus", P.rose_soft, P.rose, 19),
    ]
    for title, detail, fc, ec, y in layers:
        _box(ax, 10, y, 80, 11, f"{title}\n{detail}", fc, ec, fs=12)

    for y1, y2 in [(79, 64), (64, 49), (49, 34), (34, 19)]:
        _arrow(ax, (50, y1), (50, y2 + 11), color=P.line, lw=2.0)

    _arrow(ax, (25, 74), (25, 26), color="#88A7D9", lw=1.3, rad=0.05, alpha=0.55, style="->")
    _arrow(ax, (75, 74), (75, 26), color="#88A7D9", lw=1.3, rad=-0.05, alpha=0.55, style="->")
    ax.text(50, 9, "End-to-end traceable pipeline: Evidence -> Factor -> Strategy -> Run -> Report -> Gate", ha="center", fontsize=10.5, color=P.gray)
    _save(fig, path)


def fig02_object_lifecycle(path: Path):
    fig, ax = _new_canvas("Figure 2. Object Lifecycle", "From user question to auditable execution artifacts")
    nodes = [
        ("Question", 8),
        ("ResearchPlan", 18),
        ("EvidencePack", 30),
        ("FactorSpec", 42),
        ("StrategySpec", 54),
        ("Run", 66),
        ("Report", 78),
        ("Approval / RiskEvent", 90),
    ]
    for name, x in nodes:
        _box(ax, x - 5.2, 56, 10.4, 11, name, P.blue_soft if name in {"Question", "ResearchPlan", "EvidencePack"} else P.green_soft, P.blue if name in {"Question", "ResearchPlan", "EvidencePack"} else P.green, fs=10.5)
    for (_, x1), (_, x2) in zip(nodes[:-1], nodes[1:]):
        _arrow(ax, (x1 + 5, 61.5), (x2 - 5, 61.5), color=P.line, lw=1.8)

    _box(ax, 9, 28, 24, 12, "Registry Layer\nplans/runs/evidence", P.purple_soft, P.purple, fs=10.5)
    _box(ax, 38, 28, 24, 12, "Artifact Layer\nfactor/report json", P.orange_soft, P.orange, fs=10.5)
    _box(ax, 67, 28, 24, 12, "Audit Layer\naudit.jsonl + trace_id", P.rose_soft, P.rose, fs=10.5)

    _arrow(ax, (18, 56), (20.5, 40), color=P.purple, lw=1.4, alpha=0.8, style="->")
    _arrow(ax, (54, 56), (50, 40), color=P.orange, lw=1.4, alpha=0.8, style="->")
    _arrow(ax, (78, 56), (79, 40), color=P.rose, lw=1.4, alpha=0.8, style="->")
    _arrow(ax, (90, 56), (79, 40), color=P.rose, lw=1.2, alpha=0.7, style="->")
    ax.text(50, 13, "Every object is linked by IDs: plan_id, evidence_pack_id, factor_version, strategy_version, run_id, trace_id", ha="center", fontsize=10.3, color=P.gray)
    _save(fig, path)


def fig03_multi_agent_topology(path: Path):
    fig, ax = _new_canvas("Figure 3. Multi-Agent Topology", "Grouped flow: EvidencePack -> Expert Pool -> Aggregator")
    _box(ax, 6, 45, 18, 14, "EvidencePack", P.teal_soft, P.teal, fs=12, weight="bold")

    _box(ax, 31, 27, 36, 52, "Expert Pool", "#F8F5FF", P.purple, fs=12, weight="bold")
    agents = [
        ("Buffett", 70),
        ("Soros", 63),
        ("Simons", 56),
        ("Dalio", 49),
        ("Kahneman", 42),
        ("Factor", 35),
        ("RiskManager", 28),
    ]
    for name, y in agents:
        _circle(ax, 49, y, 3.3, name, P.purple_soft, P.purple, fs=8.7)

    _box(ax, 74, 45, 20, 14, "Aggregator", P.orange_soft, P.orange, fs=12, weight="bold")
    _box(ax, 32, 11, 40, 11, "Output Artifacts\nAgentOutput + ReasoningTrace + Citations", P.green_soft, P.green, fs=10.5)
    _box(ax, 6, 12, 20, 10, "Counterfactual\nRetriever", P.rose_soft, P.rose, fs=9.6)

    # Data flow: EvidencePack -> Expert Pool -> Aggregator
    _arrow(ax, (24, 52), (31, 52), color="#6FA8C7", lw=2.0, style="-|>")
    ax.text(26.7, 55.7, "data flow", fontsize=8.8, color="#467490")
    _arrow(ax, (67, 52), (74, 52), color="#6FA8C7", lw=2.0, style="-|>")

    # Internal grouped fan-out (kept inside expert pool only)
    for _, y in agents:
        _arrow(ax, (35, 52), (45.5, y), color="#B3BED8", lw=1.0, alpha=0.7, style="->")
        _arrow(ax, (52.5, y), (63, 52), color="#B3BED8", lw=1.0, alpha=0.7, style="->")

    # Counterfactual path
    _arrow(ax, (26, 17), (43, 42), color=P.rose, lw=1.8, rad=0.16, style="->")
    ax.text(29.5, 25, "counterfactual flow", fontsize=8.8, color=P.rose)

    # Output path
    _arrow(ax, (84, 45), (64, 22), color=P.green, lw=2.0, rad=0.1, style="-|>")
    ax.text(73.8, 30.2, "output flow", fontsize=8.8, color=P.green)

    ax.text(50, 7.2, "Grouped links reduce visual clutter while preserving lens diversity.", ha="center", fontsize=9.5, color=P.gray)
    _save(fig, path)


def fig04_orchestration_sequence(path: Path):
    fig, ax = _new_canvas("Figure 4. Orchestration Sequence", "Swimlane with emitted artifacts and incremental SSE cards")
    lanes = [("User", 8), ("UI", 22), ("Orchestrator", 38), ("RAG", 54), ("Agents", 70), ("Backtest", 86)]
    for name, x in lanes:
        ax.plot([x, x], [15, 88], color="#CBD5E7", linewidth=1.2, zorder=1)
        _box(ax, x - 5.5, 88.5, 11, 6.5, name, P.blue_soft, P.blue, fs=9.5, weight="bold")

    messages = [
        (8, 22, 82, "1) Ask question"),
        (22, 38, 76, "2) POST /chat/message"),
        (38, 54, 70, "3) Retrieve evidence"),
        (54, 38, 64, "4) Return EvidencePack"),
        (38, 70, 58, "5) Dispatch experts"),
        (70, 38, 52, "6) Agent outputs + trace"),
        (38, 86, 46, "7) Run backtest"),
        (86, 38, 40, "8) Return report"),
        (38, 22, 34, "9) Response + cards"),
        (38, 22, 28, "10) SSE incremental cards (no full reload)"),
    ]
    for x1, x2, y, text in messages:
        _arrow(ax, (x1, y), (x2, y), color="#7D8FB0", lw=1.5, alpha=0.95)
        ax.text((x1 + x2) / 2, y + 1.6, text, ha="center", va="bottom", fontsize=9.3, color="#2E3A4F")

    # Artifact emissions
    _box(ax, 28, 20, 20, 6.5, "Emitted: evidence_pack_id", "#F6FBFF", "#7DA6D9", fs=8.6)
    _box(ax, 50, 20, 16, 6.5, "Emitted: plan_id", "#F6FBFF", "#7DA6D9", fs=8.6)
    _box(ax, 68, 20, 16, 6.5, "Emitted: run_id", "#F6FBFF", "#7DA6D9", fs=8.6)
    _box(ax, 44, 12, 16, 6.5, "Emitted: trace_id", "#FFF8F3", "#E4A34B", fs=8.6)
    _arrow(ax, (38, 37), (38, 26.5), color="#9AB1D6", lw=1.1, style="->")
    _arrow(ax, (38, 31), (58, 26.5), color="#9AB1D6", lw=1.1, style="->")
    _arrow(ax, (86, 39), (76, 26.5), color="#9AB1D6", lw=1.1, style="->")
    _arrow(ax, (38, 52), (52, 18.5), color="#E4A34B", lw=1.1, style="->")

    _save(fig, path)


def fig05_reasoning_trace_schema(path: Path):
    fig, ax = _new_canvas("Figure 5. Reasoning Trace Schema", "Structured, auditable reasoning trace without raw CoT")
    _box(ax, 33, 77, 34, 9, "ReasoningTrace", P.blue_soft, P.blue, fs=13, weight="bold")
    steps = [
        ("Hypothesis", 10, P.purple_soft, P.purple),
        ("Evidence Search", 27, P.teal_soft, P.teal),
        ("Counterevidence", 44, P.rose_soft, P.rose),
        ("Revision", 61, P.orange_soft, P.orange),
        ("Decision", 78, P.green_soft, P.green),
    ]
    for label, x, fc, ec in steps:
        _box(ax, x, 58, 12, 8, label, fc, ec, fs=9.4)
        _arrow(ax, (50, 77), (x + 6, 66), color="#9AAAD0", lw=1.2)
        _box(ax, x, 34, 12, 18, "question\nquery\nevidence_refs\noutput_summary\nconfidence_delta", "#F8FAFF", "#C8D3EA", fs=8.4)
        _arrow(ax, (x + 6, 58), (x + 6, 52.2), color="#AAB7D1", lw=1.1)

    _box(ax, 20, 15, 60, 10, "Interpretability principle: persist structure + citations, avoid exposing internal chain-of-thought text.", "#F7F8FC", "#D0D7E6", fs=10)
    _save(fig, path)


def fig06_evidence_flow(path: Path):
    fig, ax = _new_canvas("Figure 6. Evidence Flow and Credibility Breakdown", "Hybrid retrieval pipeline with interpretable scoring components")
    _box(ax, 6, 61, 17, 10, "Query", P.blue_soft, P.blue, fs=11.5, weight="bold")
    _box(ax, 27, 68, 18, 8, "LocalCorpusRetriever", P.purple_soft, P.purple, fs=9.5)
    _box(ax, 27, 58, 18, 8, "MockNewsProvider", P.teal_soft, P.teal, fs=9.5)
    _box(ax, 27, 48, 18, 8, "MockMacroProvider", P.orange_soft, P.orange, fs=9.5)
    _box(ax, 49, 58, 17, 12, "HybridRetriever", P.green_soft, P.green, fs=10.5)
    _box(ax, 70, 58, 21, 12, "EvidenceCredibilityScorer", P.rose_soft, P.rose, fs=10.2)
    _box(ax, 70, 38, 21, 12, "EvidencePack", "#EEF6FF", "#6A8FD8", fs=10.5)

    for y in [72, 62, 52]:
        _arrow(ax, (23, 66), (27, y), color="#8EA6D6", lw=1.3)
    for y in [72, 62, 52]:
        _arrow(ax, (45, y), (49, 64), color="#8EA6D6", lw=1.2, alpha=0.8)
    _arrow(ax, (66, 64), (70, 64), color="#8EA6D6", lw=1.5)
    _arrow(ax, (80.5, 58), (80.5, 50), color="#8EA6D6", lw=1.5)

    ax.text(16, 29, "Credibility Breakdown", fontsize=12, fontweight="bold", color="#1F2937")
    bar_x, bar_y, bar_w, bar_h = 13, 20, 52, 6
    segments = [
        ("source_type", 0.35, P.blue),
        ("recency", 0.25, P.purple),
        ("citation_density", 0.20, P.green),
        ("conflict_score", 0.20, P.orange),
    ]
    offset = bar_x
    for name, frac, color in segments:
        w = bar_w * frac
        ax.add_patch(Rectangle((offset, bar_y), w, bar_h, facecolor=color, edgecolor="white", linewidth=1.0))
        ax.text(offset + w / 2, bar_y + bar_h / 2, f"{name}\n{int(frac*100)}%", ha="center", va="center", fontsize=8.4, color="white")
        offset += w

    _box(ax, 68, 18, 24, 13, "Semantic Assist Tags\n- authoritative_source\n- promotional_language\n- missing_methods\n- methods_disclosed", "#FFF7FA", "#E4A7BE", fs=8.8)
    _save(fig, path)


def fig07_factor_pipeline(path: Path):
    fig, ax = _new_canvas("Figure 7. Factor Pipeline and QC", "From FactorSpec to HealthReport and reusable artifacts")
    stages = [
        ("FactorSpec / DSL", 8, P.blue_soft, P.blue),
        ("Compute Series", 25, P.purple_soft, P.purple),
        ("QC Engine", 42, P.teal_soft, P.teal),
        ("FactorReport", 59, P.green_soft, P.green),
        ("Registry + Artifacts", 76, P.orange_soft, P.orange),
    ]
    for name, x, fc, ec in stages:
        _box(ax, x, 63, 14, 11, name, fc, ec, fs=9.8)
    for i in range(len(stages) - 1):
        _arrow(ax, (stages[i][1] + 14, 68.5), (stages[i + 1][1], 68.5), color="#9AAED3", lw=1.6)

    _box(ax, 39, 43, 20, 13, "QC Metrics\nIC / RankIC\nDecay\nCoverage\nOOS Split\nSensitivity", "#F5FAFF", "#8BB2E8", fs=9.5)
    _arrow(ax, (49, 63), (49, 56), color="#9AAED3", lw=1.3)

    # mini chart
    ax.text(14, 31, "Illustrative Decay Curves", fontsize=10.5, color="#1F2937", fontweight="bold")
    ax.plot([14, 34, 54, 74], [20, 18, 15, 12], color=P.blue, linewidth=2.2, label="in-sample IC")
    ax.plot([14, 34, 54, 74], [19, 16, 12, 9], color=P.rose, linewidth=2.2, label="out-of-sample IC")
    for x, y in [(14, 20), (34, 18), (54, 15), (74, 12)]:
        _circle(ax, x, y, 0.75, "", P.blue, P.blue)
    for x, y in [(14, 19), (34, 16), (54, 12), (74, 9)]:
        _circle(ax, x, y, 0.75, "", P.rose, P.rose)
    ax.text(76, 12, "lag", fontsize=8.5, color=P.gray)
    ax.text(12, 22.2, "IC", fontsize=8.5, color=P.gray)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    _save(fig, path)


def fig08_strategy_tradeoff(path: Path):
    fig, ax = _new_canvas("Figure 8. Strategy Decision A/B Trade-off", "Candidate comparison with selection rationale")
    _box(ax, 7, 70, 38, 18, "Candidate A: RiskBudgetAllocator\nPros: drawdown control, regime adaptation\nCons: estimation noise, higher complexity\nRisk: covariance instability", P.blue_soft, P.blue, fs=10)
    _box(ax, 55, 70, 38, 18, "Candidate B: EqualWeightAllocator\nPros: simple, robust operations\nCons: weak downside control\nRisk: concentration under vol spikes", P.purple_soft, P.purple, fs=10)

    _box(ax, 7, 45, 38, 18, "Cost Profile A\nturnover: medium-high\nimplementation: complex\nfit for strict drawdown target", P.green_soft, P.green, fs=9.6)
    _box(ax, 55, 45, 38, 18, "Cost Profile B\nturnover: low-medium\nimplementation: simple\nfit for stable regime", P.orange_soft, P.orange, fs=9.6)

    _box(ax, 20, 18, 60, 18, "Selected: Candidate A (example)\nRationale: market microstructure + drawdown constraints require dynamic risk contribution control.\nWhy not B: static weighting cannot absorb volatility concentration under current constraints.", "#EEF3FF", "#5A80D1", fs=10.2, weight="bold")
    _arrow(ax, (26, 45), (45, 36), color=P.blue, lw=1.6, rad=0.12)
    _arrow(ax, (74, 45), (55, 36), color=P.purple, lw=1.6, rad=-0.12)
    _save(fig, path)


def fig09_risk_approval(path: Path):
    fig, ax = _new_canvas("Figure 9. Risk and Approval State Machine", "Approval lifecycle and runtime kill-switch escalation")
    states = [
        ("Requested", 12, 70),
        ("Pending", 30, 70),
        ("Approved", 48, 70),
        ("Enabled", 66, 70),
        ("Revoked", 84, 70),
    ]
    for name, x, y in states:
        _box(ax, x - 6.5, y - 5, 13, 10, name, P.blue_soft, P.blue, fs=10.2)
    for (n1, x1, y1), (_, x2, y2) in zip(states[:-1], states[1:]):
        _arrow(ax, (x1 + 6.5, y1), (x2 - 6.5, y2), color="#90A7D9", lw=1.6)

    _arrow(ax, (66, 65), (84, 65), color=P.rose, lw=1.2, rad=0.25, style="->", alpha=0.8)
    ax.text(74, 60.8, "revoke / expire", fontsize=8.6, color=P.gray)

    _box(ax, 12, 20, 32, 28, "Runtime RiskMonitor\nstatus: normal / warn / blocked\nmetrics: drawdown, volatility", P.rose_soft, P.rose, fs=10.1)
    _box(ax, 52, 20, 36, 28, "TradingService + RiskGate\nif blocked -> kill_switch = ON\nreject new live orders", P.orange_soft, P.orange, fs=10.1)
    _arrow(ax, (44, 34), (52, 34), color="#B06E87", lw=1.8)
    _arrow(ax, (66, 65), (70, 48), color=P.orange, lw=1.6, rad=-0.1)
    _save(fig, path)


def fig10_multi_market(path: Path):
    fig, ax = _new_canvas("Figure 10. Multi-Market Migration Warning", "Configuration-time preflight warning and adjustment path")
    _box(ax, 7, 63, 20, 12, "Input Strategy/Factor", P.blue_soft, P.blue, fs=10.4)
    _box(ax, 31, 63, 20, 12, "Load MarketRules", P.purple_soft, P.purple, fs=10.4)
    _box(ax, 55, 63, 20, 12, "Preflight Checker", P.teal_soft, P.teal, fs=10.4)
    _arrow(ax, (27, 69), (31, 69), color="#95AADA", lw=1.5)
    _arrow(ax, (51, 69), (55, 69), color="#95AADA", lw=1.5)

    diamond = Polygon([[79, 75], [88, 69], [79, 63], [70, 69]], closed=True, facecolor="#FFF3E8", edgecolor="#F59E0B", linewidth=1.6, zorder=2)
    ax.add_patch(diamond)
    ax.text(79, 69, "Warn or\nBlock?", ha="center", va="center", fontsize=9.5, color="#1F2937", zorder=3)
    _arrow(ax, (75, 69), (70, 69), color="#95AADA", lw=1.5)

    _box(ax, 57, 36, 18, 11, "Warn Path\nshow guidance", P.orange_soft, P.orange, fs=9.3)
    _box(ax, 79, 36, 18, 11, "Block Path\nforce confirm/adjust", P.rose_soft, P.rose, fs=9.3)
    _arrow(ax, (76.2, 64), (66, 47), color=P.orange, lw=1.4, style="->")
    _arrow(ax, (81.8, 64), (88, 47), color=P.rose, lw=1.4, style="->")

    _box(ax, 24, 14, 52, 13, "Auto-adjust examples:\nrebalance intraday -> daily, enforce lot-size rounding, align trading session windows", P.green_soft, P.green, fs=9.5)
    _arrow(ax, (66, 36), (50, 27), color=P.green, lw=1.5, rad=0.06)
    _arrow(ax, (88, 36), (56, 27), color=P.green, lw=1.5, rad=-0.08)
    _save(fig, path)


def main() -> int:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "fig01_system_overview.svg": fig01_system_overview,
        "fig02_object_lifecycle.svg": fig02_object_lifecycle,
        "fig03_multi_agent_topology.svg": fig03_multi_agent_topology,
        "fig04_orchestration_sequence.svg": fig04_orchestration_sequence,
        "fig05_reasoning_trace_schema.svg": fig05_reasoning_trace_schema,
        "fig06_evidence_flow.svg": fig06_evidence_flow,
        "fig07_factor_pipeline.svg": fig07_factor_pipeline,
        "fig08_strategy_tradeoff.svg": fig08_strategy_tradeoff,
        "fig09_risk_approval_state_machine.svg": fig09_risk_approval,
        "fig10_multi_market_migration.svg": fig10_multi_market,
    }
    for name, fn in outputs.items():
        out = FIG_DIR / name
        fn(out)
        print(f"[render_figures] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
