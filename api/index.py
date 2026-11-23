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

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from _gemini_client import GeminiError, generate

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


@app.get("/api/health")
def health():
    return {"ok": True, "key_set": bool(os.environ.get("GEMINI_API_KEY"))}


@app.post("/api/agent")
def run_agent(req: AgentRequest):
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


# Local development only: serve the frontend from public/ (Vercel serves it itself).
_public = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if not os.environ.get("VERCEL") and os.path.isdir(_public):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_public, html=True), name="public")
