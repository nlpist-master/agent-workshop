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

## Architecture

- `public/index.html` – the whole UI (vanilla HTML/CSS/JS, no build). Projects live in `localStorage` (`agentWorkshop:v1`). ZIP is built client-side.
- `api/index.py` – FastAPI:
  - `POST /api/agent` – one-shot call (Planner, Tester). `{agent, prompt}` → `{text, model, truncated, notes}`.
  - `POST /api/agent/stream` – NDJSON stream (Builder, Polisher). Events: `note`, `model`, `ping`, `text`, `end`, `error`.
  - `GET /api/health`.
- `api/_gemini_client.py` – all Gemini access (REST via `httpx`). Key only from env `GEMINI_API_KEY`.
- `vercel.json` – `maxDuration: 300` (Hobby max), rewrite `/api/(.*)` → `/api/index`.

### Model policy

- Order: `gemini-3.8-flash` → `3.7` → `3.6` → `3.5` → `gemini-3-flash-preview` → `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`. Override with env `GEMINI_MODEL` (comma list).
- Daily quota (429 PerDay) → next model. Per-minute 429 → wait once (≤60s), retry same model. 404/5xx/timeout → next model. Other 4xx → stop.
- Do NOT add `gemini-2.5-flash`: deprecated, routes to 3.5-flash-lite from 2026-12-01.
- Free tier (AI Studio export 2026-11-11): Flash models ~5 RPM / 20 RPD each; Flash-Lite 15 RPM / 500 RPD. Quotas are per Google Cloud project. Pro models: 0 on free.

### Long outputs (Builder, Polisher)

- Agents write file blocks, not JSON: `=== SUMMARY ===`, `=== FILE: path ===` … `=== END FILE ===`, `=== NOTES ===` / `=== IMPROVEMENTS ===`, `=== DONE ===`.
- Server cuts itself off at `STREAM_DEADLINE` (230s). A model that sends nothing for `READ_TIMEOUT` (90s) counts as hung.
- Browser (`runFileAgent`) keeps every closed file block; if cut off, a continuation call sends the files already written and prefers the same model (`start_model`). Up to 5 rounds.

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
- Bash tool heredocs may mangle `\\n` in JS strings – prefer the Edit tool for JS string changes.
- Line endings: git warns LF→CRLF; harmless.
