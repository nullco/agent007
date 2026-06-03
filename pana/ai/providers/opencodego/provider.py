"""OpenCode Go provider — OpenAI-compatible Chat Completions API with API key authentication."""

from openai import AsyncOpenAI

from pana.ai.providers.auth import CredentialStore
from pana.ai.providers.model import Model, ModelInfo
from pana.ai.providers.openai_completions import OpenAICompletionsClient
from pana.ai.providers.provider import Provider

BASE_URL = "https://opencode.ai/zen/go/v1"

_OPENAI_THINKING = ["low", "medium", "high"]

MODEL_REGISTRY: dict[str, ModelInfo] = {
    "deepseek-v4-flash": ModelInfo(
        display_name="DeepSeek V4 Flash",
        thinking_levels=["high", "xhigh"],
        default_thinking="high",
        thinking_mode="deepseek",
        display_details="free",
    ),
    "deepseek-v4-pro": ModelInfo(
        display_name="DeepSeek V4 Pro",
        thinking_levels=["high", "xhigh"],
        default_thinking="high",
        thinking_mode="deepseek",
        display_details="1x",
    ),
    "glm-5": ModelInfo(
        display_name="GLM-5",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="0x",
    ),
    "glm-5.1": ModelInfo(
        display_name="GLM-5.1",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="1x",
    ),
    "kimi-k2.5": ModelInfo(
        display_name="Kimi K2.5",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="0x",
    ),
    "kimi-k2.6": ModelInfo(
        display_name="Kimi K2.6",
        thinking_levels=["high", "xhigh"],
        default_thinking="high",
        thinking_mode="deepseek",
        display_details="1x",
    ),
    "mimo-v2.5": ModelInfo(
        display_name="MiMo V2.5",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="0x",
    ),
    "mimo-v2.5-pro": ModelInfo(
        display_name="MiMo V2.5 Pro",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="1x",
    ),
    "minimax-m2.7": ModelInfo(
        display_name="MiniMax M2.7",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        display_details="0x",
    ),
    "qwen3.6-plus": ModelInfo(
        display_name="Qwen3.6 Plus",
        thinking_levels=_OPENAI_THINKING,
        default_thinking="medium",
        thinking_mode="qwen",
        display_details="0x",
    ),
}


class OpenCodeGoProvider(Provider):
    name = "opencodego"

    def __init__(self):
        self._credentials = CredentialStore("opencodego")

    async def authenticate(self, handler, ctx=None):
        if ctx is None:
            await handler("OpenCode Go requires a UI context for API key input.")
            return

        await handler("Please enter your OpenCode Go API key.")
        api_key = await ctx.input("OpenCode Go API key")
        if not api_key:
            await handler("API key is required for OpenCode Go.")
            return

        api_key = api_key.strip()
        self._credentials.set("api_key", api_key)
        self._credentials.save()
        await handler("OpenCode Go API key saved successfully.")

    def is_authenticated(self) -> bool:
        return bool(self._credentials.get("api_key"))

    def should_reauthenticate(self) -> bool:
        return False

    async def reauthenticate(self):
        pass

    async def build_model(self, model_name: str) -> Model:
        api_key = self._credentials.get("api_key")
        if not api_key:
            raise ValueError("OpenCode Go API key not configured — run /login")

        default_headers = {
            "x-opencode-client": "pana",
        }

        openai_client = AsyncOpenAI(
            base_url=BASE_URL,
            api_key=api_key,
            default_headers=default_headers,
        )
        info = MODEL_REGISTRY.get(model_name)
        client = OpenAICompletionsClient(
            openai_client,
            thinking_mode=info.thinking_mode if info else "reasoning_effort",
        )
        return Model(model_name, client, self, info=info)

    def get_models(self) -> dict[str, ModelInfo]:
        return MODEL_REGISTRY
