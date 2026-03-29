"""Constants for the OpenAI Conversation integration."""

import logging
from typing import Any

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm

DOMAIN = "openai_compatible_conversation"
LOGGER: logging.Logger = logging.getLogger(__package__)

CONF_API_BASE_URL = "api_base_url"
RECOMMENDED_API_BASE_URL = "https://api.openai.com/v1"

DEFAULT_CONVERSATION_NAME = "OpenAI Conversation"
DEFAULT_AI_TASK_NAME = "OpenAI AI Task"
DEFAULT_STT_NAME = "OpenAI STT"
DEFAULT_TTS_NAME = "OpenAI TTS"
DEFAULT_NAME = "OpenAI Conversation"

CONF_CHAT_MODEL = "chat_model"
CONF_MAX_TOKENS = "max_tokens"
CONF_PROMPT = "prompt"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_TEMPERATURE = "temperature"
CONF_TOP_P = "top_p"
CONF_TTS_SPEED = "tts_speed"

RECOMMENDED_CHAT_MODEL = "gpt-4o-mini"
RECOMMENDED_MAX_TOKENS = 3000
RECOMMENDED_REASONING_EFFORT = "low"
RECOMMENDED_STT_MODEL = "whisper-1"
RECOMMENDED_TEMPERATURE = 1.0
RECOMMENDED_TOP_P = 1.0
RECOMMENDED_TTS_SPEED = 1.0

DEFAULT_STT_PROMPT = (
    "The following conversation is a smart home user talking to Home Assistant."
)

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
RECOMMENDED_AI_TASK_OPTIONS: dict[str, Any] = {}
RECOMMENDED_STT_OPTIONS: dict[str, Any] = {}
RECOMMENDED_TTS_OPTIONS = {
    CONF_PROMPT: "",
    CONF_CHAT_MODEL: "tts-1",
}
