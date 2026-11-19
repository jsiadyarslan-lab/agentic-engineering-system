# AES-CHAT-WORKSPACE-002 — Conversation-first Factory UX specification

Version: source-stage 2026-11-17, built for AES project/API not a ChatGPT brand clone. Arabic `lang=ar dir=rtl` with isolated English code and filenames.

## Information architecture

```
Factory (left/right depends RTL)
├─ New project (objective-based DRAFT, no auto-run)
├─ Projects
│  ├─ Project #4 → Chat (default)
│  │   ├─ Conversations (persistent, searchable later)
│  │   ├─ Project overview (short and honest)
│  │   ├─ Execution (latest + history; no auto-resume)
│  │   ├─ Outputs (evidence-backed files and preview)
│  │   ├─ Owner decisions (real pending gates)
│  │   └─ References (NOT CONNECTED until API)
├─ Owner inbox (pending decisions)
├─ Tools & integrations (capabilities, not fake connectors)
└─ Settings (personal theme vs server owner settings)
```

## Layout contract
- **Primary**: Single conversation reading surface. Natural response from assistant rendered as streamed deltas, with source-true status. Composer anchored below, user questions kept separate from plan/run/approval buttons. No KPI wall above first message.
- **Secondary**: Project context pane shows objective, status, pending decisions, verified evidence count, and links to run/outputs; collapsed under chat on narrower layouts.
- **Navigation**: Sidebar has projects then scoped conversation threads. One click to any conversation; deep link `#/p/:id/chat/:conversationId` restores after refresh.
- **Execution**: Run identity and current attempt must lead. Historical steps never silently merged. Owner controls require direct confirmation and refresh of backend state.
- **Output**: File preview comes from `/artifacts/content`; show source evidence, step, digest, verdict; do not call files VERIFIED based on their existence.
- **Browser**: Until a remotely operable browser API is present, show NOT CONNECTED and a usable path to reference sources; do not embed untrusted external pages as an agent-controlled session.
- **Extensions**: Until capability registry is connected, show available/nonconnected status only; never say tool is installed based on a decorative card.
- **Settings**: Personal appearance local to UI; server provider keys/settings only through existing authenticated server setting endpoints and separate approvals.

## Text rules
- "محادثة جديدة" starts a **conversation**, not a production run.
- "إرسال" submits a message to a genuine configured model, does not start a project run.
- "التشغيل" opens job timeline/owner actions. "استئناف" is explicit, confirmed and backend-authorized.
- "المخرجات" means files evidenced by project attempts. "تم التحقق" is reserved for real verification.
- "الخادم متصل" means transport only; a paused project must visibly remain paused.
- Loading: "يتصل بالمزود…"; partial failures: "انقطع البث، قد يستمر العمل على الخادم"; no automatic retry that might double-send.
- Configuration missing: show original backend error. Never invent answers or source attributions.

## Screens, responsive rules
- Desktop >= 1000px: sidebar 220–260px; chat ~700–900px; context 250px.
- Tablet < 1000px: context moves under main thread.
- Mobile <= 600px: navigation drawer, chat max-width 100%, composer remains accessible; no horizontal overflow.
- Keyboard: labeled composer, focus states, Enter submission semantics documented; safe escape of response text as text, not HTML.

## User journey #4
1. Open `#/p/4/chat`, see objective and PAUSED in context.
2. Choose existing conversation or start one; SSE response appears incrementally; refresh uses stored conversation ID.
3. Click "التشغيل" to see latest job/step history; examine 311-second missing heartbeat warning.
4. Open "المخرجات"; preview evidence-backed build and files (NOT VERIFIED if final tests absent).
5. If action required, view "القرارات"; confirm it separately. Observe server response and refreshed state.
6. Owner receives actual verifiable artifact/preview or explicit NOT READY with remaining acceptance conditions.

## Design-quality gate
No homepage logs wall. No canned project response. No false success. No mixing ECP/DecisionTrace/JARVIS. No automatic production deployment from design acceptance.
