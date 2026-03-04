"""Command palette providers for login and model selection."""

from __future__ import annotations

import logging
from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider

logger = logging.getLogger(__name__)


class LoginProvider(Provider):
    """Command provider for selecting a login provider."""

    async def discover(self) -> Hits:
        from app.tui.app import CodingAgentApp

        app = self.app
        if not isinstance(app, CodingAgentApp):
            return

        auth_manager = app.app_config.auth_manager
        providers = auth_manager.get_available_providers()

        for provider_name in providers:
            is_logged_in = auth_manager.is_logged_in(provider_name)
            status = "✓" if is_logged_in else "○"
            display = f"{status} {provider_name}"
            yield DiscoveryHit(
                display,
                partial(app._login_with_provider_sync, provider_name),
                help=f"Authenticate with {provider_name}",
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self.app

        from app.tui.app import CodingAgentApp

        if not isinstance(app, CodingAgentApp):
            return

        auth_manager = app.app_config.auth_manager
        providers = auth_manager.get_available_providers()

        for provider_name in providers:
            is_logged_in = auth_manager.is_logged_in(provider_name)
            status = "✓" if is_logged_in else "○"
            command = f"{status} {provider_name}"
            score = matcher.match(command)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command),
                    partial(app._login_with_provider_sync, provider_name),
                    help=f"Authenticate with {provider_name}",
                )


class ModelProvider(Provider):
    """Command provider for selecting a model."""

    async def startup(self) -> None:
        from app.tui.app import CodingAgentApp

        app = self.app
        if not isinstance(app, CodingAgentApp):
            self._models = []
            return

        worker = app.run_worker(
            partial(app.app_config.ai_manager.get_all_models), thread=True
        )
        self._models = await worker.wait()

    async def discover(self) -> Hits:
        from app.tui.app import CodingAgentApp

        app = self.app
        if not isinstance(app, CodingAgentApp):
            return

        current = app.app_config.ai_manager.get_current_model()
        current_provider = app.app_config.ai_manager.provider_name()

        for model in self._models:
            model_id = model.get("id", "unknown")
            provider = model.get("provider", "unknown")
            is_current = "→" if (model_id == current and provider == current_provider) else " "
            display = f"{is_current} {model_id} ({provider})"
            yield DiscoveryHit(
                display,
                partial(app._select_model, model_id, provider)
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self.app

        from app.tui.app import CodingAgentApp

        if not isinstance(app, CodingAgentApp):
            return

        current = app.app_config.ai_manager.get_current_model()
        current_provider = app.app_config.ai_manager.provider_name()

        for model in self._models:
            model_id = model.get("id", "unknown")
            provider = model.get("provider", "unknown")
            is_current = "→" if (model_id == current and provider == current_provider) else " "
            command = f"{is_current} {model_id} ({provider})"
            score = matcher.match(command)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command),
                    partial(app._select_model, model_id, provider)
                )
