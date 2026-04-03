---
name: strategy-spec-design
description: Design a structured, extensible, and validation-ready StrategySpec for OpenFinance instead of relying on template-bound or opaque strategy generation.
---

# Strategy Spec Design Skill

Use this skill when the task involves:
- redesigning strategy generation
- defining a reusable strategy abstraction
- mapping factor outputs into strategy semantics
- building a strategy registry or schema
- improving inspectability and extensibility of strategy generation
- separating research intent from execution-adjacent semantics
- preparing strategy generation for validation, simulation, UI display, audit, and risk review

## Goal

Design or refine a structured `StrategySpec` system for OpenFinance so that strategy creation becomes:

- explicit instead of opaque
- extensible instead of template-bound
- inspectable instead of hidden in prompts
- validation-ready instead of ad hoc
- compilable instead of manually interpreted
- risk-gated instead of semantically loose
- evidence-linked instead of purely generative

This skill is for abstraction and schema design first.
Do not jump straight into implementation unless explicitly asked.

---

## Required Output

Always produce the following sections:

1. Design Scope
2. Current Problem
3. Design Goals
4. Proposed StrategySpec Structure
5. Field Semantics
6. Validation Rules
7. Compilation / Simulation Path
8. UI / Inspectability Requirements
9. Risk and Approval Boundaries
10. Extensibility Strategy
11. Risks / Tradeoffs
12. Recommended Next Step

---

## Core Design Principles

### 1. A strategy is not just a backtest config
Treat a strategy as a structured decision artifact, not merely:
- a prompt output
- a parameter bundle
- a single backtest script
- an execution-like instruction set

A good strategy representation should preserve:
- intended objective
- signal source
- instrument universe
- selection logic
- weighting logic
- rebalance logic
- constraint logic
- risk overlays
- simulation assumptions
- approval requirements
- limitations

### 2. Separate research intent from operational semantics
Do not mix:
- what market behavior the strategy is trying to exploit
with
- how the system constructs positions or simulated decisions

At minimum distinguish:
- `thesis` or `intent`: why the strategy exists
- `spec`: how the strategy is formed, constrained, and evaluated

### 3. Separate recommendation semantics from action semantics
A StrategySpec may support:
- research comparison
- simulation
- recommendation generation
but that does not mean it should imply:
- direct execution
- autonomous action
- production readiness

The structure must preserve these distinctions explicitly.

### 4. Prefer structured semantics over prompt-only generation
Natural-language reasoning may help propose a strategy idea.
But the durable product artifact should be structured, reviewable, and machine-checkable.

### 5. Design for validation, simulation, and governance
A usable `StrategySpec` must support:
- schema validation
- compatibility checks with FactorSpec or signal outputs
- simulation / backtest construction
- UI explanation
- evidence and audit linkage
- risk and approval review

---

## Design Process

### Step 1: Define the current problem clearly
State what the current strategy-generation system is missing.

Typical problems may include:
- only instantiates prewritten strategy directions
- hidden assumptions about selection, weighting, and rebalance logic
- unclear distinction between strategy idea and simulation semantics
- weak inspectability in UI
- weak compatibility with evidence, risk, and approval surfaces
- difficult to extend across markets, asset classes, or portfolio styles
- hard to compare strategies systematically

Do not say only “it is not flexible enough”.
Be specific.

### Step 2: Define what a StrategySpec must support
At minimum inspect whether the design needs to support:

- long-only strategies
- long-short strategies
- ranking-based selection
- threshold-based selection
- factor-combination strategies
- multi-signal strategies
- portfolio construction rules
- rebalance schedules
- turnover controls
- exposure constraints
- market / asset-class adapters
- simulation-only modes
- recommendation-facing output
- approval metadata

### Step 3: Propose a canonical structure
A strong StrategySpec usually includes fields such as:

- `id`
- `name`
- `version`
- `thesis`
- `description`
- `strategy_family`
- `asset_class`
- `market_scope`
- `frequency`
- `target_horizon`
- `signal_sources`
- `selection_rule`
- `weighting_rule`
- `rebalance_rule`
- `position_constraints`
- `risk_overlays`
- `simulation_assumptions`
- `approval_requirements`
- `validation_rules`
- `assumptions`
- `limitations`
- `evidence_links`
- `status`

You do not have to use exactly these names, but the structure must be explicit and justified.

### Step 4: Define field semantics
For each important field, explain:
- what it means
- whether it is required
- its expected type or shape
- what invalid values look like
- whether it belongs to research semantics, simulation semantics, risk semantics, or UI metadata

### Step 5: Define the decision representation
Choose how strategy logic is represented.

Possible directions:
- declarative rules
- a staged portfolio construction pipeline
- a graph of signal -> selection -> weighting -> constraints -> rebalance
- a registry-backed composition model

When proposing a representation, explain:
- why it fits OpenFinance
- how it supports validation
- how it supports inspectability
- how it stays compatible with FactorSpec and future compiler layers
- how it avoids becoming too magical or too execution-like

