"""All Gemini access lives here. The API key is read from the environment only.

Model policy: output quality first.
  1. Full Flash models, best first (free tier: about 5 RPM, 20 requests/day each).
  2. Flash-Lite models only after every Flash model failed (free tier: 500/day each).
GEMINI_MODEL (comma-separated) overrides the whole order if set.

Per model:
  - Daily quota used up (429, PerDay quota)    -> next model.
  - Per-minute limit (429, not daily)           -> wait once (up to 60s) and retry the same model.
  - Busy / server error (408, 5xx), timeout     -> next model.
  - Model not found (404)                       -> next model, and skip it until the instance restarts.
  - Any other error (bad key, bad request)      -> stop and report.
The whole call never runs longer than DEADLINE seconds (Vercel Hobby limit is 300s).
Every switch or wait is returned in "notes" so the UI can show it.
"""
import os
import time

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"
FLASH_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview"]
LITE_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

DEADLINE = 280.0        # total budget for one call, under Vercel's 300s maxDuration
FIRST_TIMEOUT = 170.0   # max wait for a model that still has a fallback after it
MIN_LEFT = 5.0          # do not start an attempt with less time than this
MINUTE_WAIT_MAX = 60    # longest wait for a per-minute limit before moving on
BUSY = {408, 500, 502, 503, 504}

_gone = set()  # models that returned 404; skipped until the instance restarts


class GeminiError(Exception):
    def __init__(self, kind, message, status=502, retry_after=None, notes=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.notes = notes or []


def _models():
    env = [m.strip() for m in os.environ.get("GEMINI_MODEL", "").split(",") if m.strip()]
    seen, out = set(), []
    for m in env or (FLASH_MODELS + LITE_MODELS):
        if m not in seen and m not in _gone:
            seen.add(m)
            out.append(m)
    return out


def _scrub(text, key):
    text = str(text)
    return text.replace(key, "***") if key else text


def _retry_delay(resp, data):
    try:
        ra = resp.headers.get("retry-after")
        if ra:
            return max(1, min(300, int(float(ra))))
        for d in (data.get("error") or {}).get("details") or []:
            if str(d.get("@type", "")).endswith("RetryInfo"):
                return max(1, min(300, int(float(str(d.get("retryDelay", "30s")).rstrip("s")))))
    except Exception:
        pass
    return 30


def _is_daily(data):
    err = data.get("error") or {}
    for d in err.get("details") or []:
        if str(d.get("@type", "")).endswith("QuotaFailure"):
            for v in d.get("violations") or []:
                if "perday" in str(v.get("quotaId", "")).lower():
                    return True
    msg = str(err.get("message", "")).lower()
    return "per day" in msg or "perday" in msg


def _extract(data):
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise GeminiError("gemini_error", "Gemini returned no answer" + (f" (blocked: {reason})" if reason else "") + ".")
    c = cands[0]
    parts = (c.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text, c.get("finishReason") == "MAX_TOKENS"


def generate(prompt, json_mode=False, max_tokens=8192):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError("missing_key", "GEMINI_API_KEY is not set on the server.", status=500)

    config = {"maxOutputTokens": max_tokens, "temperature": 0.7}
    if json_mode:
        config["responseMimeType"] = "application/json"
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}

    models = _models()
    if not models:
        raise GeminiError("gemini_error", "No Gemini model is available (all returned 404).")

    start = time.monotonic()
    notes, last, rate_delays, waited = [], None, [], set()
    i = 0
    while i < len(models):
        model = models[i]
        remaining = DEADLINE - (time.monotonic() - start)
        if remaining < MIN_LEFT:
            break
        is_last = i == len(models) - 1
        slice_ = remaining if is_last else min(FIRST_TIMEOUT, remaining)
        try:
            resp = httpx.post(
                f"{BASE}/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body,
                timeout=httpx.Timeout(slice_, connect=10.0),
            )
        except httpx.TimeoutException:
            notes.append({"model": model, "reason": "timeout"})
            last = GeminiError("timeout", f"{model} did not answer within {int(slice_)}s.", status=504)
            i += 1
            continue
        except httpx.HTTPError as e:
            notes.append({"model": model, "reason": "network"})
            last = GeminiError("gemini_error", f"{model}: network error: {_scrub(e, key)}")
            i += 1
            continue

        try:
            data = resp.json()
        except ValueError:
            data = {}
        err = data.get("error") or {}

        if resp.status_code == 429 or err.get("status") == "RESOURCE_EXHAUSTED":
            delay = _retry_delay(resp, data)
            if _is_daily(data):
                notes.append({"model": model, "reason": "quota_daily"})
                last = GeminiError("quota_daily", f"{model}: daily quota used up.", status=429)
            else:
                left = DEADLINE - (time.monotonic() - start)
                if model not in waited and delay <= MINUTE_WAIT_MAX and left - delay > MIN_LEFT + 10:
                    waited.add(model)
                    notes.append({"model": model, "reason": "rate_minute", "wait": delay})
                    time.sleep(delay)
                    continue  # retry the same model once
                notes.append({"model": model, "reason": "rate_minute"})
                rate_delays.append(delay)
                last = GeminiError("rate_limited", f"{model}: per-minute limit reached.", status=429)
            i += 1
            continue
        if resp.status_code == 404:
            _gone.add(model)
            notes.append({"model": model, "reason": "model_gone"})
            last = GeminiError("gemini_error", f"{model}: not found (404).")
            i += 1
            continue
        if resp.status_code in BUSY:
            notes.append({"model": model, "reason": "busy", "status": resp.status_code})
            last = GeminiError("busy", f"{model}: HTTP {resp.status_code} {_scrub(err.get('message', ''), key)}", status=503)
            i += 1
            continue
        if resp.status_code >= 400:
            raise GeminiError("gemini_error", f"{model}: HTTP {resp.status_code} {_scrub(err.get('message', resp.text[:300]), key)}", notes=notes)

        text, truncated = _extract(data)
        return {"text": text, "model": model, "truncated": truncated, "notes": notes}

    reasons = {n["reason"] for n in notes}
    if reasons == {"quota_daily"} or reasons == {"quota_daily", "model_gone"}:
        raise GeminiError("quota_daily", "The daily Gemini quota of every model is used up. It resets at midnight Pacific time.",
                          status=429, notes=notes)
    if rate_delays and reasons <= {"quota_daily", "rate_minute", "model_gone"}:
        raise GeminiError("rate_limited", "Gemini is rate-limited right now. Try again shortly.",
                          status=429, retry_after=min(rate_delays), notes=notes)
    if last is None:
        last = GeminiError("timeout", "Ran out of time before any Gemini model answered.", status=504)
    last.notes = notes
    raise last


if __name__ == "__main__":
    # Helper: list models this key can use for generateContent.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    k = os.environ.get("GEMINI_API_KEY", "")
    r = httpx.get(f"{BASE}/models", headers={"x-goog-api-key": k}, params={"pageSize": 1000}, timeout=20)
    if r.status_code != 200:
        print("HTTP", r.status_code, _scrub(r.text[:300], k))
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(m["name"].removeprefix("models/"), m.get("outputTokenLimit"))
