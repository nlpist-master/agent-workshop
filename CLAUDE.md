# CLAUDE.md – Agent Workshop

App that builds apps with 4 AI agents (Planner, Builder, Tester, Polisher) and human approval at every stage.
Originally a Claude Artifact; now a standalone app on Gemini, deployed on Vercel.

- Live: https://agent-workshop-blue.vercel.app
- Repo: https://github.com/nlpist-master/agent-workshop (public, Vercel auto-deploys every push to `main`)
- Plan, history and ideas: [ROADMAP.md](ROADMAP.md) – read it first, and add new ideas there.

## Working rules (from Yosef, the owner)

- Write to the user in Hebrew. Every line and bullet starts with a Hebrew word; English terms only mid-sentence or in code blocks.
- Free solutions only. No billing on Google Cloud or any other service.
- Never delete files, push, or create a repo without asking.
- Briefly explain the reasoning behind every recommendation.
- Stop at the end of every stage and wait for approval.
- Output quality beats speed (it is a code-writing app): prefer the strongest Flash model; Flash-Lite only as a last resort or when the user picks "fast".
- UX: light, not overloaded with details, but gives the user freedom of action.
- Never enter API keys into services yourself (Vercel env vars etc.) – the user does it.
- Responsive: every change must work on desktop AND mobile (narrow ~375px). Reuse existing CSS classes.
- Every change follows this flow:
  1. **Propose**: explain the idea, and show that it does not break logic (existing flows, saved projects in `localStorage`) or design (layout, desktop and mobile). Wait for approval.
  2. **Implement** only after approval.
  3. **Verify**: run the affected flow end-to-end (prefer mocks/no-key setups to save Gemini quota), and compare desktop + mobile screenshots before/after so the design did not change unintentionally.
  4. Report, then stop for commit/push approval.

## Architecture

- `public/index.html` – the whole UI (vanilla HTML/CSS/JS, no build). Projects live in `localStorage` (`agentWorkshop:v1`). ZIP is built client-side.
- `api/index.py` – FastAPI:
  - `POST /api/agent` – one-shot call (Planner, Tester). `{agent, prompt}` → `{text, model, truncated, notes}`.
  - `POST /api/agent/stream` – NDJSON stream (Builder, Polisher). Events: `note`, `model`, `ping`, `text`, `end`, `error`.
  - `GET /api/health` → `{ok, key_set, access_required}`.
  - Access code: if env `APP_ACCESS_CODE` is set, both agent endpoints need header `X-Access-Code` (URL-encoded, so Hebrew works), else 401 `{"error":"access_code"}`. The browser asks once and keeps it in `localStorage` (`agentWorkshop:accessCode`). Unset = open (local dev). `.claude/launch.json` has `agent-workshop-code` (port 8020, code set, no Gemini key) to test it without using quota.
- `api/_gemini_client.py` – all Gemini access (REST via `httpx`). Key only from env `GEMINI_API_KEY`.
- `vercel.json` – `maxDuration: 300` (Hobby max), rewrite `/api/(.*)` → `/api/index`.

### Model policy

- Order: `gemini-3.8-flash` → `3.7` → `3.6` → `3.5` → `gemini-3-flash-preview` → `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`. Override with env `GEMINI_MODEL` (comma list).
- Busy skip: the browser remembers models that were busy / timed out / network-failed (10 min) or 404 (24 h) in `localStorage` (`agentWorkshop:modelSkip`) and sends them as `skip` in both endpoints; a model that answers is cleared. The server drops them from the order, unless that would leave no model. Logged as `⏭ Skipping …`.
- Daily quota (429 PerDay) → next model. Per-minute 429 → wait once (≤60s), retry same model. 404/5xx/timeout → next model. Other 4xx → stop.
- Do NOT add `gemini-2.5-flash`: deprecated, routes to 3.5-flash-lite from 2026-12-01.
- Free tier (AI Studio export 2026-11-11): Flash models ~5 RPM / 20 RPD each; Flash-Lite 15 RPM / 500 RPD. Quotas are per Google Cloud project. Pro models: 0 on free.

### Long outputs (Builder, Polisher)

- Agents write file blocks, not JSON: `=== SUMMARY ===`, `=== FILE: path ===` … `=== END FILE ===`, `=== NOTES ===` / `=== IMPROVEMENTS ===`, `=== DONE ===`.
- Server cuts itself off at `STREAM_DEADLINE` (230s). A model that sends nothing for `READ_TIMEOUT` (90s) counts as hung.
- Browser (`runFileAgent`) keeps every closed file block; if cut off, a continuation call sends the files already written and prefers the same model (`start_model`). Up to 5 rounds.
- Partial work: finished files are also kept in `projectState.draft` (`{agent, findings, files, summary, notes, improvements, model}`), saved with the project while streaming. Project files change only on success, which clears the draft. After a failure or page reload a card offers `Continue` (resumes via continuation) or `Discard`.
- Stop: `run()` creates an `AbortController` (`abortCtl`); both fetches pass its signal, and the busy box has `⏹ Stop`. Anything thrown after an abort is logged as "stopped by you" (no red error); partial files stay in the draft. Stop saves time, not quota (the request was already counted), and a one-shot call keeps running on the server until Gemini answers.
- Testing without quota: mock `window.fetch` for `/api/agent/stream` in the console (return a `ReadableStream` of NDJSON events) and use the `agent-workshop-code` launch config.

## Local development (Windows)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn api.index:app --reload
```

- `.env` holds `GEMINI_API_KEY` (gitignored; see `.env.example`).
- `python api/_gemini_client.py` lists the models the key can use.
- Testing continuation: env `STREAM_DEADLINE` (e.g. 90) forces a cut-off. `.claude/launch.json` has an `agent-workshop-shortcut` config for that (`.claude/` is gitignored).
- To save quota while testing the Builder, inject a short plan in the browser console (`addPlanVersion(...)`, then `approve()`) instead of calling the Planner.

## Known facts / gotchas

- Gemini 3.8 / 3.7 Flash are often overloaded (503), and sometimes take ~90s to answer 503. In practice many calls are answered by 3.6 Flash.
- Local preview may serve a cached `index.html` after edits: reload with `/?nocache=<n>` and check a new function exists before testing.
- Bash tool heredocs may mangle `\\n` in JS strings – prefer the Edit tool for JS string changes.
- Line endings: git warns LF→CRLF; harmless.
