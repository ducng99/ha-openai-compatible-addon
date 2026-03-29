"""FastAPI proxy — Ollama API to OpenAI-compatible back-end."""

import json
import logging
import time
import uuid

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("openai_ollama_proxy")

app = FastAPI()

# These are overridden at import-time by __init__.py before the server starts.
API_BASE_URL: str = "https://api.openai.com/v1"
API_KEY: str = ""
MODEL_NAME: str = ""


def _get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


# ---------------------------------------------------------------------------
# /api/tags — proxy upstream GET /models so HA dropdown has options
# ---------------------------------------------------------------------------


@app.get("/api/tags")
def list_models():
    """List available models by querying the upstream /models endpoint."""
    url = f"{API_BASE_URL.rstrip('/')}/models"
    headers = _get_headers()

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("Upstream /models returned %s", resp.status_code)
            return {"models": []}

        data = resp.json()
        models = data.get("data", [])

        now = time.strftime("%Y-%m-%dT%H:%M:%S.000000000%z", time.localtime())
        ollama_models = []
        for m in models:
            mid = m.get("id", "")
            if not mid:
                continue
            ollama_models.append(
                {
                    "name": mid,
                    "model": mid,
                    "modified_at": now,
                    "size": 0,
                    "digest": "",
                    "details": {
                        "format": "api",
                        "family": "openai-compatible",
                        "families": ["openai-compatible"],
                        "parameter_size": "unknown",
                        "quantization_level": "unknown",
                    },
                }
            )

        if MODEL_NAME and not any(m["name"] == MODEL_NAME for m in ollama_models):
            ollama_models.insert(
                0,
                {
                    "name": MODEL_NAME,
                    "model": MODEL_NAME,
                    "modified_at": now,
                    "size": 0,
                    "digest": "",
                    "details": {
                        "format": "api",
                        "family": "openai-compatible",
                        "families": ["openai-compatible"],
                        "parameter_size": "unknown",
                        "quantization_level": "unknown",
                    },
                },
            )

        return {"models": ollama_models}

    except requests.RequestException as exc:
        logger.warning("Failed to fetch upstream /models: %s", exc)
        return {"models": []}


# ---------------------------------------------------------------------------
# /api/chat — translate Ollama chat → OpenAI chat/completions
# ---------------------------------------------------------------------------


def _ollama_messages_to_openai(messages: list) -> list:
    """Convert Ollama message list to OpenAI message list."""
    openai_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "tool":
            openai_messages.append(
                {
                    "role": "tool",
                    "content": content,
                    "tool_call_id": msg.get("tool_call_id", ""),
                }
            )
            continue

        images = msg.get("images")
        if images:
            content_parts = []
            if content:
                content_parts.append({"type": "text", "text": content})
            for img in images:
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img}",
                        },
                    }
                )
            openai_messages.append({"role": role, "content": content_parts})
            continue

        tool_calls = msg.get("tool_calls")
        if tool_calls and role == "assistant":
            openai_tc = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, dict):
                    args = json.dumps(args)
                openai_tc.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": args,
                        },
                    }
                )
            openai_messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": openai_tc,
                }
            )
            continue

        openai_messages.append({"role": role, "content": content})
    return openai_messages


def _ollama_tools_to_openai(tools) -> list | None:
    """Convert Ollama tool list to OpenAI tool list."""
    if not tools:
        return None
    openai_tools = []
    for tool in tools:
        fn = tool.get("function", {})
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                },
            }
        )
    return openai_tools


def _ollama_format_to_openai_response_format(fmt):
    """Convert Ollama format to OpenAI response_format."""
    if not fmt:
        return None
    if isinstance(fmt, str) and fmt == "json":
        return {"type": "json_object"}
    if isinstance(fmt, dict):
        return {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": fmt, "strict": True},
        }
    return None


def _openai_tool_calls_to_ollama(tool_calls) -> list | None:
    """Convert OpenAI tool_calls to Ollama format."""
    if not tool_calls:
        return None
    ollama_tc = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        ollama_tc.append(
            {
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": args,
                }
            }
        )
    return ollama_tc if ollama_tc else None


def _openai_finish_reason_to_ollama(reason) -> str:
    """Map OpenAI finish_reason to Ollama done_reason."""
    if reason == "stop":
        return "stop"
    if reason == "length":
        return "length"
    if reason == "tool_calls":
        return "stop"
    return reason or "stop"


def _non_stream_response(openai_data: dict, ollama_model: str) -> dict:
    """Convert a non-streaming OpenAI response to Ollama format."""
    choice = openai_data.get("choices", [{}])[0]
    message = choice.get("message", {})
    usage = openai_data.get("usage", {})

    content = message.get("content") or ""
    thinking = message.get("reasoning_content")

    ollama_msg = {
        "role": "assistant",
        "content": content,
    }
    if thinking:
        ollama_msg["thinking"] = thinking

    tool_calls = _openai_tool_calls_to_ollama(message.get("tool_calls"))
    if tool_calls:
        ollama_msg["tool_calls"] = tool_calls

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    return {
        "model": ollama_model,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()),
        "message": ollama_msg,
        "done": True,
        "done_reason": _openai_finish_reason_to_ollama(choice.get("finish_reason")),
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_count": prompt_tokens,
        "prompt_eval_duration": 0,
        "eval_count": completion_tokens,
        "eval_duration": 0,
    }


