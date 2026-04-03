---
name: risk-gate
description: Apply a structured risk gate to OpenFinance tasks that touch strategy, execution-adjacent logic, approvals, automation boundaries, or production-sensitive financial workflows.
---

# Risk Gate Skill

Use this skill when the task involves:
- factor outputs affecting downstream strategy decisions
- strategy generation or strategy execution semantics
- portfolio construction logic
- recommendation-to-action boundaries
- approval flows
- kill switch logic
- automated actions or action proposals
- execution-adjacent backend or UI changes
- risk limit handling
- anything that could move OpenFinance closer to production-sensitive behavior

## Goal

Apply a structured risk gate before describing a change as safe, ready, or deployable.

This skill exists to prevent OpenFinance from drifting from:
- research workbench
into
- unsafe pseudo-production behavior
without explicit controls, boundaries, and review.

Use this skill to determine:
- what layer the task belongs to
- whether it touches a sensitive boundary
- what controls already exist
- what controls are missing
- what must happen before the change can be treated as production-capable

This skill is for review and gating first.
Do not jump straight into implementation unless explicitly asked.

---

## Required Output

Always produce the following sections:

1. Gate Scope
2. Sensitive Boundary Classification
3. What the Change Actually Affects
4. Existing Controls
5. Missing or Weak Controls
6. Failure Modes
7. Approval / Human-in-the-Loop Status
8. Audit / Traceability Implications
9. Deployment Status
10. Required Follow-Up
11. Risk Verdict

---

## Core Principles

### 1. Distinguish research, recommendation, and action
Always separate:
- research artifact
- analytical recommendation
- user-facing decision support
- executable action
- automated action

Do not blur these layers.

A system that explains an idea is not the same as a system that proposes a tradable signal.
A system that proposes a signal is not the same as a system that can trigger an action.

### 2. No production claims without control evidence
Do not describe a change as:
- safe
- production-ready
- deployable
- robust
unless controls and evidence clearly support that claim.

### 3. Risk is broader than market loss
Inspect not only strategy risk, but also:
- data leakage risk
- approval bypass risk
- automation creep
- audit blind spots
- stale-state risk
- UI misrepresentation risk
- silent fallback risk
- kill-switch absence
- inconsistent realtime state risk

### 4. User interpretation risk matters
In OpenFinance, the UI itself can create risk if it:
- implies recommendations are executable
- hides uncertainty
- hides approval requirements
- shows stale status as current
- mixes simulated and action-ready outputs unclearly

### 5. Stronger claims require stronger gates
The closer a feature gets to production-sensitive use, the stricter the review must be.

Research notes need one level of scrutiny.
Execution-adjacent logic needs much more.

---

## Risk Gate Process

### Step 1: Define the gate scope
State:
- what task or proposed change is under review
- whether it is design, implementation, refactor, or review
- which OpenFinance layer it touches

Typical layers:
- research abstraction layer
- strategy layer
- simulation / backtest layer
- approval layer
- risk-control layer
- execution-adjacent layer
- audit / evidence layer
- UI interpretation layer

### Step 2: Classify the sensitive boundary
Explicitly classify whether the task touches any of these boundaries:

- factor -> strategy boundary
- strategy -> recommendation boundary
- recommendation -> executable action boundary
- user approval -> system action boundary
- simulated result -> action-like presentation boundary
- normal workflow -> emergency stop / kill-switch boundary
- hidden internal state -> user-visible decision boundary

If no sensitive boundary is touched, say so clearly.

### Step 3: Describe what the change actually affects
Be concrete.

Examples:
- changes only schema design
- changes how factor outputs are interpreted by strategy generation
- changes approval UI semantics
- changes whether an action can be surfaced without approval
- changes execution-adjacent backend logic
- changes visibility of risk warnings
- changes user perception of recommendation confidence

### Step 4: Inventory existing controls
List controls already present or apparently present.

Examples:
- human approval step
- explicit approval state
- risk review workflow
- kill switch
- audit event logging
- trace / evidence persistence
- simulation-only labeling
- validation checks
- readonly review step
- manual confirmation requirement

Only count controls that are actually visible or clearly specified.

### Step 5: Identify missing or weak controls
Inspect whether any of the following are missing or weak:

