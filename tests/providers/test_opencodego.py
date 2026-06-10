import pytest

from pana.ai.providers.openai_completions import OpenAICompletionsClient
from pana.ai.providers.opencodego.provider import MODEL_REGISTRY, OpenCodeGoProvider
from pana.ai.providers.provider import AuthFlow


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr("pana.ai.providers.auth.AUTH_DIR", tmp_path / "auth")
    return OpenCodeGoProvider()


class TestOpenCodeGoProvider:
    def test_name(self, provider):
        assert provider.name == "opencodego"

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
        assert ("handler", "OpenCode Go API key is required.") in calls

    async def test_authenticate_empty_key(self, provider):
        calls = []

        async def handler(msg):
            calls.append(("handler", msg))

        await provider.authenticate(handler, {"api_key": ""})
        assert not provider.is_authenticated()
        assert ("handler", "API key is required for OpenCode Go.") in calls

    def test_get_models(self, provider):
        models = provider.get_models()
        assert models == MODEL_REGISTRY

    async def test_build_model(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.set("base_url", "https://custom.example.com")
        provider._credentials.save()

        model = await provider.build_model("kimi-k2.6")
        assert model.name == "kimi-k2.6"
        assert model.provider == provider
        assert model.info is not None
        assert model.display_name == "Kimi K2.6"
        assert isinstance(model.client, OpenAICompletionsClient)

    async def test_build_model_unauthenticated(self, provider):
        with pytest.raises(ValueError, match="OpenCode Go API key not configured"):
            await provider.build_model("kimi-k2.6")

    def test_model_registry_has_expected_models(self, provider):
        models = provider.get_models()
        expected_ids = {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "glm-5",
            "glm-5.1",
            "kimi-k2.5",
            "kimi-k2.6",
            "mimo-v2.5",
            "mimo-v2.5-pro",
            "minimax-m2.7",
            "qwen3.6-plus",
        }
        assert set(models.keys()) == expected_ids

    def test_thinking_modes(self, provider):
        models = provider.get_models()
        assert models["deepseek-v4-flash"].thinking_mode == "deepseek"
        assert models["kimi-k2.6"].thinking_mode == "deepseek"
        assert models["qwen3.6-plus"].thinking_mode == "qwen"
        assert models["kimi-k2.5"].thinking_mode == "reasoning_effort"

    async def test_build_model_sets_thinking_mode(self, provider):
        provider._credentials.set("api_key", "test-key")
        provider._credentials.save()

        from pana.ai.providers.opencodego.provider import _qwen_thinking

        model = await provider.build_model("qwen3.6-plus")
        assert model.info is not None
        assert model.info.thinking_mode == "qwen"
        assert model.client._apply_thinking_fn is _qwen_thinking
