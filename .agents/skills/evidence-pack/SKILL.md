---
name: evidence-pack
description: Produce a structured change evidence pack for OpenFinance after investigation, design, refactor, or implementation work.
---

# Evidence Pack Skill

Use this skill when the task involves:
- code changes
- architecture changes
- frontend refactors
- factor or strategy abstraction design
- validation work
- investigation results that should be preserved as a durable engineering artifact
- any non-trivial change that should end with a clear summary of evidence, verification, and remaining risks

## Goal

Produce a structured evidence pack that turns a change, investigation, or design task into a reviewable engineering artifact.

The evidence pack should help a reader quickly understand:
- what was changed or proposed
- why the change was made
- what evidence supports it
- what was verified
- what remains uncertain or risky
- what should happen next

This skill is for closing the loop after meaningful work.
It should be used after investigation, design, refactor, or implementation.

---

## Required Output

Always produce the following sections:

1. Task Summary
2. Change or Proposal Summary
3. Why This Was Done
4. Evidence and Reasoning
5. Affected Files / Modules
6. Verification Performed
7. Known Risks / Limitations
8. Non-Goals / What Was Not Changed
9. Recommended Next Step

If the task is investigation-only or design-only, adapt the wording accordingly, but still preserve the same structure.

---

## Core Principles

### 1. Treat the output as a durable artifact
Do not write a casual conversational recap.
Write something that could be:
- reviewed later
- attached to a PR
- pasted into a design review
- used by another engineer as context
- referenced during audit or debugging

### 2. Separate evidence from narrative
Always distinguish:
- what is directly observed
- what is inferred
- what is proposed
- what is still unknown

Do not mix conclusions and raw observations carelessly.

### 3. Verification is part of the evidence
A change without verification is not fully evidenced.

If verification was not run, say so explicitly and explain:
- what was not run
- why it was not run
- what risk remains because of that

### 4. Preserve scope clarity
Readers should be able to tell:
- what changed
- what did not change
- what was intentionally deferred

Do not let the summary imply broader completion than actually occurred.

### 5. Prefer explicit limits over false confidence
Do not overstate readiness.

Avoid phrases like:
- fully production-ready
- completely solved
- no remaining issues
unless the evidence clearly supports them

---

## When to Use This Skill

Use this skill after:
- a frontend performance audit
- a factor/strategy design proposal
- a provider or state refactor
- a risk-sensitive review
- an API or schema change
- a non-trivial debugging task
- a meaningful code modification set

This skill should usually be the closing step after another skill such as:
- frontend-performance-audit
- factor-spec-design
- strategy-spec-design
- risk-gate

---

## Output Structure Guidance

### 1. Task Summary
State briefly:
- what task was performed
- whether it was investigation, design, implementation, or review
- what part of OpenFinance it focused on

### 2. Change or Proposal Summary
Describe:
- what was changed, or
- what design/proposal was produced

This should be concise but specific.

### 3. Why This Was Done
Explain the motivation:
- user pain point
- architectural issue
- product limitation
- risk or validation gap
- extensibility problem

### 4. Evidence and Reasoning
Break this into:
- Observations
- Inferences
- Proposal or decision rationale

Use this section to show that the work was grounded.

### 5. Affected Files / Modules
List:
- changed files
- relevant modules reviewed
- related boundaries affected

If it is a design-only task, list the modules or layers expected to be affected.

### 6. Verification Performed
State explicitly what was checked.

Possible items:
- unit tests
- integration tests
- e2e tests
- lint / type checks
- manual UX inspection
- render path inspection
- schema review
- backtest realism review
- risk review

For each major item, prefer one of:
- run and passed
- run and revealed issues
- not run

### 7. Known Risks / Limitations
State what remains unresolved.

Examples:
- migration path not yet implemented
- no performance benchmark yet
- schema validator not yet built
- UX improved in one route but not globally
- backend assumptions still need confirmation

### 8. Non-Goals / What Was Not Changed
This section is important.
Clarify what was deliberately not included.

Examples:
- no backend API changes
- no execution-path modifications
- no production approval logic changes
- no UI redesign beyond the target route

### 9. Recommended Next Step
Recommend the highest-leverage next action, not a giant wishlist.

Pick the next step that most naturally follows from the current evidence.

---

## OpenFinance-Specific Guidance

When producing evidence packs for OpenFinance, explicitly preserve whether the work touched any of these layers:

- frontend UX / performance
- orchestration / workflow logic
- factor or strategy abstractions
- risk / approval logic
- evidence / audit surfaces
- data contracts or schemas
- execution-adjacent logic

If a task touches risk-sensitive boundaries, explicitly say so.

If a task affects inspectability, auditability, or traceability, explicitly say so.

If a task is only a design proposal and not yet implemented, make that unmistakably clear.

---

## Style Rules

- Be concrete
- Be scoped
- Be reviewable
- Be honest about unknowns
- Avoid inflated language
- Avoid vague praise of the change
- Avoid pretending that partial work is complete

Prefer:
- “Implemented the first step of provider decomposition for task state”
over:
- “Significantly improved architecture”

Prefer:
- “Proposed a FactorSpec schema and validator boundary; compiler integration remains unimplemented”
over:
- “Built an extensible factor generation system”

---

## Optional Severity / Confidence Labels

Where useful, you may add:
- Severity: Critical / Major / Moderate / Minor
- Confidence: High / Medium / Low

Use them only when they help clarify uncertainty or importance.

---

## Final Response Template

### Task Summary
...

### Change or Proposal Summary
...

### Why This Was Done
...

### Evidence and Reasoning

#### Observations
- ...

#### Inferences
- ...

#### Decision / Proposal Rationale
- ...

### Affected Files / Modules
- ...

### Verification Performed
- ...
- ...

### Known Risks / Limitations
- ...
- ...

### Non-Goals / What Was Not Changed
- ...
- ...

### Recommended Next Step
...