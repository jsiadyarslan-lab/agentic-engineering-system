# AES Chat Factory — G0/G2 Audit Ledger
Review workstream JAB-92 · 2026-11-17

## Sources inspected
- Oracle live web page `http://92.5.14.150/#/p/4` via Browser tab context, read-only, Nov 17.
- GitHub AES repository `jsiadyarslan-lab/agentic-engineering-system` `main@9d77a79e71902411371decef2dd68499068246ee`: `src/ui/index.html`, `src/api/routes.py`, `src/api/projects.py`, `src/persistence/conversations.py`, `src/api/streaming.py`, `tests/api`.
- PR #7, PR #8 still draft/unmerged; do not confuse either with new PR #9.

## Production page observations (not a backend functional test)
- Project #4 objective: Arabic multi-page news site, 12 articles/categories/search.
- State PAUSED; 7/14 steps; 9 execution records; 324 artifact records; 0 open owner gates in displayed summary.
- Event wall includes `JOB_INTERRUPTED` (no heartbeat after 311 seconds), `JOB_PAUSED`, `EVIDENCE_CREATED`, `EXECUTION_COMPLETED`.
- Old step #1047 `build.js` FAILED, newer step #1052 with similar objective COMPLETED; likely different executions/plan revisions. UI does not distinguish attempts properly.
- Verification steps still show NOT STARTED and no delivered working site verified in the inspected view.
- Finding: UI G0 **FAIL** as an owner factory console; engine status remains **NOT DETERMINED** from read-only page alone.

## Real API inventory
| Operation | Endpoint | Review status |
|---|---|---|
| projects | `GET/POST /api/projects` | CONTRACT PRESENT (source) |
| snapshot | `GET /api/projects/{id}/state` | CONTRACT PRESENT |
| steps | `GET /api/projects/{id}/steps` | CONTRACT PRESENT |
| plan | `POST /api/projects/{id}/plan/generate` | CONTRACT PRESENT |
| owner approve | `POST /api/projects/{id}/plan/approve` | CONTRACT PRESENT, auto-launch |
| pause, resume, preflight | `POST /api/projects/{id}/{pause,resume,preflight}` | CONTRACT PRESENT, resume/preflight may launch |
| gate | `POST /api/projects/{id}/gates/{gid}` | CONTRACT PRESENT |
| artifacts | `GET /api/projects/{id}/artifacts` | CONTRACT PRESENT |
| file preview | `GET /api/projects/{id}/artifacts/content` | CONTRACT PRESENT, text <=256KB |
| chats | `GET /api/conversations` + `GET /api/conversations/{id}/messages` | CONTRACT PRESENT |
| model SSE | `POST /api/chat/stream` | CONTRACT PRESENT; new optional scoped project_id in PR #9 |
| reconnect | `GET /api/chat/active`, `GET /api/chat/events/{id}` | CONTRACT PRESENT |
| provider tools | `GET /api/providers` | CONTRACT PRESENT |
| host readiness | `GET /api/environment/readiness` | CONTRACT PRESENT |
| generic embedded browser | none | UNSUPPORTED — must not fake |
| binary delivery endpoint | none in examined contract | UNVERIFIED — text preview does not certify binary |

## Defects / protections under test
- P0 scope leakage on **first** SSE event if chat is linked to project after its creation; PR #9 changes route contract so binding occurs before append/broadcast. Tests reject cross-project sends (409) and unknown project (404).
- P0 log wall crowding active objective; new conversation stage places latest project status first and history collapsed.
- P1 false success if plan approval succeeds but launch fails; new client separates `launch.launched` from decision accepted.
- P1 unsafe double-post after dropped HTTP; new client does not automatically replay mutations.
- P1 JSON file preview accidentally treated as structured JSON; corrected to text.
- P1 historical event leakage on SSE replay; scope event checks and current message_id filter in new client.
- P1 browser/settings: declared as limited, not disguised as fully provisioned integrations.

## Status and required checks
| Check | State | Evidence |
|---|---|---|
| G0 server-side route/source audit | PASS (source only) | endpoints mapped above |
| G0 project #4 page read | PASS (read-only) | snapshot in program JAB-88 |
| G1 visual layout (1366/390) | NOT RUN | browser automation unavailable here |
| G2 SSE scoped contract test | CI PENDING | `tests/api/test_chat_factory_live.py` |
| G2 JS syntax | PASS (new Function parse) | GitHub staged source |
| G2 trusted full suite | CI PENDING | PR #9 |
| G3 actual OCI `/workspace` | NOT DEPLOYED | no approved shell write channel |
| G3 rollback verification | NOT RUN | keep existing root untouched |
| G3 cleanup `aes-v3-publish-1115203153` | **PENDING / SECURITY** | policy was created previously; no proof deleted |

Do not set release PASS until OCI serves this exact UI and a reviewer tests the live #4 read-only and a new disposable project transactionally.
