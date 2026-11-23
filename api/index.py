"""Agent Workshop backend: one endpoint that forwards an agent prompt to Gemini.

Local:  uvicorn api.index:app --reload   (serves public/ at /)
Vercel: api/index.py is the function; public/ is served as static files.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import hmac
import json
from urllib.parse import unquote

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from _gemini_client import GeminiError, generate, stream_generate

app = FastAPI(title="Agent Workshop")

# agent -> (JSON response mode, maxOutputTokens)
AGENTS = {
    "planner": (False, 16384),
    "builder": (True, 65536),
    "tester": (True, 16384),
    "polisher": (True, 65536),
}


class AgentRequest(BaseModel):
    agent: str
    prompt: str = Field(min_length=1, max_length=2_000_000)


def _access_code():
    """Shared access code (env APP_ACCESS_CODE). Not set = open access (local development)."""
    return os.environ.get("APP_ACCESS_CODE", "").strip()


def _denied(sent):
    """401 response if an access code is required and the one sent does not match, else None.
    The browser sends the code URL-encoded, so non-ASCII codes (e.g. Hebrew) work in a header."""
    code = _access_code()
    if not code:
        return None
    given = unquote(sent or "").strip()
    if given and hmac.compare_digest(given.encode(), code.encode()):
        return None
    return JSONResponse({"error": "access_code", "message": "Access code required." if not given else "Wrong access code."},
                        status_code=401)


@app.get("/api/health")
def health():
    return {"ok": True, "key_set": bool(os.environ.get("GEMINI_API_KEY")), "access_required": bool(_access_code())}


@app.post("/api/agent")
def run_agent(req: AgentRequest, x_access_code: str | None = Header(None)):
    if (denied := _denied(x_access_code)):
        return denied
    if req.agent not in AGENTS:
        return JSONResponse({"error": "bad_request", "message": f"Unknown agent: {req.agent}"}, status_code=400)
    json_mode, max_tokens = AGENTS[req.agent]
    try:
        return generate(req.prompt, json_mode=json_mode, max_tokens=max_tokens)
    except GeminiError as e:
        body = {"error": e.kind, "message": e.message, "notes": e.notes}
        if e.retry_after:
            body["retry_after_seconds"] = e.retry_after
        return JSONResponse(body, status_code=e.status)


class StreamRequest(BaseModel):
    agent: str
    prompt: str = Field(min_length=1, max_length=2_000_000)
    start_model: str | None = None


@app.post("/api/agent/stream")
def run_agent_stream(req: StreamRequest, x_access_code: str | None = Header(None)):
    """Long outputs (Builder, Polisher): NDJSON event stream, cut off by the server in time."""
    if (denied := _denied(x_access_code)):
        return denied
    if req.agent not in AGENTS:
        return JSONResponse({"error": "bad_request", "message": f"Unknown agent: {req.agent}"}, status_code=400)
    _, max_tokens = AGENTS[req.agent]

    def events():
        for ev in stream_generate(req.prompt, max_tokens=max_tokens, start_model=req.start_model):
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Local development only: serve the frontend from public/ (Vercel serves it itself).
_public = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if not os.environ.get("VERCEL") and os.path.isdir(_public):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_public, html=True), name="public")
