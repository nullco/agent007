from pana.ai.client import ModelClient


class Model:
    def __init__(
        self,
        name: str,
        client: ModelClient,
        provider,
        thinking_map: dict[str, str] | None = None,
    ):
        self.name = name
        self.client = client
        self.provider = provider
        self.thinking_map: dict[str, str] = thinking_map or {}

    def resolve_thinking(self, level: str) -> str | None:
        """Translate an app-level thinking label to a provider-native value.

        Returns ``None`` when the level is ``"off"`` or unknown.
        """
        if level == "off":
            return None
        return self.thinking_map.get(level)
