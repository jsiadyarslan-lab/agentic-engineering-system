# AES-CHAT-WORKSPACE-001 — Independent source and owner-journey audit

Date: 2026-11-17 · Repository: `jsiadyarslan-lab/agentic-engineering-system` · Baseline: `main@9d77a79e71902411371decef2dd68499068246ee`
Scope: AES Factory only. Evidence: live owner browser tab `http://92.5.14.150/#/p/4` (read-only text view), `src/api/routes.py`, `src/api/projects.py`, `src/ui/index.html`, `src/ui/app.js`, and PR #8 source. No live mutations were performed during audit.

## What the owner can actually see
- Project #4 is `PAUSED`, shows `7/14` steps complete, `9` executions, `324` repository files, `0` open gates.
- Long activity wall leads with `JOB_PAUSED`, `CHECKPOINT_CREATED`, `STEP_COMPLETED`, `TOOL_EXECUTION`, `JOB_INTERRUPTED`, and others; messages from one day ago dominate first screen.
- `JOB_INTERRUPTED` explicitly reports 311 seconds without heartbeat against a 300-second threshold. `JOB_PAUSED` is a separate state.
- Step #1047 `Create build.js` is marked FAILED, while later #1052 `Create build.js` is marked completed. This is **not** proven data inconsistency: newer steps belong to a later attempt/plan; UI must visually associate each step with its run and plan.
- `verify.js` verification steps (#1048, #1056, #1057) are NOT STARTED in the visible list. Neither a `TEST_COMPLETED` event nor 324 files establishes a final verified deliverable.
- The owner cannot identify a currently approved build or open the final news site from the captured view.

## API verified from repository source
- `GET /api/projects` lists projects.
- `GET /api/projects/{id}/state` returns project, plan, phases, gates, executions, evidence, events, owner action; a single initial snapshot is available.
- `GET /api/projects/{id}/artifacts` returns evidence-backed files only. `GET /api/projects/{id}/artifacts/content?step_id=&name=` previews text (256KB max) with server path safeguards.
- `GET /api/projects/{id}/conversations` lists persistent project conversations. `GET /api/conversations/{id}/messages` loads their saved messages.
- `POST /api/chat/stream` emits `conversation.bind`, `message_delta`, `message_completed`, and `chat.error` as SSE with conversation scope. `POST /api/conversations/{id}/move-to-project` assigns the conversation to a project.
- Project plan, gate, resume, pause, stop and verify APIs exist and have real side effects. A chat question must never call them implicitly.
- The API does **not** establish a full remote browser session or connector/plugin registry for the new UI; mark such spaces NOT CONNECTED.

## Failures and severity
| ID | Severity | Finding | Requirement |
|---|---|---|---|
| A1 | P0 | Event wall displaces current decision and output | Chat first; latest run/status beside it |
| A2 | P0 | Historical and current step outcomes are visually mixed | Link each step to attempt/plan and mark current vs history |
| A3 | P0 | File count is mistaken for a delivered product | Evidence-backed output preview; separate VERIFIED state |
| A4 | P0 | SSE response was not shown progressively in staged V3 | Render real `message_delta` chunks, preserve partial on error |
| A5 | P1 | Project conversation list was not in global navigation | Add per-project conversation rail and deep links |
| A6 | P1 | Main project entry opened status dashboard | Project link goes directly to chat |
| A7 | P1 | UI needs empty/error/slow-loading states | Scope errors locally; show status truthfully |
| A8 | P1 | Settings/plugins/browser not wired | Use explicit unsupported / existing console links |
| A9 | P0 security | Older temporary OCI IAM group/policy may still exist | Verify and remove separately; do not touch ECP |
| A10 | P0 deploy | No verified OCI preview deployment or recovery snapshot | Do not overwrite root index before live approval |

## Acceptance gates
- [x] Real backend API routes identified from source.
- [x] Actual owner page inspected with project/steps/events.
- [x] Chat-first source code staged in PR #8.
- [x] Isolated JavaScript syntax check passed in tool runtime.
- [ ] Full CI PASS at staged commit (pending as of initial issue).
- [ ] Native browser desktop/mobile functional acceptance with live backend.
- [ ] True streamed chat response on Oracle measured.
- [ ] Live project #4 artifact preview, run evidence and no false VERIFIED.
- [ ] Verified rollback manifest + OCI preview deployment.
- [ ] Temporary IAM permission confirmed removed.

**Verdict: current live UI FAIL for operator UX; this does not prove backend FAIL. PR #8 is not a deployment.**
