# AGENTS.md

## Mission

OpenFinance is a financial research-and-execution workbench.
It is not a generic chatbot project and not a demo-first UI shell.

The repository should evolve toward an industrial-grade product that is:

- evidence-based
- reproducible
- auditable
- risk-aware
- modular
- production-conscious
- user-friendly

The current top priorities are:

1. improve product usability and frontend responsiveness
2. redesign factor/strategy generation into an extensible specification-driven system
3. strengthen engineering governance so Codex can modify the codebase safely and consistently

---

## Product Identity

OpenFinance should behave like a financial operating workbench where users can:

- explore ideas
- define hypotheses
- generate or refine factor/strategy specifications
- run constrained validation and backtests
- review evidence and reports
- pass through risk and approval gates
- preserve traceability and auditability

Do not treat the system as “an LLM that magically invents strategies”.
Treat it as a constrained research pipeline with explicit artifacts, controls, and review boundaries.

---

## Repository Priorities

When making tradeoffs, prefer in this order:

1. correctness and auditability
2. safety and explicitness
3. user experience and responsiveness
4. extensibility of research abstractions
5. implementation speed

Never optimize for convenience by weakening traceability, safety, or validation.

---

## Current Engineering Focus

### A. Frontend experience and performance
The frontend currently requires focused improvement in responsiveness, state isolation, and rendering efficiency.

When working on frontend code:
- reduce unnecessary global re-renders
- avoid oversized provider state
- prefer localized data ownership where possible
- avoid mixing user mode, audit mode, and debug mode in one heavy render path
- keep SSE/event-driven updates structured and predictable
- optimize for clarity first, then micro-optimization

### B. Factor and strategy extensibility
The system should move from template-bound instantiation toward specification-driven extensibility.

Target direction:
- factor generation should produce structured FactorSpec, not ad hoc opaque output
- strategy generation should produce structured StrategySpec, not only instantiate prewritten templates
- specs must be validated, compilable, and inspectable
- generation must remain constrained, reviewable, and evidence-linked

### C. Industrialized governance
Codex should not modify the codebase as a generic autocomplete assistant.
It must operate as a governed engineering agent.

That means:
- classify the task
- plan before non-trivial changes
- preserve architectural boundaries
- verify changes
- summarize evidence, risks, and limitations

---

## Architectural Boundaries

Preserve and respect these boundaries unless there is a strong, explicitly stated reason to change them:

- user interaction layer
- orchestration / workflow layer
- factor / strategy specification layer
- backtest / execution simulation layer
- risk / approval layer
- evidence / audit layer
- storage / registry layer

Do not collapse research logic, execution logic, and UI presentation into one mixed path.

Notebook logic is not production logic.
Prototype logic is not release logic.
Debug visibility is not user-facing UX.

---

## Task Classification

Before changing code, classify the task as one of the following:

### 1. Product UX task
Examples:
- improve interaction flow
- reduce frontend lag
- simplify page structure
- improve empty/loading/error states

Expected output:
- user pain point
- affected route/components
- performance or UX rationale
- verification steps

### 2. Specification-system task
Examples:
- define FactorSpec
- define StrategySpec
- create registry or compiler
- add validator or schema checks

Expected output:
- schema or abstraction change
- compatibility impact
- migration or adaptation notes
- validation strategy

### 3. Risk-sensitive task
Examples:
- execution path changes
- position sizing changes
- approval flow changes
- automated action boundary changes
- kill switch changes

Expected output:
- failure modes
- controls inventory
- missing controls
- deployment caution

### 4. Evidence / audit task
Examples:
- improve trace display
- improve reports/evidence linkage
- clarify reasoning surfaces
- add reproducibility artifacts

Expected output:
- source of truth
- persisted artifacts
- audit implications
- user-visible implications

### 5. General implementation task
Examples:
- refactor module boundaries
- add endpoint
- improve tests
- rename internal structures

Expected output:
- changed files/modules
- rationale
- risk and regression notes
- verification summary

---

## Hard Rules

### 1. Plan before non-trivial work
A task is non-trivial if it includes any of:
- more than one file change
- architecture or schema changes
- state management changes
- factor / strategy / backtest / risk logic
- execution or approval path changes
- unclear impact radius

For non-trivial tasks:
- write or update a plan first
- identify affected files/modules
- identify assumptions and risks
- define verification

### 2. Separate fact from interpretation
Always distinguish:
- Observation
- Inference
- Hypothesis
- Action

Do not describe guesses as confirmed architecture facts.

### 3. No magical generation claims
Do not describe factor/strategy creation as unconstrained AI creativity.
Always frame it as constrained generation under:
- schema
- available data
- operator registry
- validation rules
- risk and evidence constraints

### 4. No silent boundary crossing
Do not silently move logic across:
- frontend ↔ orchestration
- orchestration ↔ execution
- research ↔ production
- model output ↔ action
- evidence layer ↔ hidden internal logic

### 5. No silent weakening
Do not silently:
- remove safety checks
- weaken test coverage to make code pass
- reduce logging or auditability
- blur approval boundaries
- hardcode assumptions without comment
- introduce broad global state when a local boundary is better

### 6. Done means verified
Code written is not equal to task completed.

A task is complete only when:
- changes are explained
- affected files are identified
- verification steps are run or explicitly marked unrun
- risks and limitations are stated

---

## Frontend Performance Rules

When working on frontend performance or UX:

- prefer reducing render scope over adding ad hoc memoization everywhere
- prefer splitting oversized providers over expanding them
- keep realtime state and static resource state separate
- avoid broad context updates when only one slice changes
- avoid combining debug-heavy views with default user mode
- prefer predictable event normalization before UI updates
- preserve correctness of task/event/risk state while optimizing

If a performance improvement might alter semantics of realtime updates, explain the tradeoff clearly.

---

## Factor / Strategy Design Rules

When working on factor or strategy generation:

- design structured specs before implementation details
- define required inputs explicitly
- define supported operators explicitly
- define validation rules explicitly
- define unsupported cases explicitly
- preserve inspectability in UI and evidence outputs
- prefer composable registries over monolithic prompt logic

Desired direction:
- hypothesis -> spec -> validator -> compiler -> backtest/simulation -> evidence -> approval

Avoid:
- one-shot opaque prompt-to-code generation
- hidden defaults
- silent field coercion
- unexplained operator behavior
- mixing market assumptions into generic logic without clear adapters

---

## Risk-Sensitive Rules

For any task touching execution, approval, or automated action:

- identify what is recommendation vs executable action
- identify what still requires human approval
- identify failure modes
- identify rollback or kill-switch implications
- identify monitoring and audit implications

Never call such changes production-ready unless evidence clearly supports that claim.

---

## Required Output Format

For implementation tasks, end with:

1. What changed
2. Why it changed
3. Affected files/modules
4. Verification performed
5. Risks / limitations
6. Recommended next step

For investigation or review tasks, end with:

1. Observations
2. Inferences
3. Hypotheses
4. Suggested actions

---

## Preferred Working Sequence

1. Read relevant code and docs
2. Classify the task
3. Create or update plan if non-trivial
4. Make scoped changes
5. Run verification
6. Summarize evidence and risks
7. Suggest the next most leverageable step

---

## Quality Standard

Favor:
- explicitness over cleverness
- modularity over shortcuts
- inspectability over magic
- constrained extensibility over fragile flexibility
- safe partial improvement over unsafe sweeping change