# PLANS.md

## Active Plan

### Task
Final wrap-up audit and closeout pass for the current OpenFinance migration / spec-workflow round

### Goal
Formally close this round by documenting what is complete on the active strategy-facing main path, what remains as compatibility debt, and what is intentionally deferred to later tracks without treating every historical raw payload as a blocking architecture gap.

### Task Class
Evidence / audit task / Specification-system task / Risk-sensitive task

### Relevant Files / Modules
- `backend/openfinance/quant/factors/factor_spec.py`
- `backend/openfinance/research/strategy_spec.py`
- `backend/openfinance/research/strategy_decision.py`
- `backend/openfinance/research/strategy_validation.py`
- `backend/openfinance/research/strategy_compilation.py`
- `backend/openfinance/research/strategy_registry.py`
- `backend/openfinance/quant/backtest/evaluation_plan.py`
- `backend/openfinance/quant/backtest/strategy_trace.py`
- `backend/openfinance/quant/backtest/strategy_runtime_summary.py`
- `backend/openfinance/quant/backtest/strategy_runtime_diagnostics.py`
- `backend/openfinance/quant/backtest/strategy_runtime_action_regime.py`
- `backend/openfinance/quant/backtest/strategy_runtime_attribution_execution.py`
- `backend/openfinance/quant/backtest/strategy_runtime_control_optimizer.py`
- `backend/openfinance/quant/backtest/strategy_runtime_control_action_deep.py`
- `backend/openfinance/api/routes_workbench.py`
- `backend/openfinance/api/routes_trace.py`
- `backend/openfinance/api/routes_chat.py`
- `frontend/src/lib/types.ts`
- `frontend/src/app/reports/[runId]/page.tsx`
- `frontend/src/app/reports/page.tsx`

### Exact Files To Change
- `PLANS.md`

### Observations
- Active strategy-facing flows now have explicit typed homes for the high-value main-path objects across:
  - spec
  - decision
  - validation
  - compilation
  - request-side evaluation
  - trace
  - runtime summary
  - runtime diagnostics/result
  - action/regime detail
  - attribution/execution detail
  - control/optimizer detail
  - deeper control/action detail
- The frontend report and compare surfaces already prefer these typed objects and only fall back to raw report payloads for historical compatibility or tolerant rendering.
- Compare and robustness paths still retain legacy compatibility payloads such as `diff_table` and `table`, but they now also expose typed `result_details` and typed row/variant detail objects.
- `BacktestReport` still carries broad raw `diagnostics`, `metrics`, `cost_breakdown`, and raw attribution maps, but the active strategy-facing subset is no longer ownerless.
- Restore flows still preserve raw `request` payloads and partial report compatibility payloads for replayability and historical recovery, even though typed `strategy_trace`, summary, diagnostics, and detail objects now exist alongside them.

### Assumptions
- “Complete enough to close” should mean the active strategy-facing main path has durable, typed ownership for the review-relevant objects users actually inspect and compare.
- Historical raw payloads that remain only as mirrors, compatibility inputs, or broad archival/debug bags should not block closeout if the main path no longer depends on them as the primary source of truth.
- Future tracks should focus on new product capabilities or deeper optional typing only when they materially improve usability or governance, not just to eliminate every remaining raw dict.

### Risks
- If closeout language is too broad, readers may assume every historical diagnostics payload is typed, which is not true.
- If compatibility debt is described too vaguely, future contributors may restart broad diagnostics migration work that no longer has strong product leverage.
- If we fail to distinguish main-path architecture from compatibility mirrors, later refactors may accidentally remove raw payloads still needed for restore, replay, or old artifacts.

