# OpenAI-compatible Ollama Proxy

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that proxies Ollama API requests on port **11434** to any **OpenAI-compatible** backend.

Lets you use any OpenAI-compatible provider (OpenAI, LiteLLM, vLLM, LocalAI, OpenRouter, Groq, Azure OpenAI, etc.) as a drop-in replacement for Ollama with Home Assistant's built-in **Ollama** integration.

## Installation

### HACS (recommended)

1. Make sure [HACS](https://hacs.xyz) is installed.
2. Go to **HACS → Integrations → ⋮ → Custom repositories** and add this repo URL as type **Integration**.
3. Search for "OpenAI-compatible Ollama Proxy" and install it.
4. Restart Home Assistant.

### Manual

Copy the `custom_components/openai_ollama_proxy/` directory into your Home Assistant `config/custom_components/` folder and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **OpenAI-compatible Ollama Proxy**.
3. Fill in:
   | Field | Description |
   |---|---|
   | API Base URL | Base URL of the OpenAI-compatible API (default: `https://api.openai.com/v1`) |
   | API Key | Bearer token / API key (leave empty if not needed) |
   | Port | Port to listen on (default: `11434`) |
   | Model name | Optional — force a specific model name in the model list |

## Usage with Ollama integration

After setting up the proxy, add Home Assistant's built-in **Ollama** integration pointing at the proxy:

1. **Settings → Devices & Services → Add Integration → Ollama**.
2. Set the URL to `http://<your-ha-ip>:11434` (or `http://localhost:11434`).
3. Select the model from the dropdown (populated from the upstream API, or the configured model name).
4. Done — HA will talk to your OpenAI-compatible backend through the Ollama interface.

## Supported endpoints

| Ollama endpoint | Status |
|---|---|
| `GET /api/tags` | Proxies to upstream `GET /v1/models` |
| `POST /api/chat` | Proxies to upstream `POST /v1/chat/completions` (streaming & non-streaming) |
| `POST /api/show` | Stub for compatibility |

## Features

- Streaming and non-streaming chat
- Tool / function calling
- Vision (inline base64 images)
- Structured output (`format` parameter)
- Thinking / reasoning content passthrough (`reasoning_content`)
- Ollama options → OpenAI parameter mapping (`temperature`, `top_p`, `max_tokens`, `stop`, `seed`)
