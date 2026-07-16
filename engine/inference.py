"""
Inference backend abstraction for the Observation Engine.

Routes structured, closed-domain generation to a local
Ollama model when available, falling back to the Anthropic API otherwise.
The system/user prompts and the JSON output contract are identical across
backends; callers parse the returned text exactly as before.

Routing is local-first by default and fails *open*: any error reaching or
generating with Ollama (including the `ollama` package not being installed)
falls back to the Anthropic API, so a stopped Ollama server never breaks a run.

An optional model-selector hook may be installed via ``set_model_selector(fn)``
to influence which local model is chosen per request. When no selector is
installed, the ``OLLAMA_MODEL`` environment variable (or its ``llama3.1:8b``
default) is used. The selector receives an optional work-hint string and should
return a model tag string or ``None``; any exception is caught and the default
model is used, so a faulty selector never breaks a run.

Env:
  OLLAMA_HOST       Ollama base URL   (default http://localhost:11434)
  OLLAMA_MODEL      Local model tag   (default llama3.1:8b)
  OBS_PREFER_LOCAL  "0"/"false" forces API-only (default local-first)
  ANTHROPIC_API_KEY required for the fallback backend
"""

import logging
import os

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
_AVAIL_TIMEOUT_S = 2.0

# ── Optional model-selector seam ──────────────────────────────────────────────
# Install a selector via set_model_selector(fn). The selector signature is
# Callable[[Optional[str]], Optional[str]]: takes a work_hint, returns a model
# tag string or None. When None is returned (or the selector is absent),
# _resolve_local_model falls back to the LOCAL_MODEL constant. Any exception
# from the selector is also caught and falls back to LOCAL_MODEL.
_local_model_selector = None


def set_model_selector(fn) -> None:
    """Install (or clear) the optional local-model selector.

    ``fn`` must accept one positional argument (the work_hint string or None)
    and return a model tag string or None. Pass ``None`` to clear any installed
    selector and revert to the LOCAL_MODEL constant.
    """
    global _local_model_selector
    _local_model_selector = fn


def _resolve_local_model(work_hint) -> str:
    """Return the local model tag to use for this request.

    If a selector is installed, calls it with ``work_hint``. A truthy return
    value is used as the model tag. On any exception or a falsy (None/empty)
    return, the ``LOCAL_MODEL`` constant is used — fail-open.
    """
    if _local_model_selector is None:
        return LOCAL_MODEL
    try:
        tag = _local_model_selector(work_hint)
        if tag:
            return tag
    except Exception as exc:
        logger.warning(
            "Model selector raised an exception (%s); using default %s.",
            exc, LOCAL_MODEL,
        )
    return LOCAL_MODEL


def prefer_local_default() -> bool:
    return os.environ.get("OBS_PREFER_LOCAL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _model_matches(resident_name: str, wanted: str) -> bool:
    """A resident tag matches if it equals the wanted tag or shares its base
    name, so `nomic-embed-text:latest` matches a wanted `nomic-embed-text`."""
    if resident_name == wanted:
        return True
    return resident_name.split(":")[0] == wanted.split(":")[0]


def _resident_model_id(m) -> str:
    """Extract a resident model's tag across ollama-python response shapes.
    ollama-python >= 0.4 returns `Model` objects whose tag is the `.model`
    attribute; older versions returned dicts keyed `name` (or `model`)."""
    val = getattr(m, "model", None)
    if val:
        return val
    if isinstance(m, dict):
        return m.get("name") or m.get("model") or ""
    return ""


def _list_resident_models(client) -> list:
    """Return resident model entries across ollama-python response shapes.
    `ListResponse` exposes `.models`; older dict responses use `["models"]`."""
    resp = client.list()
    models = getattr(resp, "models", None)
    if models is None and hasattr(resp, "get"):
        models = resp.get("models", [])
    return list(models or [])


def local_available(timeout: float = _AVAIL_TIMEOUT_S, model: str | None = None) -> bool:
    """True iff the Ollama server responds and the specified model is resident.

    When ``model`` is None, checks for the ``LOCAL_MODEL`` constant. Existing
    callers that pass no arguments continue to check ``LOCAL_MODEL`` unchanged.
    """
    effective_model = model if model is not None else LOCAL_MODEL
    try:
        import ollama

        client = ollama.Client(host=OLLAMA_HOST, timeout=timeout)
        models = _list_resident_models(client)
        return any(
            _model_matches(_resident_model_id(m), effective_model) for m in models
        )
    except Exception as exc:  # pragma: no cover - exercised via mock
        logger.debug("Ollama availability check failed: %s", exc)
        return False


def _ollama_generate(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    model: str | None = None,
) -> str:
    """Generate via Ollama chat.

    When ``model`` is None, uses the ``LOCAL_MODEL`` constant. Existing callers
    that omit ``model`` (positional-only) continue to use ``LOCAL_MODEL``
    unchanged.
    """
    import ollama

    effective_model = model if model is not None else LOCAL_MODEL
    client = ollama.Client(host=OLLAMA_HOST)
    resp = client.chat(
        model=effective_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        format="json",
        options={"temperature": 0, "num_predict": max_tokens},
    )
    return _chat_content(resp).strip()


def _chat_content(resp) -> str:
    """Extract message content across ollama-python response shapes.
    `ChatResponse` exposes `.message.content`; older dict responses use
    `["message"]["content"]`."""
    msg = getattr(resp, "message", None)
    if msg is not None:
        content = getattr(msg, "content", None)
        if content is None and hasattr(msg, "get"):
            content = msg.get("content", "")
        return content or ""
    return resp["message"]["content"] or ""


def _anthropic_generate(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set and local inference unavailable"
        )
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


def generate_json(
    system_prompt: str,
    user_prompt: str,
    *,
    prefer_local: bool | None = None,
    max_tokens: int = MAX_TOKENS,
    work_hint: str | None = None,
) -> tuple[str, str]:
    """Generate a model response (expected JSON text).

    Returns (text, backend) where backend is "ollama" or "anthropic".
    Local-first when prefer_local is True; on any local error, falls back to
    the Anthropic API.

    ``work_hint`` is an optional string passed to any installed model selector
    (see ``set_model_selector``) to steer local model choice. Omitting it is
    safe and backward-compatible — when absent, the selector (if any) receives
    None and the default model applies.
    """
    if prefer_local is None:
        prefer_local = prefer_local_default()

    if prefer_local:
        model = _resolve_local_model(work_hint)
        if local_available(model=model):
            try:
                return (
                    _ollama_generate(system_prompt, user_prompt, max_tokens, model=model),
                    "ollama",
                )
            except Exception as exc:
                logger.warning(
                    "Local inference failed (%s); falling back to Anthropic API.", exc
                )

    return _anthropic_generate(system_prompt, user_prompt, max_tokens), "anthropic"