### Final Closeout Matrix
| layer/object | current owner | main-path status | remaining debt type | recommended disposition |
| --- | --- | --- | --- | --- |
| `FactorSpec` | `backend/openfinance/quant/factors/factor_spec.py` | complete on main path | none blocking | keep as durable factor contract; evolve in future spec-authoring track |
| `StrategySpec` + registry | `backend/openfinance/research/strategy_spec.py` + `backend/openfinance/research/strategy_registry.py` | complete on main path | naming/field evolution only | keep stable as durable strategy object |
| `StrategyDecision` | `backend/openfinance/research/strategy_decision.py` | complete on main path | no registry by design | keep as decision-time artifact, not source of truth |
| `StrategyValidationResult` | `backend/openfinance/research/strategy_validation.py` | complete on main path | validator breadth can grow later | keep as explicit validation boundary |
| `StrategyCompilationPlan/Profile/PolicyResult` | `backend/openfinance/research/strategy_compilation.py` | complete on main path | deeper compiler policy optional | keep as compile boundary; do not expand casually |
| `BacktestEvaluationPlan` + request input profile | `backend/openfinance/quant/backtest/evaluation_plan.py` | complete on main path | broader non-strategy evaluation uses still raw | keep typed subset; avoid repo-wide forced migration |
| `StrategyTraceArtifact` | `backend/openfinance/quant/backtest/strategy_trace.py` | complete on main path | raw restore request still preserved | keep as trace/report-side typed boundary |
| `runtime_summary` / `outcome_summary` | `backend/openfinance/quant/backtest/strategy_runtime_summary.py` | complete on main path | legacy summary tables still mirrored | keep as summary owner; leave compatibility tables in place |
| `runtime_diagnostics` / `result_details` | `backend/openfinance/quant/backtest/strategy_runtime_diagnostics.py` | complete on main path | broad raw diagnostics still exist | keep typed high-value diagnostic summary and result detail boundary |
| `action_regime_details` | `backend/openfinance/quant/backtest/strategy_runtime_action_regime.py` | complete on main path | historical raw arrays still mirrored | keep typed-first, raw fallback only |
| `attribution_execution_details` | `backend/openfinance/quant/backtest/strategy_runtime_attribution_execution.py` | complete on main path | raw attribution/cost maps still mirrored | keep typed-first, raw compatibility only |
| `control_optimizer_details` | `backend/openfinance/quant/backtest/strategy_runtime_control_optimizer.py` | complete on main path | deeper internals intentionally separate | keep narrow owner for high-value control/optimizer rows |
| `control_action_deep_details` | `backend/openfinance/quant/backtest/strategy_runtime_control_action_deep.py` | complete but optional for deeper review | future enrichment possible | keep separate from shallow control/optimizer detail |
| raw `BacktestReport.diagnostics` | `BacktestReport` compatibility payload | not main-path owner | acceptable compatibility debt | preserve for historical artifacts and tolerant fallback |
| raw `metrics`, `cost_breakdown`, raw attribution maps | `BacktestReport` compatibility payloads | not main-path owner | acceptable compatibility debt | preserve as mirrors; avoid treating them as primary strategy-facing surfaces |
| raw compare `diff_table` / robustness `table` | compare / robustness compatibility payloads | not main-path owner | should-be-typed-later but not blocking | keep for compatibility; prefer typed `result_details` in active surfaces |
| raw restore `request` payload | restore compatibility payload | not main-path owner | acceptable compatibility debt | keep for replay/restore; typed artifacts sit alongside it |
| raw chart/series payloads | report diagnostics / charts | outside this round’s ownership goal | not worth expanding now | leave raw until a dedicated chart/data contract track exists |
| raw `agent_outputs`, `reasoning_steps`, `comparison_table`, broad evidence source bags | pipeline/orchestration outputs | outside typed runtime boundary goal | separate future product track | do not expand in this closeout round |

### Compatibility Debt Classification

#### Acceptable Compatibility Debt
- `BacktestReport.diagnostics`
- `BacktestReport.metrics`
- raw `cost_breakdown`
- raw attribution maps
- raw restore `request`
- raw report/restore compatibility mirrors that duplicate already-owned typed data

Reason:
- these are still useful for replay, tolerant hydration, and older stored artifacts
- they are no longer the preferred main-path owner for high-value strategy-facing objects

#### Should-Be-Typed-Later But Not Blocking
- compare `diff_table`
- robustness `table`
- remaining non-primary restore/report helper payloads that still mirror typed result rows
- selected orchestration/product-facing raw bags such as `comparison_table` when/if product workflows need stronger inspectability

Reason:
- there is still some product value in eventually narrowing these
- they no longer block architecture closeout for the active strategy-facing path

#### Not Worth Expanding Now
- chart/series payloads
- broad historical diagnostics bags not surfaced as first-class strategy-facing review objects
- generic metrics bags where typed summary already covers the review-relevant subset

Reason:
- low leverage for current product quality
- high risk of reopening a broad schema migration with limited user benefit

### Approach
1. Audit the current typed owner map across spec, compile/request, trace, summary, diagnostics, and detail layers.
2. Distinguish typed main-path ownership from compatibility mirrors and historical raw payloads.
3. Update `PLANS.md` into a durable closeout artifact with a final matrix and explicit deferred-work classification.
4. Close the round without starting the next architecture track.

### Verification
- [ ] static owner-map audit across backend typed contracts
- [ ] static audit of frontend typed-first report/compare consumption
- [ ] raw compatibility debt classification review
- [ ] risk/closeout review

### Done When
- The closeout file makes it explicit which layers are complete on the active main path.
- The remaining raw payloads are classified clearly as compatibility debt, later optional typing, or out-of-scope.
- The next major engineering track is named explicitly without starting implementation.

### Post-Change Notes
- This closeout pass must not redesign execution semantics.
- This closeout pass must not change risk/approval/live-execution boundaries.
- This closeout pass must not start pluggable architecture implementation.
- This closeout pass is complete when the architecture/debt state is accurately documented, not when every historical raw payload has been typed.
