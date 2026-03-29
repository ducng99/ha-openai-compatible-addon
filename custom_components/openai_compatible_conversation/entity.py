"""Base entity for OpenAI."""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator, Callable, Iterable
import json
from mimetypes import guess_file_type
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import openai
from openai._streaming import AsyncStream
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from homeassistant.util import slugify

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DOMAIN,
    LOGGER,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_REASONING_EFFORT,
    RECOMMENDED_STT_MODEL,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)

if TYPE_CHECKING:
    from . import OpenAIConfigEntry


# Max number of back and forth with the LLM to generate a response
MAX_TOOL_ITERATIONS = 10


def _format_structured_output(
    schema: vol.Schema, llm_api: llm.APIInstance | None
) -> dict[str, Any]:
    """Format the schema to be compatible with OpenAI API."""
    return convert(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
    )


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> ChatCompletionToolParam:
    """Format tool specification."""
    return ChatCompletionToolParam(
        type="function",
        function={
            "name": tool.name,
            "parameters": convert(tool.parameters, custom_serializer=custom_serializer),
            "description": tool.description,
        },
    )


def _convert_content_to_param(
    chat_content: Iterable[conversation.Content],
) -> list[ChatCompletionMessageParam]:
    """Convert any native chat message for this agent to the native format."""
    messages: list[ChatCompletionMessageParam] = []

    for content in chat_content:
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": content.tool_call_id,
                    "content": json_dumps(content.tool_result),
                }
            )
            continue

        if isinstance(content, conversation.AssistantContent):
            tool_calls: list[ChatCompletionMessageToolCallParam] = []
            if content.tool_calls:
                for tool_call in content.tool_calls:
                    tool_calls.append(
                        ChatCompletionMessageToolCallParam(
                            id=tool_call.id,
                            type="function",
                            function={
                                "name": tool_call.tool_name,
                                "arguments": json_dumps(tool_call.tool_args),
                            },
                        )
                    )

            msg: ChatCompletionMessageParam = {
                "role": "assistant",
                "content": content.content or None,
            }
            if content.thinking_content:
                msg["reasoning_content"] = content.thinking_content
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)
            continue

        if content.content:
            messages.append({"role": content.role, "content": content.content})

    return messages


