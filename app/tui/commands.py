"""Command handlers for the TUI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import AppConfig

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles slash commands in the TUI."""

    def __init__(self, app_config: AppConfig):
        """Initialize the command handler.
        
        Args:
            app_config: Application configuration with agent and authenticators.
        """
        self.app_config = app_config
        self.agent = app_config.agent

    async def handle_login(self, provider_name: str = "") -> str | None:
        """Handle /login command.
        
        Usage:
            /login              - Show list of available providers
            /login copilot      - Log in with GitHub Copilot
            /login openai       - Log in with OpenAI
        """
        provider_name = provider_name.strip().lower()
        
        # If no provider specified, show available providers
        if not provider_name:
            available = self.app_config.auth_manager.get_available_providers()
            if not available:
                return "[Login] No providers available."
            
            # Always show list when no provider is specified
            message = "[Login] Available providers:\n"
            for provider in available:
                status = "✓" if self.app_config.auth_manager.is_logged_in(provider) else "○"
                message += f"  {status} {provider}\n"
            message += "\nUse: /login <provider_name>"
            return message
        
        # Get authenticator for the specified provider
        authenticator = self.app_config.get_authenticator(provider_name)
        if not authenticator:
            available = self.app_config.auth_manager.get_available_providers()
            if available:
                available_str = ", ".join(available)
                return f"[Login] Provider '{provider_name}' not found.\n\nAvailable providers: {available_str}\n\nUsage: /login <provider>"
            return f"[Login] Provider '{provider_name}' not found and no providers available."
        
        try:
            ok, msg = authenticator.start_login()
            return msg
        except Exception as e:
            logger.error("Login failed: %s", e)
            return f"[Login] Failed: {e}"

    async def handle_logout(self, provider_name: str = "") -> str | None:
        """Handle /logout command.
        
        Usage:
            /logout              - Log out from the current provider
            /logout copilot      - Log out from GitHub Copilot
            /logout openai       - Log out from OpenAI
        """
        provider_name = provider_name.strip().lower()
        
        # If no provider specified, use current provider
        if not provider_name:
            provider_name = self.app_config.ai_manager.provider_name()
        
        authenticator = self.app_config.get_authenticator(provider_name)
        if not authenticator:
            return f"[Logout] Provider '{provider_name}' not found or has no authenticator."
        
        try:
            return authenticator.logout()
        except Exception as e:
            logger.error("Logout failed: %s", e)
            return f"[Logout] Failed: {e}"

    async def handle_status(self, provider_name: str = "") -> str | None:
        """Handle /status command.
        
        Usage:
            /status              - Show status for the current provider
            /status copilot      - Show status for GitHub Copilot
            /status openai       - Show status for OpenAI
            /status all          - Show status for all providers
        """
        provider_name = provider_name.strip().lower()
        
        # If "all" specified, show status for all providers
        if provider_name == "all":
            return self.app_config.auth_manager.get_login_status()
        
        # If no provider specified, use current provider
        if not provider_name:
            provider_name = self.app_config.ai_manager.provider_name()
        
        authenticator = self.app_config.get_authenticator(provider_name)
        if not authenticator:
            return f"[Status] Provider '{provider_name}' not found or has no authenticator."
        
        try:
            status = authenticator.get_status()
            return f"[{provider_name}] {status}"
        except Exception as e:
            logger.error("Status check failed: %s", e)
            return f"[Status] Failed: {e}"

    async def handle_clear(self) -> str | None:
        """Handle /clear command."""
        try:
            self.agent.clear_history()
            return "[Agent] Chat history cleared."
        except Exception as e:
            logger.error("Clear history failed: %s", e)
            return f"[Commands] Clear failed: {e}"

    async def handle_model(self, args: str = "") -> str | None:
        """Handle /model command.
        
        Usage:
            /model              - Show available models from all providers
            /model <id>         - Select a model (switches to its provider)
        """
        args = args.strip().lower()
        
        if not args:
            # List available models from all providers
            try:
                models = self.app_config.ai_manager.get_all_models()
                current = self.app_config.ai_manager.get_current_model()
                current_provider = self.app_config.ai_manager.provider_name()
                
                if not models:
                    return "[Model] No models available. You may need to log in first."
                
                model_lines = []
                for m in models:
                    model_id = m.get("id", "unknown")
                    model_name = m.get("name", model_id)
                    provider = m.get("provider", "unknown")
                    is_current = "→" if (model_id == current and provider == current_provider) else " "
                    enabled = " (enabled)" if m.get("enabled") else ""
                    requires_policy = " (requires acceptance)" if m.get("requires_policy") else ""
                    
                    model_lines.append(
                        f"  {is_current} {model_id:<20} {model_name:<25} [{provider}]{enabled}{requires_policy}"
                    )
                
                model_list = "\n".join(model_lines)
                return f"[Model] Current: {current} ({current_provider})\n\nAvailable:\n{model_list}\n\nUse: /model <id>"
            except Exception as e:
                logger.debug("Failed to list models: %s", e)
                return f"[Model] Failed to list models: {e}"
        
        # Find model by ID and switch to its provider
        try:
            all_models = self.app_config.ai_manager.get_all_models()
            selected_model = None
            
            for m in all_models:
                if m.get("id", "").lower() == args or m.get("name", "").lower() == args:
                    selected_model = m
                    break
            
            if not selected_model:
                return f"[Model] Model not found: {args}\n\nTry /model to see available options."
            
            provider = selected_model.get("provider")
            model_id = selected_model.get("id")
            
            # Switch provider
            if not self.app_config.ai_manager.switch_provider(provider):
                return f"[Model] Failed to switch to provider: {provider}"
            
            # Select model in the new provider
            if not self.app_config.ai_manager.select_model(model_id):
                return f"[Model] Failed to select model: {model_id}"
            
            # Rebuild agent with new provider and model
            self.app_config.rebuild_agent()
            
            return f"[Model] Switched to: {model_id} (provider: {provider})"
        except Exception as e:
            logger.error("Model selection failed: %s", e)
            return f"[Commands] Model selection failed: {e}"

    async def handle_command(self, cmd: str) -> str | None:
        """Handle a slash command.
        
        Args:
            cmd: Command string (e.g., "/login", "/status").
            
        Returns:
            Message to display, or None.
        """
        cmd = cmd.strip()
        
        # Parse command and arguments
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if command == "/login":
            return await self.handle_login(args)
        elif command == "/logout":
            return await self.handle_logout(args)
        elif command == "/status":
            return await self.handle_status(args)
        elif command == "/clear":
            return await self.handle_clear()
        elif command == "/model":
            return await self.handle_model(args)
        else:
            return "[Commands] Unknown command."
