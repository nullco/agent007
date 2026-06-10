import pytest

from pana.ai.providers.openai_completions import OpenAICompletionsClient
from pana.ai.providers.openrouter.provider import (
    MODEL_REGISTRY,
    OpenRouterProvider,
    _openrouter_thinking,
)
from pana.ai.providers.provider import AuthFlow


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr("pana.ai.providers.auth.AUTH_DIR", tmp_path / "auth")
    return OpenRouterProvider()


class TestOpenRouterProvider:
    def test_name(self, provider):
        assert provider.name == "openrouter"

    def test_not_authenticated(self, provider):
        assert not provider.is_authenticated()

    def test_should_not_reauthenticate(self, provider):
        assert not provider.should_reauthenticate()

    def test_get_auth_flow(self, provider):
        flow = provider.get_auth_flow()
        assert isinstance(flow, AuthFlow)
        assert len(flow.fields) == 1
        assert flow.fields[0].key == "api_key"

    async def test_authenticate_with_key(self, provider):
        calls = []

        async def handler(msg):
            calls.append(("handler", msg))

        await provider.authenticate(handler, {"api_key": "test-api-key"})
        assert provider.is_authenticated()
        assert provider._credentials.get("api_key") == "test-api-key"

    async def test_authenticate_without_credentials(self, provider):
        calls = []

        async def handler(msg):
            calls.append(("handler", msg))

        await provider.authenticate(handler, None)
        assert not provider.is_authenticated()
        assert ("handler", "OpenRouter API key is required.") in calls

    async def test_authenticate_empty_key(self, provider):
        calls = []

        async def handler(msg):
            calls.append(("handler", msg))

        await provider.authenticate(handler, {"api_key": ""})
        assert not provider.is_authenticated()
        assert ("handler", "API key is required for OpenRouter.") in calls

    def test_get_models(self, provider):
        models = provider.get_models()
        assert models == MODEL_REGISTRY

    async def test_build_model(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.save()

        model = await provider.build_model("google/gemma-4-31b-it:free")
        assert model.name == "google/gemma-4-31b-it:free"
        assert model.provider == provider
        assert model.info is not None
        assert model.display_name == "Gemma 4 31B"
        assert isinstance(model.client, OpenAICompletionsClient)

    async def test_build_model_unauthenticated(self, provider):
        with pytest.raises(ValueError, match="OpenRouter API key not configured"):
            await provider.build_model("google/gemma-4-31b-it:free")

    def test_model_registry_has_expected_models(self, provider):
        models = provider.get_models()
        expected_ids = {
            "poolside/laguna-m.1:free",
            "poolside/laguna-xs.2:free",
            "qwen/qwen3-coder:free",
            "nex-agi/nex-n2-pro:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "openai/gpt-oss-120b:free",
            "openai/gpt-oss-20b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "openrouter/free",
        }
        assert set(models.keys()) == expected_ids

    def test_thinking_modes(self, provider):
        models = provider.get_models()
        # Models with thinking use openrouter mode by default
        assert models["nvidia/nemotron-3-ultra-550b-a55b:free"].thinking_mode == "reasoning_effort"
        # Qwen3 Coder has no thinking
        assert models["qwen/qwen3-coder:free"].thinking_levels == []
        assert models["qwen/qwen3-coder:free"].default_thinking == "off"
        # Llama 3.3 has no thinking
        assert models["meta-llama/llama-3.3-70b-instruct:free"].thinking_levels == []

    def test_thinking_levels_present(self, provider):
        models = provider.get_models()
        thinking_models = [
            "poolside/laguna-m.1:free",
            "poolside/laguna-xs.2:free",
            "nex-agi/nex-n2-pro:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "openai/gpt-oss-120b:free",
            "openai/gpt-oss-20b:free",
            "openrouter/free",
        ]
        for mid in thinking_models:
            assert models[mid].thinking_levels == ["low", "medium", "high"], f"{mid} missing thinking_levels"

    async def test_build_model_thinking_client(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.save()

        model = await provider.build_model("google/gemma-4-31b-it:free")
        assert model.client._apply_thinking_fn is _openrouter_thinking

    async def test_build_model_non_thinking_client(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.save()

        model = await provider.build_model("qwen/qwen3-coder:free")
        # No thinking strategy given -> defaults to reasoning_effort
        assert model.client._apply_thinking_fn is not _openrouter_thinking

    async def test_default_headers_set(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.save()

        model = await provider.build_model("openai/gpt-oss-120b:free")
        client = model.client
        assert client._client.default_headers["HTTP-Referer"] == "https://github.com/juan/pana"
        assert client._client.default_headers["X-Title"] == "pana"