async def _transform_stream(
    chat_log: conversation.ChatLog,
    stream: AsyncStream[ChatCompletionChunk],
) -> AsyncGenerator[
    conversation.AssistantContentDeltaDict | conversation.ToolResultContentDeltaDict
]:
    """Transform an OpenAI Chat Completions delta stream into HA format."""
    current_tool_calls: dict[int, dict[str, str | int]] = {}
    last_role: Literal["assistant", "tool_result"] | None = None

    async for chunk in stream:
        LOGGER.debug("Received chunk: %s", chunk)

        if not chunk.choices:
            if chunk.usage is not None:
                chat_log.async_trace(
                    {
                        "stats": {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                        }
                    }
                )
            continue

        choice = chunk.choices[0]

        if choice.delta.role and choice.delta.role != last_role:
            yield {"role": "assistant"}
            last_role = "assistant"

        # Handle reasoning_content from OpenAI-compatible providers (DeepSeek, etc.)
        if (
            reasoning_content := getattr(choice.delta, "reasoning_content", None)
        ) and reasoning_content:
            yield {"thinking_content": reasoning_content}

        if choice.delta.content:
            yield {"content": choice.delta.content}

        if choice.delta.tool_calls:
            for tc_delta in choice.delta.tool_calls:
                idx = tc_delta.index
                if idx not in current_tool_calls:
                    current_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    if last_role != "assistant":
                        yield {"role": "assistant"}
                        last_role = "assistant"
                if tc_delta.id:
                    current_tool_calls[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        current_tool_calls[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        current_tool_calls[idx]["arguments"] += (
                            tc_delta.function.arguments
                        )

        if choice.finish_reason == "tool_calls":
            for idx in sorted(current_tool_calls.keys()):
                tc = current_tool_calls[idx]
                try:
                    tool_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    LOGGER.warning(
                        "Failed to parse tool arguments: %s", tc["arguments"]
                    )
                    tool_args = {}
                yield {
                    "tool_calls": [
                        llm.ToolInput(
                            id=tc["id"],
                            tool_name=tc["name"],
                            tool_args=tool_args,
                        )
                    ]
                }
            current_tool_calls = {}

        if choice.finish_reason == "length":
            raise HomeAssistantError("Response incomplete: max tokens reached")

        if choice.finish_reason == "content_filter":
            raise HomeAssistantError("Response incomplete: content filter triggered")


class OpenAIBaseLLMEntity(Entity):
    """OpenAI conversation agent."""

    _attr_has_entity_name = True
    _attr_name: str | None = None

    def __init__(self, entry: OpenAIConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="OpenAI",
            model=subentry.data.get(
                CONF_CHAT_MODEL,
                RECOMMENDED_CHAT_MODEL
                if subentry.subentry_type != "stt"
                else RECOMMENDED_STT_MODEL,
            ),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Generate an answer for the chat log."""
        options = self.subentry.data

        messages = _convert_content_to_param(chat_log.content)

        model_args: dict[str, Any] = {
            "model": options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
            "messages": messages,
            "max_tokens": options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
            "top_p": options.get(CONF_TOP_P, RECOMMENDED_TOP_P),
            "temperature": options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
            "user": chat_log.conversation_id,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if options.get(CONF_REASONING_EFFORT):
            model_args["reasoning_effort"] = options.get(
                CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT
            )

        tools: list[ChatCompletionToolParam] = []
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        # Handle attachments by adding them to the last user message
        last_content = chat_log.content[-1]
        if last_content.role == "user" and last_content.attachments:
            files = await async_prepare_files_for_prompt(
                self.hass,
                [(a.path, a.mime_type) for a in last_content.attachments],
            )
            last_message = messages[-1]
            assert last_message["role"] == "user" and isinstance(
                last_message["content"], str
            )
            last_message["content"] = [
                {"type": "text", "text": last_message["content"]},
                *files,
            ]

        if structure and structure_name:
            model_args["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": slugify(structure_name),
                    "strict": True,
                    "schema": _format_structured_output(structure, chat_log.llm_api),
                },
            }

        if tools:
            model_args["tools"] = tools

        client = self.entry.runtime_data

        # To prevent infinite loops, we limit the number of iterations
        for _iteration in range(max_iterations):
            try:
                stream = await client.chat.completions.create(**model_args)

                messages.extend(
                    _convert_content_to_param(
                        [
                            content
                            async for content in chat_log.async_add_delta_content_stream(
                                self.entity_id,
                                _transform_stream(chat_log, stream),
                            )
                        ]
                    )
                )
            except openai.RateLimitError as err:
                LOGGER.error("Rate limited: %s", err)
                raise HomeAssistantError("Rate limited or insufficient funds") from err
            except openai.OpenAIError as err:
                LOGGER.error(
                    "Error talking to API: %s\nRequest: %s\nMessages: %s",
                    err,
                    model_args,
                    messages,
                )
                raise HomeAssistantError("Error talking to API") from err

            if not chat_log.unresponded_tool_results:
                break


async def async_prepare_files_for_prompt(
    hass: HomeAssistant, files: list[tuple[Path, str | None]]
) -> list[dict[str, Any]]:
    """Append files to a prompt.

    Caller needs to ensure that the files are allowed.
    """

    def append_files_to_content() -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []

        for file_path, mime_type in files:
            if not file_path.exists():
                raise HomeAssistantError(f"`{file_path}` does not exist")

            if mime_type is None:
                mime_type = guess_file_type(file_path)[0]

            if not mime_type or not mime_type.startswith("image/"):
                raise HomeAssistantError(
                    f"Only images are supported, `{file_path}` is not an image file"
                )

            base64_file = base64.b64encode(file_path.read_bytes()).decode("utf-8")

            if mime_type.startswith("image/"):
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_file}",
                        },
                    }
                )

        return content

    return await hass.async_add_executor_job(append_files_to_content)
