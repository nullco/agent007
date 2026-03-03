# Command Reference

Your TUI supports the following slash commands:

## Authentication Commands

### `/login`
Start authentication with a specified or default provider.

**Usage:**
- `/login` - Log in with the current provider (default: GitHub Copilot)
- `/login copilot` - Log in with GitHub Copilot (device flow)
- `/login openai` - Log in with OpenAI
- `/login <provider>` - Log in with any configured provider

**Features:**
- Device flow for GitHub Copilot
- Automatically polls for completion
- Supports multiple providers
- Each provider maintains its own token state

### `/logout`
Clear authentication tokens for a provider.

**Usage:**
- `/logout` - Log out from the current provider
- `/logout copilot` - Log out from GitHub Copilot
- `/logout openai` - Log out from OpenAI
- `/logout <provider>` - Log out from any configured provider

**Features:**
- Removes stored tokens
- Updates environment variables
- Per-provider logout support

### `/status`
Show login status for provider(s).

**Usage:**
- `/status` - Show status for the current provider
- `/status copilot` - Show status for GitHub Copilot
- `/status openai` - Show status for OpenAI
- `/status all` - Show status for all providers

**Example Output:**
```
[Status] Not logged in
```

## Chat & History

### `/clear`
Clear chat history.
- Removes all previous messages in the current session
- Agent state is reset

## Model Selection

### `/model`
List or select a model. Selecting a model automatically switches to its provider.

**Usage:**
- `/model` - Show all available models from all providers with their provider names
- `/model <id>` - Select a model (automatically switches to its provider)

**Example:**
```
/model

Current: gpt-4 (copilot)

Available:
  → gpt-4                  GPT-4                     [copilot] (enabled)
    gpt-4-turbo            GPT-4 Turbo               [copilot] (enabled)
    claude-opus            Claude 3 Opus             [copilot] (requires acceptance)
    gpt-4o                 GPT-4o                    [openai]

/model gpt-4o
# Automatically switches to OpenAI provider and selects gpt-4o
```

**Features:**
- Shows all models from all configured providers
- Displays current model and provider
- Shows model status (enabled, requires acceptance, etc.)
- Automatically handles provider switching when you select a model
- Models are inherently tied to their providers

## Multi-Provider Support

The TUI now supports multiple authentication providers:

- **GitHub Copilot** (default) - Uses device flow OAuth
- **OpenAI** - API key based authentication

Each provider maintains its own:
- Authentication tokens
- Token expiration state
- Login status
- Available models

You can seamlessly switch between providers using:
1. `/login <provider>` - Log in to a new provider
2. `/model <model_id>` - Switch to provider by selecting its model
3. Models automatically indicate which provider they belong to

## Interactive Usage

All commands can be:
1. **Typed** in the chat input with `/` prefix
2. **Selected** from the system command palette (usually Ctrl+\)

## Key Bindings

- `Ctrl+C` - Single press clears session, double press within 1 second quits
- `c` - Copy focused message to clipboard
