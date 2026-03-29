"""Config flow for OpenAI-compatible Ollama Proxy."""

import socket

import voluptuous as vol
from homeassistant import config_entries

DOMAIN = "openai_ollama_proxy"

DEFAULTS = {
    "api_base_url": "https://api.openai.com/v1",
    "api_key": "",
    "port": 11434,
    "model_name": "",
}


def _port_available(port: int) -> bool:
    """Check if a TCP port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


class OpenAIOllamaProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # Check for duplicates
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            # Validate port
            if not _port_available(user_input["port"]):
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._schema(user_input),
                    errors={"base": "port_in_use"},
                )

            return self.async_create_entry(
                title="OpenAI Ollama Proxy",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(DEFAULTS),
        )

    def _schema(self, defaults):
        return vol.Schema(
            {
                vol.Required("api_base_url", default=defaults["api_base_url"]): str,
                vol.Optional("api_key", default=defaults["api_key"]): str,
                vol.Required("port", default=defaults["port"]): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional("model_name", default=defaults["model_name"]): str,
            }
        )
