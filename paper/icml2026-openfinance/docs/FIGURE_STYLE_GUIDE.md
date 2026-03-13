# FIGURE_STYLE_GUIDE

## Scope
This guide defines a single SCI-style visual system for OpenFinance paper figures.
All new figures must follow these rules and be rendered from Graphviz DOT into SVG.

## 1) Canvas & Layout
- Output format: SVG (source of truth), generated from DOT.
- Target canvas width: `1600px` (or equivalent `viewBox` ratio from DOT canvas).
- Outer whitespace: at least `60px` on all sides.
- Grid alignment:
  - same layer: horizontal alignment
  - same column: vertical alignment
  - avoid free-floating misalignment

## 2) Typography
- Font family: `Helvetica` (fallback `Arial`, sans-serif).
- Unified sizes:
  - figure title (if used inside figure): `20`
  - group title: `14`
  - node text: `12`
  - edge label: `11`
- No serif fonts.
- No ultra-thin text weights.

## 3) Shapes
- Node: rounded rectangle only.
- Group: light background cluster with light gray border.
- Arrowhead: `normal` only.

## 4) Palette (global)
- Orchestrator / Control: `#2563EB`
- Evidence / Knowledge: `#0EA5A4`
- Agents: `#7C3AED`
- Backtest / Artifacts: `#64748B`
- Risk / Approval: `#D97706`
- Counterfactual (dashed): `#E11D48`

Background fills must stay very light (about 10-15% visual intensity).

## 5) Line Hierarchy
- Main flow: `penwidth=2.4`, dark gray or blue, solid.
- Secondary relation: `penwidth=1.2`, light gray, solid.
- Counterfactual path: dashed red.
- Risk gate path: dashed orange.

## 6) Reading Order Rule
Each figure must make this ordering explicit:
1. Main flow (thick solid)
2. Secondary relations (thin gray)
3. Counterfactual / risk links (red/orange dashed)

## 7) Prohibited
- Default matplotlib-style plots for architecture diagrams.
- Mixed font families, mixed corner styles, inconsistent line widths.
- Crossed edges when a hub (e.g., orchestrator/aggregator) can prevent crossing.
- Long sentence text inside nodes.

## 8) Reproducibility
- DOT source files must be kept in `docs/figures/src/`.
- Rendering script must be kept in `docs/figures/scripts/`.
- Generated SVG outputs must be committed under `docs/figures/`.
