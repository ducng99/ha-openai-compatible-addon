"""OpenAI-compatible Ollama Proxy for Home Assistant."""

import logging
import threading

import uvicorn
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import proxy

_LOGGER = logging.getLogger(__name__)

DOMAIN = "openai_ollama_proxy"

_uvicorn_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the proxy from a config entry."""
    global _uvicorn_server, _server_thread

    api_base_url = entry.data.get("api_base_url", "https://api.openai.com/v1")
    api_key = entry.data.get("api_key", "")
    port = entry.data.get("port", 11434)
    model_name = entry.data.get("model_name", "")

    # Configure the proxy module globals
    proxy.API_BASE_URL = api_base_url
    proxy.API_KEY = api_key
    proxy.MODEL_NAME = model_name

    _LOGGER.info(
        "Starting Ollama→OpenAI proxy on port %s (upstream: %s)", port, api_base_url
    )

    config = uvicorn.Config(
        proxy.app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        log_config=None,
    )
    _uvicorn_server = uvicorn.Server(config)

    _server_thread = threading.Thread(
        target=_uvicorn_server.run, daemon=True, name="ollama-proxy"
    )
    _server_thread.start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    global _uvicorn_server, _server_thread

    if _uvicorn_server is not None:
        _LOGGER.info("Stopping Ollama→OpenAI proxy")
        _uvicorn_server.should_exit = True
        if _server_thread is not None:
            _server_thread.join(timeout=5)
        _uvicorn_server = None
        _server_thread = None

    return True
