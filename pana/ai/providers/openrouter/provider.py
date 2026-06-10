"""OpenRouter provider — OpenAI-compatible Chat Completions API with API key authentication.

All models in this registry are free on OpenRouter (zero-cost prompts and completions).
"""

from openai import AsyncOpenAI

from pana.ai.providers.auth import CredentialStore
from pana.ai.providers.model import Model, ModelInfo
from pana.ai.providers.openai_completions import OpenAICompletionsClient
from pana.ai.providers.provider import Provider


def _openrouter_thinking(kwargs: dict, level: str) -> None:
    kwargs["reasoning"] = {"effort": level}

BASE_URL = "https://openrouter.ai/api/v1"

_OPENROUTER_THINKING = ["low", "medium", "high"]

MODEL_REGISTRY: dict[str, ModelInfo] = {
    # --- Poolside — coding agent specialists ---
    "poolside/laguna-m.1:free": ModelInfo(
        display_name="Laguna M.1",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="high",
        display_details="Poolside · flagship coding agent",
    ),
    "poolside/laguna-xs.2:free": ModelInfo(
        display_name="Laguna XS.2",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="high",
        display_details="Poolside · efficient coding agent",
    ),
    # --- Qwen — code generation specialist ---
    "qwen/qwen3-coder:free": ModelInfo(
        display_name="Qwen3 Coder 480B",
        thinking_levels=[],
        default_thinking="off",
        display_details="Qwen · agentic coding",
    ),
    # --- Nex AGI — large MoE with reasoning ---
    "nex-agi/nex-n2-pro:free": ModelInfo(
        display_name="Nex-N2-Pro",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="high",
        display_details="Nex AGI · 397B MoE 17B active",
    ),
    # --- NVIDIA — reasoning MoE models ---
    "nvidia/nemotron-3-ultra-550b-a55b:free": ModelInfo(
        display_name="Nemotron 3 Ultra",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="high",
        display_details="NVIDIA · 550B MoE 55B active",
    ),
    "nvidia/nemotron-3-super-120b-a12b:free": ModelInfo(
        display_name="Nemotron 3 Super",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="high",
        display_details="NVIDIA · 120B MoE 12B active",
    ),
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": ModelInfo(
        display_name="Nemotron 3 Nano Omni",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="NVIDIA · 30B MoE 3B active",
    ),
    # --- Google Gemma ---
    "google/gemma-4-31b-it:free": ModelInfo(
        display_name="Gemma 4 31B",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="Google · 31B dense",
    ),
    "google/gemma-4-26b-a4b-it:free": ModelInfo(
        display_name="Gemma 4 26B MoE",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="Google · 26B MoE 4B active",
    ),
    # --- OpenAI open-weight ---
    "openai/gpt-oss-120b:free": ModelInfo(
        display_name="GPT-OSS 120B",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="OpenAI · 117B MoE 5B active",
    ),
    "openai/gpt-oss-20b:free": ModelInfo(
        display_name="GPT-OSS 20B",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="OpenAI · 21B MoE 4B active",
    ),
    # --- Meta Llama ---
    "meta-llama/llama-3.3-70b-instruct:free": ModelInfo(
        display_name="Llama 3.3 70B",
        display_details="Meta · 70B dense",
    ),
    # --- OpenRouter auto-router ---
    "openrouter/free": ModelInfo(
        display_name="Free Auto Router",
        thinking_levels=_OPENROUTER_THINKING,
        default_thinking="medium",
        display_details="OpenRouter · auto-selects best free model",
    ),
}


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(self):
        self._credentials = CredentialStore("openrouter")

    async def authenticate(self, handler, ctx=None):
        if ctx is None:
            await handler("OpenRouter requires a UI context for API key input.")
            return

        await handler("Please enter your OpenRouter API key.")
        api_key = await ctx.input("OpenRouter API key")
        if not api_key:
            await handler("API key is required for OpenRouter.")
            return

        api_key = api_key.strip()
        self._credentials.set("api_key", api_key)
        self._credentials.save()
        await handler("OpenRouter API key saved successfully.")

    def is_authenticated(self) -> bool:
        return bool(self._credentials.get("api_key"))

    def should_reauthenticate(self) -> bool:
        return False

    async def reauthenticate(self):
        pass

    async def build_model(self, model_name: str) -> Model:
        api_key = self._credentials.get("api_key")
        if not api_key:
            raise ValueError("OpenRouter API key not configured — run /login")

        default_headers = {
            "HTTP-Referer": "https://github.com/juan/pana",
            "X-Title": "pana",
        }

        openai_client = AsyncOpenAI(
            base_url=BASE_URL,
            api_key=api_key,
            default_headers=default_headers,
        )
        info = MODEL_REGISTRY.get(model_name)
        strategy = _openrouter_thinking if info and info.thinking_levels else None
        client = OpenAICompletionsClient(openai_client, apply_thinking=strategy)
        return Model(model_name, client, self, info=info)

    def get_models(self) -> dict[str, ModelInfo]:
        return MODEL_REGISTRY
