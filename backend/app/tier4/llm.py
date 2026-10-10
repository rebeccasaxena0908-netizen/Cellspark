"""
Tier 4 — LLM provider layer.

One job: turn a system prompt and a user prompt into text, or return None.

WHY IT NEVER RAISES:
The copilot has a working non-LLM path — answers composed from the run's own
numbers (copilot._compose). That path is the fallback, not an error state. So
every way generation can fail here — no API key, provider switched off, a
retired model name, a timeout, a network drop, an empty response — resolves to
None, and the caller quietly composes from templates instead. A clinician
asking about a run gets a grounded answer either way; what they must never get
is a 500.

Configuration is environment-only:
  CELLSPARK_LLM   "gemini" | "off"   (default "off")
  GEMINI_API_KEY  the key
  GEMINI_MODEL    model id           (default below)

The default model is the only model name in this codebase. Nothing else
hardcodes one.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash-lite"
TEMPERATURE = 0.2
TIMEOUT_SECONDS = 20

# Configuration problems repeat identically on every single request — "no API
# key" would be logged once per question asked. Operational failures (a
# timeout, a network error) are distinct events and are logged every time.
_warned: set = set()


def _warn_once(reason: str) -> None:
    if reason not in _warned:
        _warned.add(reason)
        logger.warning("LLM generation unavailable: %s", reason)


def _redact(text: str) -> str:
    """
    Strip the API key from anything on its way to a log.

    Provider errors sometimes echo the request, and a key in a log file is a
    leaked key. Belt and braces: nothing from this module reaches a log
    without passing through here.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    out = str(text)
    if key and len(key) > 6:
        out = out.replace(key, "***REDACTED***")
    return out


def provider_name() -> str:
    """Which provider is configured, for reporting in the API response."""
    return (os.environ.get("CELLSPARK_LLM") or "off").strip().lower()


def model_name() -> str:
    """The configured model id — what the response reports as its provider."""
    return (os.environ.get("GEMINI_MODEL") or "").strip() or DEFAULT_MODEL


def is_enabled() -> bool:
    """True when a generation attempt could plausibly succeed."""
    return provider_name() == "gemini" and bool(
        (os.environ.get("GEMINI_API_KEY") or "").strip()
    )


def _load_env_file() -> None:
    """
    Pull backend/.env into the environment if python-dotenv is installed.

    Does NOT override variables that are already set, so an explicit
    CELLSPARK_LLM=off on the command line still wins over the file. Absent
    dotenv or absent file, this is a no-op and configuration comes from the
    real environment.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        load_dotenv(env_path, override=False)
    except Exception:
        pass


_load_env_file()


def generate(system_prompt: str, user_prompt: str) -> Optional[str]:
    """
    Generate an answer, or return None if generation is unavailable.

    Never raises. Every failure path returns None and logs a redacted reason.
    """
    provider = provider_name()

    if provider in ("", "off"):
        _warn_once("CELLSPARK_LLM is off (set CELLSPARK_LLM=gemini to enable)")
        return None

    if provider != "gemini":
        _warn_once(f"unknown provider {provider!r} (expected 'gemini' or 'off')")
        return None

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        _warn_once("GEMINI_API_KEY is not set")
        return None

    model = model_name()

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception as e:
        _warn_once(f"langchain-google-genai not importable: {_redact(e)}")
        return None

    try:
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=TEMPERATURE,
            timeout=TIMEOUT_SECONDS,
            # One attempt. A retry storm behind a 20s timeout would hold the
            # request open far longer than a user will wait, and the template
            # fallback is right there.
            max_retries=0,
        )
    except Exception as e:
        # Bad model name, bad credentials shape, incompatible library version.
        logger.warning("LLM init failed (model=%s): %s", model, _redact(e))
        return None

    try:
        reply = llm.invoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
    except Exception as e:
        # Timeout, network error, rate limit, model not found, safety block.
        logger.warning(
            "LLM call failed (model=%s): %s: %s",
            model, type(e).__name__, _redact(e),
        )
        return None

    text = getattr(reply, "content", None)

    # Some providers return content as a list of parts rather than a string.
    if isinstance(text, list):
        parts = [
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in text
        ]
        text = "".join(parts)

    if not isinstance(text, str) or not text.strip():
        logger.warning("LLM returned an empty response (model=%s)", model)
        return None

    return text.strip()
