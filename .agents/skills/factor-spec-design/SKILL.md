---
name: factor-spec-design
description: Design a structured, extensible, and validation-ready FactorSpec for OpenFinance instead of relying on opaque prompt-only factor generation.
---

# Factor Spec Design Skill

Use this skill when the task involves:
- redesigning factor generation
- defining a reusable factor abstraction
- turning research ideas into structured factor specifications
- building a factor registry or factor schema
- improving inspectability and extensibility of factor generation
- separating factor hypothesis from factor implementation
- preparing factor generation for validation, compilation, UI display, and audit

## Goal

Design or refine a structured `FactorSpec` system for OpenFinance so that factor creation becomes:

- explicit instead of opaque
- extensible instead of template-bound
- inspectable instead of hidden in prompts
- validation-ready instead of ad hoc
- compilable instead of manually interpreted
- evidence-linked instead of purely generative

This skill is for abstraction and schema design first.
Do not jump straight into implementation unless explicitly asked.

---

## Required Output

Always produce the following sections:

1. Design Scope
2. Current Problem
3. Design Goals
4. Proposed FactorSpec Structure
5. Field Semantics
6. Validation Rules
7. Compilation / Execution Path
8. UI / Inspectability Requirements
9. Extensibility Strategy
10. Risks / Tradeoffs
11. Recommended Next Step

---

## Core Design Principles

### 1. A factor is not just code
Treat a factor as a structured research artifact, not merely a Python function or a prompt output.

A good factor representation should preserve:
- hypothesis
- inputs
- operators
- transformation steps
- frequency and horizon assumptions
- normalization assumptions
- missing-data behavior
- evaluation intent
- limitations

### 2. Separate hypothesis from specification
Do not mix:
- why the factor exists
with
- how the factor is computed

The system should preserve both.

At minimum distinguish:
- `hypothesis`: what market behavior or mechanism the factor is trying to capture
- `spec`: how the factor should be computed and validated

### 3. Prefer structured semantics over free-form prose
A factor system should not depend on a long opaque natural-language prompt as the main source of truth.

Natural language may help propose ideas, but the durable product artifact should be structured.

### 4. Design for validation and compilation
A usable `FactorSpec` must support:
- schema validation
- data availability checks
- operator compatibility checks
- execution graph construction
- factor preview / explanation in UI
- audit/evidence surfaces

### 5. Preserve inspectability
Users and reviewers should be able to answer:
- what this factor is supposed to measure
- what inputs it needs
- how it transforms data
- what assumptions it makes
- what risks or limitations it has

If these cannot be answered from the factor representation, the design is incomplete.

---

## Design Process

### Step 1: Define the current problem clearly
State what the current factor-generation system is missing.

Typical problems may include:
- only instantiates prewritten factor directions
- prompt output is not reusable as a durable artifact
- hidden assumptions about data and operators
- weak compatibility with UI, evidence, or validation
- hard to expand across markets or asset classes
- difficult to compare or audit factors systematically

Do not say only “it is not flexible enough”.
Be specific.

### Step 2: Define what a FactorSpec must support
At minimum inspect whether the design needs to support:

- cross-sectional factors
- time-series factors
- event-driven factors
- single-input and multi-input transforms
- configurable windows
- normalization / winsorization / ranking
- universe filters
- market-specific adaptations
- required data field declarations
- metadata for evidence and UI

### Step 3: Propose a canonical structure
A strong FactorSpec usually includes fields such as:

- `id`
- `name`
- `version`
- `hypothesis`
- `description`
- `factor_family`
- `asset_class`
- `market_scope`
- `frequency`
- `target_horizon`
- `inputs`
- `operators`
- `parameters`
- `pipeline` or `transform_graph`
- `output`
- `constraints`
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
- whether it belongs to research semantics, execution semantics, or UI metadata

### Step 5: Define the computation representation
Choose how computation is represented.

Possible directions:
- a linear pipeline
- a graph of operators
- a declarative mini-DSL
- a registry-backed composition model

When proposing a representation, explain:
- why it fits OpenFinance
- how it supports validation
- how it supports extensibility
- how it avoids becoming too magical

### Step 6: Define validation rules
At minimum, specify whether the validator should check:

- required fields exist
- referenced inputs exist
- operator names are valid
- operator-parameter compatibility is valid
- window values are legal
- frequency/horizon combinations are legal
- unsupported market/asset combinations are rejected
- impossible transformation order is rejected
- forbidden future-dependent operations are blocked

Validation should fail loudly and structurally.

### Step 7: Define compilation or execution mapping
A FactorSpec should not stop at metadata.
Explain how it maps into execution.

Examples:
- FactorSpec -> factor DAG
- FactorSpec -> feature pipeline
- FactorSpec -> backtest-ready computation node
- FactorSpec -> UI preview + evidence artifact

If a compiler/translator layer is needed, describe it explicitly.

### Step 8: Define inspectability and product surfaces
The factor should be readable in product surfaces.

At minimum explain how users could inspect:
- summary
- hypothesis
- required inputs
- transformation steps
- assumptions
- warnings / validation results
- comparable factors in the same family

Do not design a backend-only abstraction that the UI cannot explain.

### Step 9: Define extensibility strategy
Explain how the system can grow without collapsing into chaos.

Possible mechanisms:
- operator registry
- market adapters
- factor-family templates
- schema versioning
- compatibility layer for old factor definitions
- capability flags by asset class

Extensibility should be constrained, not anarchic.

---

## OpenFinance-Specific Heuristics

When designing FactorSpec for OpenFinance, explicitly inspect whether the system needs to solve these repository-specific issues:

- current factor generation may be constrained by prewritten directions instead of open structured composition
- factor creation must connect to evidence, reports, and validation surfaces
- factor semantics should be visible in the UI, not buried in prompts
- the abstraction should not break downstream strategy generation
- the abstraction should be compatible with future strategy specs and compiler layers
- factor design must not bypass risk and review workflows when factors influence decision paths

---

## Recommended Shape Guidelines

These are guidelines, not mandatory exact field names.

A strong FactorSpec often contains four conceptual layers:

### Layer A: Identity and lifecycle
Examples:
- id
- name
- version
- author/source
- created_at
- status
- draft/validated/deprecated

### Layer B: Research semantics
Examples:
- hypothesis
- description
- factor_family
- intended use
- market rationale
- expected behavior
- limitations

### Layer C: Computation semantics
Examples:
- inputs
- operators
- parameters
- windows
- transform graph
- output definition
- constraints
- fallback rules
- missing-data handling

### Layer D: Product and governance metadata
Examples:
- validation results
- evidence links
- compatibility notes
- UI summary
- warnings
- lineage / provenance
- downstream strategy compatibility

A good proposal should clearly separate these layers.

---

## What to Avoid

Avoid designs that are primarily:

- one giant prompt string
- arbitrary Python snippets without structure
- hidden operator behavior
- untyped free-form JSON blobs
- market assumptions mixed into generic operator logic without adapters
- hardcoded factor families with no extension strategy
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
- design blocks extensibility
- design hides core semantics
- design cannot be validated safely
- design cannot support downstream compilation or UI inspectability

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
- downstream execution mapping

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

### Proposed FactorSpec Structure
- ...
- ...

### Field Semantics
- ...
- ...

### Validation Rules
- ...
- ...

### Compilation / Execution Path
- ...
- ...

### UI / Inspectability Requirements
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