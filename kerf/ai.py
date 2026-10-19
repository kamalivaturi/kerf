"""Prompt editing: Claude / OpenAI (Codex) / Gemini / local LLM turns an instruction into a chain of
Kerf features, then Kerf runs the chain. Also `pipeline`: user-defined chains (macros) with no AI.
"""
from __future__ import annotations

import json

from . import license, llm

PROMPT_DEFAULTS = dict(prompt="", provider="", model="", plan_only=False, items="")
PROMPT_CHOICES = dict(provider=["", *llm.PROVIDERS])
PROMPT_HELP = ("Describe the edit, e.g. 'tighten the pacing, add bold yellow captions and make a 9:16 version'. "
               "provider/model empty = your AI settings. plan_only shows the plan without editing.")
PIPELINE_DEFAULTS = dict(steps='[{"feature": "silences", "params": {"preset": "paced"}}, {"feature": "zoom"}]')
PIPELINE_HELP = "Run several features in a row (JSON list of {feature, params}). Save it as a preset to reuse."
META = {"prompt_edit", "pipeline"}

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "steps"],
    "properties": {
        "summary": {"type": "string"},
        "steps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["feature", "reason", "params"],
            "properties": {
                "feature": {"type": "string"},
                "reason": {"type": "string"},
                "params": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["key", "value"],
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}}}},
            }}},
    },
}
SYSTEM = ("You are the planning engine of Kerf, a video-editing plugin. Turn the editor's request into an ordered "
          "list of Kerf feature calls. Use only the features and parameter keys listed; omit parameters you don't "
          "need to change (defaults apply). Never set 'preview' or 'items'. Order matters: enhance first, then "
          "cutting features (silences, repeat, profanity), then style (zoom, captions, broll), then resize/viral, "
          "and render last only if the editor asks for a finished file. If the request can't be done with these "
          "features, return no steps and say why in summary.")


def catalogue():
    from .features import REGISTRY
    out = []
    for n, f in REGISTRY.items():
        if n in META:
            continue
        params = {k: v for k, v in f.defaults.items() if k not in ("preview", "items")}
        ch = {k: v for k, v in f.choices.items() if k in params}
        out.append(f"- {n}: {f.title}. {f.help} defaults={json.dumps(params)} choices={json.dumps(ch)}")
    return "\n".join(out)


def clean_steps(raw):
    from .features import REGISTRY
    steps = []
    for s in raw:
        f = REGISTRY.get(s.get("feature"))
        if f is None or s["feature"] in META:
            raise ValueError(f"step uses unknown feature '{s.get('feature')}'")
        params = s.get("params") or {}
        if isinstance(params, list):  # planner format [{key, value}]
            params = {x["key"]: x["value"] for x in params}
        steps.append(dict(feature=s["feature"], reason=s.get("reason", ""),
                          params={k: v for k, v in params.items() if k in f.defaults and k not in ("preview", "items")}))
    return steps


def plan(prompt, tl, provider="", model=""):
    info = (f"Timeline '{tl.name}': {tl.duration:.1f}s, {tl.width}x{tl.height} @ {tl.fps:.2f}fps, "
            f"{len(tl.video)} video / {len(tl.audio)} audio tracks.")
    text = llm.complete(f"{info}\n\nAvailable features:\n{catalogue()}\n\nRequest: {prompt}",
                        system=SYSTEM, schema=PLAN_SCHEMA, provider=provider or None, model=model or None)
    data = llm.parse_json(text) or {}
    return data.get("summary", ""), clean_steps([s for s in data.get("steps", []) if s.get("feature") not in META])


def execute(tl, steps, ctx):
    """Run steps in order, feeding each produced timeline into the next. Collects side outputs."""
    from .features import REGISTRY, coerce
    cur, extra, files, texts, markers, log = tl, [], [], [], [], []
    for st in steps:
        f = REGISTRY[st["feature"]]
        license.check(f)
        res = f.run(cur, coerce(f.defaults, st.get("params", {})), ctx)
        if res.get("timeline") is not None:
            cur = res["timeline"]
        extra += res.get("timelines", [])
        files += res.get("files", [])
        if res.get("text"):
            texts.append(res["text"])
        markers += res.get("markers", [])
        log.append(dict(feature=st["feature"], report=res.get("report", {})))
    out = ([cur] if cur is not tl else []) + extra
    if cur is not tl:
        cur.name = f"{tl.name} - Kerf"
    return dict(timelines=out, files=files, text="\n\n".join(texts), markers=markers, report=dict(steps=log))


def prompt_edit(tl, p, ctx):
    if not p["prompt"].strip():
        raise ValueError("write what you want done in 'prompt'")
    summary, steps = plan(p["prompt"], tl, p["provider"], p["model"])
    items = [dict(id=i, label=f"{i + 1}. {s['feature']} {json.dumps(s['params'])} — {s['reason']}")
             for i, s in enumerate(steps)]
    if p["plan_only"] or not steps:
        return dict(report=dict(summary=summary, steps=len(steps)), items=items, plan=steps)
    from .speech import selected
    chosen = [steps[it["id"]] for it in selected(p, items)]
    res = execute(tl, chosen, ctx)
    res["report"]["summary"] = summary
    res["plan"] = chosen
    return res


def pipeline(tl, p, ctx):
    steps = json.loads(p["steps"]) if isinstance(p["steps"], str) else p["steps"]
    return execute(tl, clean_steps(steps), ctx)