- explicit distinction between recommendation and action
- approval enforcement
- kill switch or rollback path
- stale-state protection
- audit logging
- validation before downstream execution
- clear simulation-only boundary
- user-visible warnings
- operator or spec validation
- backtest realism checks
- leakage safeguards

### Step 6: Identify failure modes
Think through what could go wrong if the change is misunderstood, misused, or partially broken.

Examples:
- recommendation displayed as if ready for execution
- factor with hidden leakage influences downstream selection
- approval state not enforced consistently
- stale UI state suggests a risk gate has passed when it has not
- silent fallback bypasses validation
- kill switch exists but is not reachable or not respected
- evidence exists but does not capture critical action context

### Step 7: Review approval and human-in-the-loop status
Explicitly answer:
- does this task require human approval?
- should the system block autonomous progression?
- is the human approval boundary already explicit?
- is the UI honest about where human confirmation is still required?

### Step 8: Review audit / traceability implications
Check whether the task affects:
- audit logs
- trace events
- evidence packs
- reviewability of decisions
- replayability of state changes
- ability to reconstruct what happened later

A change that weakens traceability should be treated seriously.

### Step 9: Determine deployment status
Use one of these labels:

- Research-only
- Safe for design exploration
- Safe for simulation use
- Requires additional controls before broader internal use
- Not safe to treat as production-capable

Be conservative.

### Step 10: Define required follow-up
List the smallest set of next actions required before the feature can move one level closer to production-like use.

Do not produce a giant wishlist.
Prioritize gating items.

---

## OpenFinance-Specific Heuristics

When applying the risk gate in OpenFinance, explicitly inspect these repository-relevant concerns:

- factor generation may influence strategy generation before semantics are fully validated
- strategy generation may appear more authoritative than it actually is
- UI wording may unintentionally make simulated outputs feel executable
- audit and evidence surfaces may exist, but may not yet fully cover action-relevant context
- realtime frontend state may misrepresent freshness or approval status
- architectural changes may accidentally weaken boundaries that were previously explicit
- future extensibility work may quietly move the system toward automation creep

---

## Suggested Control Categories

When useful, group controls under these categories:

### A. Semantic controls
Examples:
- recommendation vs action labels
- simulation-only labels
- confidence / uncertainty display
- limitation display

### B. Workflow controls
Examples:
- explicit approval checkpoints
- manual confirmation steps
- staged release of capabilities
- blocked execution paths

### C. Technical controls
Examples:
- schema validation
- operator validation
- state guards
- stale-state rejection
- readonly review agents
- kill switch

### D. Audit controls
Examples:
- trace persistence
- evidence pack generation
- approval event logging
- decision provenance
- replayability

---

## Severity Guidance

Use these labels where helpful:
- Critical
- Major
- Moderate
- Minor

Critical should mean:
- could cause unsafe interpretation or unsafe downstream behavior
- weakens approval or control boundaries
- creates ambiguous action semantics
- weakens traceability around sensitive workflows

---

## Risk Verdict Guidance

End with one verdict:

- Pass
- Pass with caveats
- Block pending controls
- Reject for production-sensitive use

Use:
- Pass only when controls are clearly adequate for the task scope
- Pass with caveats when risk is manageable but not fully closed
- Block pending controls when the direction may be valid but required gates are missing
- Reject for production-sensitive use when the design or implementation crosses boundaries unsafely

---

## Output Rules

Always distinguish:
- Observation: what is directly visible
- Concern: what risk follows from it
- Control: what mitigates the risk
- Gap: what is still missing
- Verdict: how the change should be treated right now

Do not use vague language like:
- “should be okay”
- “probably safe”
- “looks production-ready”
without structured support.

---

## Final Response Template

### Gate Scope
...

### Sensitive Boundary Classification
- ...
- ...

### What the Change Actually Affects
- ...
- ...

### Existing Controls
- ...
- ...

### Missing or Weak Controls
- ...
- ...

### Failure Modes
- ...
- ...

### Approval / Human-in-the-Loop Status
- ...
- ...

### Audit / Traceability Implications
- ...
- ...

### Deployment Status
...

### Required Follow-Up
1. ...
2. ...
3. ...

### Risk Verdict
...