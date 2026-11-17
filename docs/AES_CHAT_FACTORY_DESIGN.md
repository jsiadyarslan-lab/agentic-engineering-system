# AES Chat Factory — G1 UX/Design Contract
Owner mandate: 2026-11-17 · Program JAB-91 · Design workstream JAB-93

## Purpose
The platform is an engineering factory, not a messaging clone. Reuse ChatGPT's **interaction grammar** (conversation-first, persistent history, composable workspace, inline outputs and contextual drawers), never its marks/identity. All operational claims must be anchored in AES API records.

## Navigation architecture
| Area | Entry | Primary entity | Truth contract |
|---|---|---|---|
| Home | `#/ ` | saved projects and conversations | GET /api/projects + /api/conversations |
| Project | `#/p/{id}` | current project snapshot | GET /api/projects/{id}/state |
| Project chat | `#/p/{id}/c/{cid}` | saved messages + live SSE | project_id validated before first event; no cross-project writes |
| Global chat | `#/c/{cid}` | saved standalone messages | no invented project context |
| Runs | inspector tab | plan, stage steps, current status | GET /state + GET /steps; explicit POST operations |
| Outputs | inspector tab | evidence-backed file list | GET /artifacts + /artifacts/content; 256KB text preview only |
| Decisions | inspector tab | gates + plan owner approval | approval automatically launches project; explicit warning |
| Browser | inspector tab | live evolution browser link | no claim of an embedded controllable browser; no fictitious screenshot |
| Tools | inspector tab | registered providers | GET /api/providers; do not show API keys |
| Settings | inspector tab | theme + host readiness | GET /api/environment/readiness; advanced settings remain on legacy UI |

## Layout rules
- RTL root and natural direction per message (`dir=auto`). Monospace evidence labels preserve LTR.
- Desktop: 260px right sidebar; flexible middle thread max 820px; optional 375px left inspector. Dense diagnostics hidden behind an explicit summary.
- Mobile: 390px target; drawer for sidebar and full-screen inspector; composer anchored to visible viewport with safe-area inset.
- Typography from locally served IBM Plex Sans Arabic; no external font or analytics.
- Palette grayscale (dark by default, light optional). States distinguished by **text, shape and icon** in addition to contrast, not saturated green.
- Focus-visible on buttons and links; headings in logical order; real labels for inputs.

## End-to-end owner journey
1. Home asks "ماذا تريد أن تنجز اليوم؟" rather than dumping runtime logs.
2. "اسأل" opens a persisted model conversation; sending does **not** execute workflow actions.
3. "أنشئ مشروعًا" opens a project creation form; POST creates DRAFT only.
4. Review real plan and decide explicitly. A successful `/plan/approve` response may launch a job; a failed launch remains visibly blocked.
5. Project card says PAUSED/BLOCKED/RUNNING/VERIFIED with a reason from `execution_gate`; the history is folded by default.
6. File preview comes from materialized evidence. A file's presence or an `EXECUTION_COMPLETED` event is not proof the whole project passed.
7. Owner can inspect gate evidence and approve/reject in the same context. These actions request confirmation before POST.

## Anti-deception requirements
- No demo JSON, fake model stream, inferred provider status, fake ZIP, or success badge before server acknowledgment.
- No archived events redrawn as current chat response. SSE routed through conversation_id, message_id and project_id.
- Network failures do not erase saved history or silently repeat a mutating POST. On disconnect, users are warned to inspect server state.
- No browser automation claim unless a real authorized browser session API exists.
- No secret persisted in localStorage (only `aes:chat:theme`).
- No production merge/deploy claim without proof of the served bytes at Oracle.

## Known remaining design work
- Full visual Playwright screenshots at 1366px desktop and 390px mobile.
- Full keyboard walk-through, focus management and screen-reader labels on modal.
- Browser research as an authenticated, isolated product subsystem; current link to `/evolution` is only an existing specialized browser.
- Settings for model selection/connector installation need their own API contract; current panel is honest read-only overview.
- Binary artifact download and verified deployment package are not provided by the current 256KB text-preview endpoint.

## Review gate
G1 is **PENDING VISUAL REVIEW** until screenshots and actual interaction checks are recorded. Source-only CSS and static contract tests are not visual acceptance.
