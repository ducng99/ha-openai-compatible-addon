# OpenAI-compatible Assistant for Home Assistant

A custom Home Assistant integration that extends the official OpenAI Conversation integration with support for **any OpenAI-compatible API endpoint**. Use OpenAI, or bring your own local/remote LLM server (llama-server, Ollama, vLLM, LiteLLM, LocalAI, etc.).

## Requirements

- Home Assistant 2025.x or later
- An OpenAI-compatible API server accessible from your Home Assistant instance

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS.
2. Search for "OpenAI-compatible Assistant" and install it.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/openai_conversation` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

### Step 1 -- Add the integration

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **OpenAI** (or "OpenAI-compatible Assistant").
3. Enter the following:
   - **API base URL** -- the base URL of your OpenAI-compatible server (e.g., `http://192.168.1.100:8080/v1`). Defaults to `https://api.openai.com/v1`.
   - **API key** -- your API key. Use a dummy key (e.g., `not-needed`) if your server doesn't require authentication.
4. Click **Submit**. The integration will verify the connection.

### Step 2 -- Configure subentries

After setup, the integration automatically creates default subentries for **Conversation**, **AI Task**, **STT**, and **TTS**. You can reconfigure or add additional subentries:

- **Conversation** -- choose the chat model, prompt, max tokens, temperature, etc.
- **AI Task** -- configure image generation and structured data models.
- **STT** -- select the transcription model (e.g., `whisper-1`).
- **TTS** -- select the speech model and voice.

## Compatible servers

This integration works with any server that exposes an OpenAI-compatible API, including:

| Server | Example base URL |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| llama-server (llama.cpp) | `http://localhost:8080/v1` |
| vLLM | `http://localhost:8000/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |

## Supported models

The integration is designed to work with a wide range of models. When using a local server, you can specify any model name that your server supports. Some features are gated behind specific model name prefixes (e.g., `gpt-5` for advanced reasoning options).

For best results with non-OpenAI servers, enable **Recommended model settings** during subentry configuration.

## Example: llama-server (llama.cpp)

[llama.cpp](https://github.com/ggml-org/llama.cpp) provides `llama-server`, a lightweight HTTP server with a built-in OpenAI-compatible API.

```bash
# Start llama-server with a GGUF model
llama-server -m model.gguf --host 0.0.0.0 --port 8080
```

Then in Home Assistant:
1. Set **API base URL** to `http://<your-server-ip>:8080/v1`
2. Set **API key** to any value (e.g., `not-needed`) -- llama-server does not require authentication by default
3. In the conversation subentry settings, set the **Model** to the model name loaded on the server (default: `gpt-3.5-turbo` unless overridden with `--alias`)

```bash
# Example with a specific model alias and GPU offloading
llama-server -m llama-3-8b.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  --alias llama-3-8b \
  -ngl 99
```

With `--alias`, the model name in Home Assistant should match `llama-3-8b`.

## Troubleshooting

### Cannot connect

- Verify the API base URL is reachable from Home Assistant (try `curl <base_url>/models`).
- Check that your server is running and listening on the expected port.
- Ensure there are no firewall rules blocking the connection.

### Authentication errors

- Confirm the API key is correct.
- If your server doesn't require authentication, enter any non-empty string as the API key.

### Model not found

- Ensure the model name exactly matches what your server expects.
- For Ollama, the model name should match `ollama list` output.

## License

This project is based on the [Home Assistant OpenAI Conversation integration](https://www.home-assistant.io/integrations/openai_conversation) and follows the same Apache 2.0 license.
