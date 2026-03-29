# Agent Guidelines for ha-openai-compatible-addon

This document provides coding guidelines for agents working on this Home Assistant custom component.

## Project Overview

Home Assistant custom integration providing OpenAI-compatible API endpoints for conversation, AI tasks, STT, and TTS. Works with OpenAI, Ollama, llama-server, vLLM, and other compatible servers.

## Build/Lint/Test Commands

### Linting
```bash
uvx ruff check custom_components/
uvx ruff format custom_components/
```

### Single Test Execution
This project currently has no test suite. Tests would be run using Home Assistant's test framework if added.

## Code Style Guidelines

### Import Organization
Organize imports in the following order per file:
1. `from __future__ import annotations` (required for all files)
2. Standard library (`collections.abc`, `logging`, `json`, etc.)
3. Third-party packages (`openai`, `voluptuous`, `propcache`)
4. Home Assistant core (`homeassistant.*`)
5. Local imports (`.const`, `.entity`)

Separate each group with a blank line:
```python
from __future__ import annotations

from collections.abc import Mapping
import logging

import openai
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, LOGGER
from .entity import OpenAIBaseLLMEntity
```

### Type Annotations
- Use Python 3.12+ style: `list[str]` instead of `List[str]`
- Use `TYPE_CHECKING` block for runtime-only imports to avoid circular imports:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import OpenAIConfigEntry
```
- Define type aliases for config entries:
```python
type OpenAIConfigEntry = ConfigEntry[openai.AsyncClient]
```

### Naming Conventions
- **Constants**: ALL_CAPS_WITH_UNDERSCORES (`DOMAIN`, `LOGGER`, `CONF_API_KEY`)
- **Logger instances**: `_LOGGER` for module-level loggers
- **Entity classes**: Suffix with entity type (e.g., `OpenAIConversationEntity`, `OpenAITTSEntity`)
- **Config flow handlers**: Suffix with `FlowHandler` or `ConfigFlow`
- **Private methods**: Prefix with `_` (e.g., `_async_handle_chat_log`)

### File Structure
```
custom_components/openai_compatible_conversation/
├── __init__.py          # Setup, migration, reauth, services
├── config_flow.py       # Config entries, subentry flows
├── conversation.py      # Conversation agent implementation
├── ai_task.py           # AI task entity
├── stt.py               # Speech-to-text entity
├── tts.py               # Text-to-speech entity
├── entity.py            # Base LLM entity (shared logic)
├── const.py             # Constants and default options
├── manifest.json        # Integration manifest
├── services.yaml        # Service definitions
└── translations/        # Localization files
```

### Async Patterns
- Always use `async def` for Home Assistant callbacks
- Use `async_add_executor_job` for blocking calls
- Prefer `hass.async_add_executor_job` over direct thread execution

### Error Handling
Use appropriate Home Assistant exceptions:
- `HomeAssistantError` - General runtime errors
- `ConfigEntryNotReady` - Setup failure (unrecoverable)
- `ConfigEntryAuthFailed` - Authentication failures (reauth required)
- `ServiceValidationError` - Invalid service calls

Always chain exceptions with `from err`:
```python
except openai.AuthenticationError as err:
    raise ConfigEntryAuthFailed("Auth failed") from err
```

### Entity Implementation
- Inherit from base entity class (e.g., `OpenAIBaseLLMEntity`)
- Implement `async_setup_entry` function
- Use `_attr_*` class attributes for entity properties
- Use `@callback` decorator for synchronous entity methods
- Set `_attr_has_entity_name = True` for proper naming

### Config Flow
- Subentry flows inherit from `ConfigSubentryFlow`
- Use `vol.Schema` with `vol.Required`/`vol.Optional`
- Use Home Assistant selectors (`TextSelector`, `SelectSelector`, etc.)
- Always define `VERSION` and `MINOR_VERSION` for migration support

### Platform Setup
Define platforms in `__init__.py`:
```python
PLATFORMS = (Platform.AI_TASK, Platform.CONVERSATION, Platform.STT, Platform.TTS)
```

### Logging
Use module-level loggers:
```python
_LOGGER = logging.getLogger(__name__)
```

For constants module, use:
```python
LOGGER: logging.Logger = logging.getLogger(__package__)
```

### Decorators
- Use `@callback` for synchronous methods called from async context
- Use `@property` for computed properties
- Use `@cached_property` for expensive computed properties

### Constants Module (const.py)
Define all configuration constants and recommended defaults:
```python
DOMAIN = "openai_compatible_conversation"
CONF_API_KEY = "api_key"
RECOMMENDED_API_BASE_URL = "https://api.openai.com/v1"
```

### Migration Support
Implement `async_migrate_entry` for version migrations:
```python
async def async_migrate_entry(hass: HomeAssistant, entry: OpenAIConfigEntry) -> bool:
    """Migrate entry."""
    if entry.version > 2:
        return False
    # Migration logic here
    return True
```

### Reauth Flow
Support reauthentication in config flow:
```python
async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
    return await self.async_step_reauth_confirm()
```

### Key Libraries
- `openai` - OpenAI Python SDK
- `voluptuous` - Configuration schema validation
- `propcache.api` - Property caching
- Home Assistant core packages (installed by HA environment)

### Quality Standards
- Run `ruff check` before commits
- Run `ruff format` before commits
- Follow Home Assistant coding standards
- Use Home Assistant's type stubs and selectors
- Keep functions under 100 lines when possible
- Use clear, descriptive variable names