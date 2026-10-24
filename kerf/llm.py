"""Multi-provider LLM client: Claude (Anthropic SDK), OpenAI / Codex, Google Gemini, or a local
OpenAI-compatible server (Ollama, LM Studio, llama.cpp). Configure in the panel's AI settings
(~/.kerf/settings.json) or with env vars. Every caller has an offline heuristic fallback.
"""
from __future__ import annotations

import json
import re
import urllib.request

from . import settings

PROVIDERS = ["claude", "openai", "gemini", "local"]
# Models that accept Claude's server-side refusal fallback ("default" routing).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def _key(provider, s):
    return {"claude": s["anthropic_api_key"], "openai": s["openai_api_key"], "gemini": s["gemini_api_key"],
            "local": s["local_llm_url"]}[provider]


def available(provider=None):
    s = settings.load()
    return bool(_key(provider or s["ai_provider"], s))


def complete(prompt, system="You are a concise assistant for video editors.", schema=None, provider=None, model=None):
    """Return the model's text. With `schema` (JSON Schema), the text is JSON matching it."""
    s = settings.load()
    provider = provider or s["ai_provider"]
    if provider not in PROVIDERS:
        raise ValueError(f"unknown AI provider '{provider}' (use {', '.join(PROVIDERS)})")
    if not _key(provider, s):
        raise ValueError(f"No credentials for {provider}: add an API key (or local URL) in Kerf AI settings")
    model = model or s[{"claude": "claude_model", "openai": "openai_model", "gemini": "gemini_model",
                        "local": "local_llm_model"}[provider]]

    if provider == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=s["anthropic_api_key"])
        oc = {"effort": "medium"}
        if schema:
            oc["format"] = {"type": "json_schema", "schema": schema}
        extra = {}
        if model in _FALLBACK_MODELS:
            extra = dict(betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"})
        resp = client.beta.messages.create(model=model, max_tokens=16000, system=system, output_config=oc,
                                           messages=[{"role": "user", "content": prompt}], **extra)
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request")
        return "".join(b.text for b in resp.content if b.type == "text")

    if provider == "openai":
        from openai import OpenAI
        kw = dict(model=model, instructions=system, input=prompt)
        if schema:
            kw["text"] = {"format": {"type": "json_schema", "name": "kerf_output", "schema": schema, "strict": True}}
        return OpenAI(api_key=s["openai_api_key"]).responses.create(**kw).output_text

    if provider == "gemini":
        from google import genai
        from google.genai import types
        cfg = types.GenerateContentConfig(system_instruction=system,
                                          response_mime_type="application/json" if schema else None)
        if schema:
            prompt += "\n\nReturn JSON matching this JSON Schema:\n" + json.dumps(schema)
        return genai.Client(api_key=s["gemini_api_key"]).models.generate_content(
            model=model, contents=prompt, config=cfg).text

    body = dict(model=model, temperature=0.2, messages=[dict(role="system", content=system),
                                                         dict(role="user", content=prompt)])
    if schema:
        body["messages"][1]["content"] += "\n\nReply with JSON only, matching this JSON Schema:\n" + json.dumps(schema)
    req = urllib.request.Request(s["local_llm_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def parse_json(text):
    m = re.search(r"(\[.*\]|\{.*\})", text or "", re.S)
    return json.loads(m.group(1)) if m else None


def chat_json(prompt, schema=None):
    """Best-effort JSON helper for heuristic-with-AI-upgrade features. Returns None on any failure."""
    try:
        return parse_json(complete(prompt + "\nReply with JSON only.", schema=schema))
    except Exception:
        return None