def _stream_openai_to_ollama(openai_resp, ollama_model: str):
    """Convert an OpenAI SSE stream to Ollama NDJSON stream."""

    def generate():
        first_chunk = True
        for line in openai_resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                yield (
                    json.dumps(
                        {
                            "model": ollama_model,
                            "created_at": time.strftime(
                                "%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()
                            ),
                            "message": {"role": "assistant", "content": ""},
                            "done": True,
                            "done_reason": "stop",
                            "total_duration": 0,
                            "load_duration": 0,
                            "prompt_eval_count": 0,
                            "prompt_eval_duration": 0,
                            "eval_count": 0,
                            "eval_duration": 0,
                        }
                    )
                    + "\n"
                )
                return

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})

            ollama_msg = {}

            if first_chunk:
                ollama_msg["role"] = "assistant"
                first_chunk = False

            if "content" in delta:
                ollama_msg["content"] = delta["content"] or ""

            if "reasoning_content" in delta:
                ollama_msg["thinking"] = delta["reasoning_content"] or ""

            if delta.get("tool_calls"):
                ollama_msg["tool_calls"] = _openai_tool_calls_to_ollama(
                    delta["tool_calls"]
                )

            event = {
                "model": ollama_model,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()
                ),
                "message": ollama_msg,
                "done": False,
            }
            yield json.dumps(event) + "\n"

        # If stream ended without [DONE], still send final
        yield (
            json.dumps(
                {
                    "model": ollama_model,
                    "created_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()
                    ),
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 0,
                    "load_duration": 0,
                    "prompt_eval_count": 0,
                    "prompt_eval_duration": 0,
                    "eval_count": 0,
                    "eval_duration": 0,
                }
            )
            + "\n"
        )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/chat")
async def chat(request: Request):
    """Translate Ollama /api/chat to OpenAI /v1/chat/completions."""
    body = await request.json()
    ollama_model = body.get("model", "")
    stream = body.get("stream", True)

    openai_messages = _ollama_messages_to_openai(body.get("messages", []))
    openai_tools = _ollama_tools_to_openai(body.get("tools"))
    openai_response_format = _ollama_format_to_openai_response_format(
        body.get("format")
    )

    openai_body = {
        "model": ollama_model,
        "messages": openai_messages,
        "stream": stream,
    }

    if openai_tools:
        openai_body["tools"] = openai_tools

    if openai_response_format:
        openai_body["response_format"] = openai_response_format

    options = body.get("options", {})
    if options:
        if "temperature" in options:
            openai_body["temperature"] = options["temperature"]
        if "top_p" in options:
            openai_body["top_p"] = options["top_p"]
        if "num_predict" in options:
            openai_body["max_tokens"] = options["num_predict"]
        if "stop" in options:
            stop = options["stop"]
            openai_body["stop"] = stop if isinstance(stop, list) else [stop]
        if "seed" in options:
            openai_body["seed"] = options["seed"]

    url = f"{API_BASE_URL.rstrip('/')}/chat/completions"
    headers = _get_headers()

    logger.info(
        "Proxying chat request to %s (stream=%s, model=%s)", url, stream, ollama_model
    )

    try:
        if stream:
            resp = requests.post(
                url, json=openai_body, headers=headers, stream=True, timeout=300
            )
            if resp.status_code != 200:
                error_text = resp.text
                logger.error("Upstream error %s: %s", resp.status_code, error_text)
                return JSONResponse(
                    content={
                        "error": f"Upstream error {resp.status_code}: {error_text}"
                    },
                    status_code=502,
                )
            return _stream_openai_to_ollama(resp, ollama_model)
        else:
            resp = requests.post(url, json=openai_body, headers=headers, timeout=300)
            if resp.status_code != 200:
                error_text = resp.text
                logger.error("Upstream error %s: %s", resp.status_code, error_text)
                return JSONResponse(
                    content={
                        "error": f"Upstream error {resp.status_code}: {error_text}"
                    },
                    status_code=502,
                )
            return _non_stream_response(resp.json(), ollama_model)
    except requests.RequestException as exc:
        logger.error("Request to upstream failed: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=502)


# ---------------------------------------------------------------------------
# /api/show — stub so HA doesn't error out
# ---------------------------------------------------------------------------


@app.post("/api/show")
async def show_model(request: Request):
    """Return a minimal model info response."""
    body = await request.json() if await request.body() else {}
    model = body.get("model", "")
    return {
        "license": "",
        "modelfile": f"FROM {model}",
        "parameters": "",
        "template": "{{ .Prompt }}",
        "details": {
            "format": "api",
            "family": "openai-compatible",
            "families": ["openai-compatible"],
            "parameter_size": "unknown",
            "quantization_level": "unknown",
        },
        "model_info": {},
    }
