# AGENTS.md

## Project overview

Home Assistant **HACS custom integration** that proxies Ollama API requests on port 11434 to any OpenAI-compatible API. Lets HA's built-in Ollama integration talk to OpenAI, LiteLLM, vLLM, LocalAI, OpenRouter, Groq, etc.

## Repository structure

```
hacs.json                            # HACS manifest (display name)
README.md                            # User-facing documentation
custom_components/openai_ollama_proxy/
├── manifest.json                    # HA integration manifest (domain, deps, version)
├── __init__.py                      # Integration setup — starts/stops uvicorn server
├── config_flow.py                   # UI-based configuration flow
├── proxy.py                         # FastAPI app — all proxy route logic
└── strings.json                     # UI translation strings
```

## Build & run

No build step. HACS installs directly into `config/custom_components/`. To test locally without HA:

```bash
pip install fastapi uvicorn requests
export API_BASE_URL="https://api.openai.com/v1"
export API_KEY="sk-..."
# Run via uvicorn directly (bypasses HA lifecycle)
uvicorn custom_components.openai_ollama_proxy.proxy:app --host 0.0.0.0 --port 11434
```

## Linting

Lint with ruff (no config file — use defaults or pass flags inline):

```bash
ruff check custom_components/openai_ollama_proxy/
ruff format --check custom_components/openai_ollama_proxy/
```

Auto-fix:

```bash
ruff check --fix custom_components/openai_ollama_proxy/
ruff format custom_components/openai_ollama_proxy/
```

## Testing

No test suite exists. Validate changes manually:

1. Start the proxy with an OpenAI-compatible backend.
2. `curl http://localhost:11434/api/tags` — should return model list.
3. `curl -X POST http://localhost:11434/api/chat -H 'Content-Type: application/json' -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}'` — should return Ollama-format response.

## Code style

### General

- FastAPI app in `proxy.py`; all proxy route logic lives there.
- No classes — use module-level functions and FastAPI route decorators.
- Configuration via HA config entries (set in `config_flow.py`, read in `__init__.py`).
- Uvicorn server runs in a daemon thread started by `async_setup_entry`.

### Imports

- Standard library first, then third-party, separated by blank line.
- Third-party deps: `fastapi`, `uvicorn`, `requests` (all in `manifest.json` requirements).
- Import from fastapi: `from fastapi import FastAPI, Request`.
- Import from fastapi.responses: `from fastapi.responses import JSONResponse, StreamingResponse`.

### Naming

- Prefix private helpers with underscore: `_ollama_messages_to_openai`.
- Use descriptive names: `_openai_tool_calls_to_ollama` not `_convert_tc`.
- Mutable config values are module-level globals set at setup time: `API_BASE_URL`, `API_KEY`, `MODEL_NAME`.

### Formatting

- 88-character line length (ruff default).
- Single blank line between functions, double blank line between logical sections.
- Section separators with `# ---` comment blocks for the three endpoints.
- Prefer `json.dumps` + `"\n"` over f-strings for NDJSON output.

### Error handling

- Catch `requests.RequestException` for all upstream calls.
- Return `JSONResponse(..., status_code=502)` on upstream failures.
- Log with `logger.warning` for recoverable issues (model list fetch fail).
- Log with `logger.error` for request failures.
- Upstream timeout: 10s for model list, 300s for chat.

### Type handling

- Use `| None` union syntax for optional returns (e.g. `-> list | None`).
- Be defensive with `.get()` on dicts — always provide defaults.
- Parse JSON string arguments from tool calls with `json.loads` + `json.JSONDecodeError` fallback.

### API conventions

- The model name in `/api/chat` is always forwarded as-is from the Ollama request body. Never hardcode model names.
- `/api/tags` proxies to upstream `GET /v1/models` to populate HA's model dropdown.
- `/api/show` is a stub returning the model name from the request body.
- Streaming: convert upstream SSE (`data: ...` / `[DONE]`) to Ollama NDJSON (`{...}\n`).
- Always emit a final `done: true` chunk, even if `[DONE]` was missing.

## Adding new endpoints

1. Add an `@app.get/post(...)` function in the appropriate section of `proxy.py`.
2. Use `_get_headers()` for upstream auth.
3. Return plain dicts (FastAPI auto-serialises) or `JSONResponse`.
4. Keep backward compatibility — HA's Ollama integration expects specific response shapes.
