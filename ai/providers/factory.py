"""Provider factory for selecting AI providers at runtime.

_provider_map. Third-party providers can register entry points under
'007.ai_providers'.
"""
from __future__ import annotations
from .base import Provider

# List of available providers
AVAILABLE_PROVIDERS = ["copilot", "openai"]


def _get_provider_class(name: str):
    name = (name or "").lower()
    if name in ("copilot", "github", "github-copilot", "github_copilot"):
        from .copilot import CopilotProvider

        return CopilotProvider
    if name in ("openai",):
        from .openai import OpenAIProvider

        return OpenAIProvider

    # Attempt to load third-party provider via entry points
    try:
        from importlib import metadata

        eps = metadata.entry_points(group="007.ai_providers")
        for ep in eps:
            if ep.name.lower() == name:
                cls = ep.load()
                return cls
    except Exception:
        # ignore entry point errors and fall through
        pass

    raise ValueError(f"Unknown provider: {name}")


def get_provider(name: str | None = None) -> Provider:
    """Return a provider instance.

    If name is None, uses AGENT_PROVIDER env var or defaults to 'copilot'.
    """
    provider_name = name or "copilot"
    cls = _get_provider_class(provider_name)
    return cls()
