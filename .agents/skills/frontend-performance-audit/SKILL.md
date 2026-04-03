---
name: frontend-performance-audit
description: Audit frontend responsiveness, render scope, realtime state flow, and user-perceived interaction cost in OpenFinance before implementing changes.
---

# Frontend Performance Audit Skill

Use this skill when the task involves:
- frontend lag or sluggishness
- oversized providers or global state
- SSE or realtime update performance
- page interaction cost
- route-level responsiveness problems
- heavy debug/audit UI mixed into normal user flows
- deciding what to refactor before changing frontend architecture

## Goal

Produce a structured frontend performance and UX audit for OpenFinance that:
- identifies likely causes of sluggishness
- separates architectural causes from surface symptoms
- prioritizes the highest-leverage fixes
- preserves correctness of realtime task/risk/audit behavior
- gives a safe refactor path instead of random micro-optimizations

This skill is for diagnosis and planning first.
Do not jump straight into implementation unless the user explicitly asks for code changes.

---

## Required Output

Always produce the following sections:

1. Audit Scope
2. Key Observations
3. Likely Bottlenecks
4. Architectural Causes
5. UX Consequences
6. Refactor Priorities
7. Verification Plan
8. Risks / Tradeoffs
9. Recommended Next Step

---

## Core Review Principles

### 1. Optimize for user-perceived responsiveness
Do not focus only on raw technical metrics.
Also inspect:
- interaction smoothness
- time-to-feedback
- page stability during updates
- readability under realtime state changes
- whether debug surfaces increase normal-user complexity

### 2. Prefer render-scope reduction over patchy memoization
If a page or provider is too broad:
- first reduce ownership scope
- then isolate state
- then consider memoization

Do not recommend `memo`, `useMemo`, or `useCallback` everywhere as the default answer.

### 3. Respect correctness of realtime systems
OpenFinance includes tasks, SSE-style event flows, approvals, and audit/evidence surfaces.
A performance improvement is not acceptable if it silently breaks:
- task status consistency
- event ordering assumptions
- risk/approval freshness
- audit visibility
- traceability

### 4. Separate user mode, audit mode, and debug mode
If one render path serves all three at once, treat that as a likely performance and UX smell.

### 5. Distinguish symptoms from causes
Do not stop at “page feels heavy”.
Trace that feeling to concrete causes such as:
- oversized global provider
- too many subscribers
- repeated full refreshes
- heavy derived state during render
- broad context invalidation
- oversized component trees
- unnecessary debug rendering
- repeated data fetch/reconciliation

---

## Audit Process

### Step 1: Define audit scope
State clearly:
- which route, page, or interaction is under review
- whether the issue is always-on or only under realtime updates
- whether the issue is user-mode, audit-mode, or debug-mode specific

### Step 2: Identify high-frequency update sources
Inspect likely sources such as:
- SSE or event-stream updates
- polling refresh loops
- provider-level state refresh
- repeated list synchronization
- chat/session/task refresh coupling
- route transitions that trigger broad re-fetch

### Step 3: Inspect state ownership
Determine whether state is:
- globally owned but should be local
- mixed across unrelated domains
- duplicated across provider and page
- too broad for the routes actually using it

Pay special attention to:
- tasks
- chat/session state
- datasets
- strategies/factors
- risk/approvals
- evidence/debug data

### Step 4: Inspect render breadth
Check for:
- one change causing many subtrees to rerender
- giant page components with many conditional branches
- expensive cards/panels always mounted
- heavy debug or audit panels rendered in default flows
- long lists without virtualization or collapse strategy
- expensive derived transforms executed on each render

### Step 5: Inspect realtime architecture
Check whether the frontend mixes:
- event-driven updates
- scheduled polling
- delayed reconciliation refresh
- manual refresh
without a clear normalization layer

If raw events directly trigger many local state mutations, note that as a likely instability/performance source.

### Step 6: Inspect route experience
Evaluate the route as a product surface:
- is the first meaningful feedback fast?
- are loading states clean?
- are empty states helpful?
- does the page visually jump under updates?
- does debug information crowd the primary task?

### Step 7: Produce a refactor order
Do not recommend “optimize everything”.
Prioritize in order of leverage.

Preferred order:
1. reduce oversized ownership boundaries
2. separate realtime and static state
3. isolate debug/audit rendering from default user mode
4. normalize event flow before UI writes
5. split heavy pages into clearer subtrees
6. optimize expensive lists or transforms
7. apply targeted memoization only where justified

---

## OpenFinance-Specific Heuristics

When auditing OpenFinance, explicitly inspect whether the frontend is suffering from any of these patterns:

- one provider owns too many unrelated slices
- tasks, risk, chat, datasets, and strategies refresh together too often
- SSE events and polling overlap without a single reducer-like normalization layer
- chat pages attempt to show user UX, audit trace, reasoning steps, and debug diagnostics all at once
- evidence and metrics cards remain mounted even when not needed
- list pages depend on global provider state when route-local fetching would be enough
- realtime correctness concerns prevent simple optimization, requiring state-architecture changes instead

---

## Severity Labels

Use these labels where useful:
- Critical
- Major
- Moderate
- Minor

Critical should mean:
- likely to affect most user sessions
- likely to cause broad rerenders or unstable state behavior
- likely to block productization if left unchanged

---

## Output Rules

Always distinguish:
- Observation: directly visible from code structure or behavior described
- Inference: reasoned conclusion from the observations
- Recommendation: proposed next action
- Tradeoff: what might become harder or riskier after the change

Avoid vague advice such as:
- “optimize rendering”
- “improve architecture”
- “use memoization”
unless tied to specific structures and specific consequences

---

## Final Response Template

### Audit Scope
...

### Key Observations
- Observation:
- Observation:

### Likely Bottlenecks
- ...
- ...

### Architectural Causes
- ...
- ...

### UX Consequences
- ...
- ...

### Refactor Priorities
1. ...
2. ...
3. ...

### Verification Plan
- ...
- ...

### Risks / Tradeoffs
- ...
- ...

### Recommended Next Step
...