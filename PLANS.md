# PLANS.md

## Active Plan

### Task
Phase-1 Group 2B-2d-chat: reduce remaining `/chat` legacy dependency surface around restore and chat-specific freshness

### Goal
Move `/chat` restore consumption and chat-specific freshness ownership further into `ChatWorkspaceProvider` and `ResearchContextProvider`, keep `ChatWorkspaceProvider` as the rendering source of truth, and remove `/chat`’s remaining dependence on omnibus `refreshCore/refreshingCore` where a targeted reconcile is sufficient.

### Task Class
Product UX / General implementation

### Relevant Files / Modules
- `frontend/src/components/providers/chat-workspace-provider.tsx`
- `frontend/src/components/providers/research-context-provider.tsx`
- `frontend/src/lib/research-context-store.ts`
- `frontend/src/components/providers/workbench-provider.tsx`
- `frontend/src/app/chat/page.tsx`

### Exact Files To Change
- `PLANS.md`
- `frontend/src/lib/research-context-store.ts`
- `frontend/src/components/providers/research-context-provider.tsx`
- `frontend/src/components/providers/chat-workspace-provider.tsx`
- `frontend/src/components/providers/workbench-provider.tsx`
- `frontend/src/app/chat/page.tsx`

### Observations
- `/chat` already renders from workspace-owned session list and turns, but restore payload handling is still implicit and mixed across URL state, research context, and legacy restore flow.
- `WorkbenchProvider.restoreTraceContext()` still performs a legacy `refreshCore({ silent: true })`, even though dashboard and reports navigate directly to `/chat` afterward.
- `/chat` still reads `refreshingCore` from the legacy bridge only to display a background refresh hint.
- The current research context persists `lastSessionId` and `lastTraceId`, but it does not explicitly distinguish “restored payload” from “general persisted fallback.”

### Assumptions
- It is acceptable to keep the restore API call surface on legacy callers for now, as long as `/chat` itself consumes restore payloads through workspace + research context rules.
- A one-time restore payload can be consumed and cleared from research context without harming normal persisted session fallback behavior.

### Risks
- If restore payload and persisted fallback remain conflated, `/chat` can reopen a stale restored session or show the wrong banner after unrelated navigation.
- If targeted chat freshness is not surfaced to the page, removing `refreshingCore` could hide useful feedback during reconcile.
- If workspace logic starts retaining risk/task/approval render state during restore, it would break the current domain ownership split.

### /chat Restore Priority And Freshness Ownership
- Session selection priority after this group:
  - `URL session_id`
  - restored session payload from research context
  - persisted `lastSessionId`
  - first session returned by `/chat/sessions`
- Restored trace banner priority after this group:
  - `URL restored_trace_id`
  - restored trace payload from research context
  - no banner
- Freshness ownership after this group:
  - `ChatWorkspaceProvider` owns chat-targeted reconcile for session list and active-session turns
  - legacy `WorkbenchProvider` still owns global SSE lifecycle and non-chat omnibus refresh

### Approach
1. Split restore payload from general persisted fallback in research context.
2. Make `ChatWorkspaceProvider` resolve initial `/chat` session/restore context using an explicit priority helper.
3. Replace `/chat`’s background refresh indicator with workspace-owned targeted freshness state.
4. Remove restore-time `refreshCore` from the legacy restore path when `/chat` can self-reconcile.
5. Build and document the remaining legacy-backed `/chat` paths.

### Verification
- [ ] unit tests
- [ ] integration tests
- [ ] e2e / scenario tests
- [ ] lint / type checks
- [ ] manual UX review
- [ ] performance check
- [ ] risk review

### Done When
- `/chat` initializes session selection using an explicit URL / restore-payload / persisted-fallback priority.
- `/chat` no longer depends on legacy `refreshingCore` for chat-specific refresh feedback.
- restore navigation into `/chat` no longer needs legacy `refreshCore` to hydrate chat state.
- The app still builds successfully.

### Post-Change Notes
- This group must not migrate `/pipeline`.
- This group must not switch the global SSE connection owner.
- This group must not remove `workbench-provider.tsx`.
