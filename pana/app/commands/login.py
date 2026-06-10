"""``/login`` command — authenticates with a provider."""
from __future__ import annotations

from pana.ai.providers.factory import get_provider, get_providers
from pana.app.commands.base import Command
from pana.app.context import UIContext
from pana.state import state


class LoginCommand(Command):
    name = "login"
    aliases = []
    description = "Authenticate with a provider"

    async def execute(self, ctx: UIContext, args: str) -> None:
        providers = get_providers()
        if not providers:
            ctx.notify("No providers available.", "error")
            return

        chosen = await ctx.select("Select provider", list(providers))
        if chosen is None:
            return

        async def handler(message: str) -> None:
            ctx.notify(message, "muted")

        try:
            provider = get_provider(chosen)
            flow = provider.get_auth_flow()

            credentials: dict[str, str] | None = None
            if flow.fields:
                credentials = {}
                for field in flow.fields:
                    value = await ctx.input(f"{chosen}: {field.label}")
                    if value is None:
                        ctx.notify("Authentication cancelled.", "muted")
                        return
                    value = value.strip()
                    if not value:
                        ctx.notify(
                            f"{field.label} is required for {chosen}.", "error"
                        )
                        return
                    credentials[field.key] = value

            await provider.authenticate(handler, credentials)
            ctx.notify(
                f"Logged in to {chosen}. Use /model to select a model.",
                "success",
            )
        except Exception as e:
            ctx.notify(f"Auth failed: {e}", "error")
