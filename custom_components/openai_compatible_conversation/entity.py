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
from openai.types.responses import (
    EasyInputMessageParam,
    FunctionToolParam,
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseFunctionToolCallParam,
    ResponseIncompleteEvent,
    ResponseInputFileParam,
    ResponseInputImageParam,
    ResponseInputMessageContentListParam,
    ResponseInputParam,
    ResponseInputTextParam,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseReasoningItem,
    ResponseReasoningItemParam,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    ToolChoiceTypesParam,
    ToolParam,
)
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming
from openai.types.responses.response_input_param import FunctionCallOutput
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir, llm
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
) -> FunctionToolParam:
    """Format tool specification."""
    return FunctionToolParam(
        type="function",
        name=tool.name,
        parameters=convert(tool.parameters, custom_serializer=custom_serializer),
        description=tool.description,
        strict=False,
    )


def _convert_content_to_param(
    chat_content: Iterable[conversation.Content],
) -> ResponseInputParam:
    """Convert any native chat message for this agent to the native format."""
    messages: ResponseInputParam = []

    for content in chat_content:
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=content.tool_call_id,
                    output=json_dumps(content.tool_result),
                )
            )
            continue

        if content.content:
            role: Literal["user", "assistant", "system", "developer"] = content.role
            if role == "system":
                role = "developer"
            messages.append(
                EasyInputMessageParam(
                    type="message", role=role, content=content.content
                )
            )

        if isinstance(content, conversation.AssistantContent):
            if content.tool_calls:
                for tool_call in content.tool_calls:
                    messages.append(
                        ResponseFunctionToolCallParam(
                            type="function_call",
                            name=tool_call.tool_name,
                            arguments=json_dumps(tool_call.tool_args),
                            call_id=tool_call.id,
                        )
                    )

            if content.thinking_content:
                pass  # thinking_content is already in content

            if isinstance(content.native, ResponseReasoningItem):
                messages.append(
                    ResponseReasoningItemParam(
                        type="reasoning",
                        id=content.native.id,
                        summary=[],
                        encrypted_content=content.native.encrypted_content,
                    )
                )

    return messages