### Step 6: Define validation rules
At minimum, specify whether the validator should check:

- required fields exist
- referenced factor/signal sources exist
- selection rule and weighting rule are compatible
- rebalance rule is valid for the specified frequency
- position constraints are internally consistent
- market / asset combinations are supported
- unsupported strategy families are rejected
- impossible rule order is rejected
- risk overlay configuration is legal
- recommendation-facing strategies are clearly labeled
- forbidden execution-like semantics are blocked unless explicitly allowed

Validation should fail loudly and structurally.

### Step 7: Define compilation or simulation mapping
A StrategySpec should not stop at metadata.
Explain how it maps into downstream use.

Examples:
- StrategySpec -> simulation/backtest config
- StrategySpec -> portfolio construction graph
- StrategySpec -> UI summary + evidence artifact
- StrategySpec -> approval review object
- StrategySpec -> recommendation view, without implying direct execution

If a compiler/translator layer is needed, describe it explicitly.

### Step 8: Define inspectability and product surfaces
The strategy should be readable in product surfaces.

At minimum explain how users could inspect:
- summary
- thesis
- signal sources
- selection logic
- weighting logic
- rebalance logic
- constraints and overlays
- assumptions
- warnings / validation results
- comparable strategies in the same family

Do not design a backend-only abstraction that the UI cannot explain.

### Step 9: Define risk and approval boundaries
Explain how StrategySpec preserves boundaries between:
- research strategy
- simulated strategy
- recommendation artifact
- execution-adjacent behavior

At minimum consider:
- explicit simulation-only labels
- approval requirements
- human-in-the-loop requirements
- risk review hooks
- disallowed direct-action semantics by default

### Step 10: Define extensibility strategy
Explain how the system can grow without collapsing into chaos.

Possible mechanisms:
- strategy-family registry
- portfolio-construction registry
- factor/signal compatibility layer
- market adapters
- schema versioning
- capability flags by asset class or market
- compatibility layer for old templates

Extensibility should be constrained, not anarchic.

---

## OpenFinance-Specific Heuristics

When designing StrategySpec for OpenFinance, explicitly inspect whether the system needs to solve these repository-specific issues:

- current strategy generation may be constrained by prewritten directions instead of structured composition
- strategy outputs must connect to reports, evidence, and risk surfaces
- strategy semantics should be visible in the UI, not buried in prompts
- the abstraction should remain compatible with FactorSpec and future compiler layers
- strategy design must not blur simulation and execution-adjacent behavior
- approval and audit workflows must remain explicit when strategy outputs become recommendation-like

---

## Recommended Shape Guidelines

These are guidelines, not mandatory exact field names.

A strong StrategySpec often contains four conceptual layers:

### Layer A: Identity and lifecycle
Examples:
- id
- name
- version
- author/source
- created_at
- status
- draft/validated/deprecated

### Layer B: Research and intent semantics
Examples:
- thesis
- description
- strategy_family
- intended use
- market rationale
- expected behavior
- limitations

### Layer C: Decision and portfolio semantics
Examples:
- signal_sources
- selection_rule
- weighting_rule
- rebalance_rule
- constraints
- risk_overlays
- simulation assumptions
- output semantics

### Layer D: Product and governance metadata
Examples:
- validation results
- evidence links
- approval requirements
- UI summary
- warnings
- lineage / provenance
- downstream compatibility

A good proposal should clearly separate these layers.

---

## What to Avoid

Avoid designs that are primarily:

- one giant prompt string
- arbitrary execution-like scripts without structure
- hidden portfolio construction behavior
- untyped free-form JSON blobs
- strategy templates with no extension path
- simulation and action semantics mixed together
- schema that is impossible to explain to users
- schema so abstract that implementation becomes vague hand-waving

---

## Severity Labels

Use these labels if comparing design risks:
- Critical
- Major
- Moderate
- Minor

Critical should mean:
- design blurs recommendation and action semantics
- design cannot be validated safely
- design hides core strategy logic
- design cannot support simulation mapping or UI inspectability
- design weakens future risk-gating and approval workflows

---

## Output Rules

Always distinguish:
- Observation: what the current system appears to do
- Limitation: what is structurally missing
- Proposal: what the new design should introduce
- Tradeoff: what complexity or migration cost the new design creates

Do not claim a design is “industrial-grade” unless the proposal clearly includes:
- explicit structure
- validation strategy
- inspectability
- extensibility path
- downstream simulation mapping
- clear risk/approval boundaries

---

## Final Response Template

### Design Scope
...

### Current Problem
- Observation:
- Limitation:

### Design Goals
- ...
- ...

### Proposed StrategySpec Structure
- ...
- ...

### Field Semantics
- ...
- ...

### Validation Rules
- ...
- ...

### Compilation / Simulation Path
- ...
- ...

### UI / Inspectability Requirements
- ...
- ...

### Risk and Approval Boundaries
- ...
- ...

### Extensibility Strategy
- ...
- ...

### Risks / Tradeoffs
- ...
- ...

### Recommended Next Step
...