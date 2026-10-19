"""User settings (~/.kerf/settings.json). Environment variables override the file.

API keys live only on this machine; the server never returns them unmasked.
"""
from __future__ import annotations

import json
import os

from . import media

FILE = media.HOME / "settings.json"
DEFAULTS = dict(
    ai_provider="claude",              # claude | openai | gemini | local
    claude_model="claude-opus-5-5",
    openai_model="gpt-5",              # any OpenAI / Codex model id
    gemini_model="gemini-2.5-pro",
    local_llm_url="",                  # OpenAI-compatible, e.g. http://localhost:11434/v1 (Ollama)
    local_llm_model="llama3.1",
    whisper_model="auto",              # auto = large-v3-turbo on GPU, small on CPU; or any faster-whisper id / fine-tuned folder
    whisper_device="auto",
    anthropic_api_key="", openai_api_key="", gemini_api_key="", elevenlabs_api_key="", pexels_api_key="",
    theme="auto",
)
ENV = dict(anthropic_api_key="ANTHROPIC_API_KEY", openai_api_key="OPENAI_API_KEY", gemini_api_key="GEMINI_API_KEY",
           elevenlabs_api_key="ELEVENLABS_API_KEY", pexels_api_key="PEXELS_API_KEY", local_llm_url="KERF_LLM_URL",
           local_llm_model="KERF_LLM_MODEL", whisper_model="KERF_WHISPER_MODEL")
SECRET = {k for k in DEFAULTS if k.endswith("_api_key")}


def load():
    s = dict(DEFAULTS)
    if FILE.exists():
        s.update({k: v for k, v in json.loads(FILE.read_text("utf-8")).items() if k in DEFAULTS})
    for k, env in ENV.items():
        if os.environ.get(env):
            s[k] = os.environ[env]
    return s


def get(key):
    return load()[key]


def save(changes):
    cur = json.loads(FILE.read_text("utf-8")) if FILE.exists() else {}
    for k, v in changes.items():
        if k in DEFAULTS and not (k in SECRET and str(v).startswith("••")):  # masked value = unchanged
            cur[k] = v
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(cur, indent=1), "utf-8")


def public():
    return {k: (("••••" + v[-4:]) if k in SECRET and v else v) for k, v in load().items()}