async def _transform_stream(
    chat_log: conversation.ChatLog,
    stream: AsyncStream[ResponseStreamEvent],
) -> AsyncGenerator[
    conversation.AssistantContentDeltaDict | conversation.ToolResultContentDeltaDict
]:
    """Transform an OpenAI delta stream into HA format."""
    last_summary_index = None
    last_role: Literal["assistant", "tool_result"] | None = None

    async for event in stream:
        LOGGER.debug("Received event: %s", event)

        if isinstance(event, ResponseOutputItemAddedEvent):
            if isinstance(event.item, ResponseFunctionToolCall):
                yield {"role": "assistant"}
                last_role = "assistant"
                last_summary_index = None
                current_tool_call = event.item
            elif (
                isinstance(event.item, ResponseOutputMessage)
                or (
                    isinstance(event.item, ResponseReasoningItem)
                    and last_summary_index is not None
                )
                or last_role != "assistant"
            ):
                yield {"role": "assistant"}
                last_role = "assistant"
                last_summary_index = None
        elif isinstance(event, ResponseOutputItemDoneEvent):
            if isinstance(event.item, ResponseReasoningItem):
                yield {
                    "native": ResponseReasoningItem(
                        type="reasoning",
                        id=event.item.id,
                        summary=[],
                        encrypted_content=event.item.encrypted_content,
                    )
                }
                last_summary_index = len(event.item.summary) - 1
        elif isinstance(event, ResponseTextDeltaEvent):
            if event.delta:
                yield {"content": event.delta}
        elif isinstance(event, ResponseReasoningSummaryTextDeltaEvent):
            if (
                last_summary_index is not None
                and event.summary_index != last_summary_index
            ):
                yield {"role": "assistant"}
                last_role = "assistant"
            last_summary_index = event.summary_index
            yield {"thinking_content": event.delta}
        elif isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            current_tool_call.arguments += event.delta
        elif isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            current_tool_call.status = "completed"
            yield {
                "tool_calls": [
                    llm.ToolInput(
                        id=current_tool_call.call_id,
                        tool_name=current_tool_call.name,
                        tool_args=json.loads(current_tool_call.arguments),
                    )
                ]
            }
        elif isinstance(event, ResponseCompletedEvent):
            if event.response.usage is not None:
                chat_log.async_trace(
                    {
                        "stats": {
                            "input_tokens": event.response.usage.input_tokens,
                            "output_tokens": event.response.usage.output_tokens,
                        }
                    }
                )
        elif isinstance(event, ResponseIncompleteEvent):
            if event.response.usage is not None:
                chat_log.async_trace(
                    {
                        "stats": {
                            "input_tokens": event.response.usage.input_tokens,
                            "output_tokens": event.response.usage.output_tokens,
                        }
                    }
                )

            if (
                event.response.incomplete_details
                and event.response.incomplete_details.reason
            ):
                reason: str = event.response.incomplete_details.reason
            else:
                reason = "unknown reason"

            if reason == "max_output_tokens":
                reason = "max output tokens reached"
            elif reason == "content_filter":
                reason = "content filter triggered"

            raise HomeAssistantError(f"Response incomplete: {reason}")
        elif isinstance(event, ResponseFailedEvent):
            if event.response.usage is not None:
                chat_log.async_trace(
                    {
                        "stats": {
                            "input_tokens": event.response.usage.input_tokens,
                            "output_tokens": event.response.usage.output_tokens,
                        }
                    }
                )
            reason = "unknown reason"
            if event.response.error is not None:
                reason = event.response.error.message
            raise HomeAssistantError(f"Response failed: {reason}")
        elif isinstance(event, ResponseErrorEvent):
            raise HomeAssistantError(f"Response error: {event.message}")


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

        model_args = ResponseCreateParamsStreaming(
            model=options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
            input=messages,
            max_output_tokens=options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
            top_p=options.get(CONF_TOP_P, RECOMMENDED_TOP_P),
            temperature=options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
            user=chat_log.conversation_id,
            store=False,
            stream=True,
        )

        if options.get(CONF_REASONING_EFFORT):
            model_args["reasoning"] = {
                "effort": options.get(
                    CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT
                ),
            }

        tools: list[ToolParam] = []
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
            assert (
                last_message["type"] == "message"
                and last_message["role"] == "user"
                and isinstance(last_message["content"], str)
            )
            last_message["content"] = [
                {"type": "input_text", "text": last_message["content"]},
                *files,
            ]

        if structure and structure_name:
            model_args["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": slugify(structure_name),
                    "schema": _format_structured_output(structure, chat_log.llm_api),
                },
            }

        if tools:
            model_args["tools"] = tools

        client = self.entry.runtime_data

        # To prevent infinite loops, we limit the number of iterations
        for _iteration in range(max_iterations):
            try:
                stream = await client.responses.create(**model_args)

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
                LOGGER.error("Error talking to API: %s", err)
                raise HomeAssistantError("Error talking to API") from err

            if not chat_log.unresponded_tool_results:
                break


async def async_prepare_files_for_prompt(
    hass: HomeAssistant, files: list[tuple[Path, str | None]]
) -> ResponseInputMessageContentListParam:
    """Append files to a prompt.

    Caller needs to ensure that the files are allowed.
    """

    def append_files_to_content() -> ResponseInputMessageContentListParam:
        content: ResponseInputMessageContentListParam = []

        for file_path, mime_type in files:
            if not file_path.exists():
                raise HomeAssistantError(f"`{file_path}` does not exist")

            if mime_type is None:
                mime_type = guess_file_type(file_path)[0]

            if not mime_type or not mime_type.startswith(("image/", "application/pdf")):
                raise HomeAssistantError(
                    "Only images and PDF are supported,"
                    f"`{file_path}` is not an image file or PDF"
                )

            base64_file = base64.b64encode(file_path.read_bytes()).decode("utf-8")

            if mime_type.startswith("image/"):
                content.append(
                    ResponseInputImageParam(
                        type="input_image",
                        image_url=f"data:{mime_type};base64,{base64_file}",
                        detail="auto",
                    )
                )
            elif mime_type.startswith("application/pdf"):
                content.append(
                    ResponseInputFileParam(
                        type="input_file",
                        filename=str(file_path),
                        file_data=f"data:{mime_type};base64,{base64_file}",
                    )
                )

        return content

    return await hass.async_add_executor_job(append_files_to_content)
