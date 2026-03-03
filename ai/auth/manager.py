"""Authentication manager for multi-provider support."""

from __future__ import annotations

import logging
from typing import Optional

from ai.auth.base import Authenticator
from ai.providers.factory import get_provider, AVAILABLE_PROVIDERS

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages authenticators for all available providers.
    
    Allows users to authenticate with any provider without switching
    the active provider. This enables scenarios like having multiple
    providers' tokens available simultaneously.
    """

    def __init__(self):
        """Initialize the auth manager."""
        self._authenticators: dict[str, Authenticator] = {}
        self._current_provider: str | None = None

    def get_authenticator(self, provider_name: str) -> Optional[Authenticator]:
        """Get or create authenticator for a provider.
        
        Args:
            provider_name: Name of the provider (e.g., 'copilot', 'openai')
            
        Returns:
            Authenticator instance, or None if provider doesn't have auth.
        """
        if provider_name not in AVAILABLE_PROVIDERS:
            logger.warning("Unknown provider: %s", provider_name)
            return None

        # Cache authenticators to maintain state
        if provider_name not in self._authenticators:
            try:
                provider = get_provider(provider_name)
                auth = provider.get_authenticator()
                if auth:
                    self._authenticators[provider_name] = auth
                    logger.debug("Created authenticator for provider: %s", provider_name)
            except Exception as e:
                logger.error("Failed to get authenticator for %s: %s", provider_name, e)
                return None

        return self._authenticators.get(provider_name)

    def get_all_authenticators(self) -> dict[str, Authenticator]:
        """Get all cached authenticators.
        
        Returns:
            Dictionary mapping provider names to authenticators.
        """
        return self._authenticators.copy()

    def get_available_providers(self) -> list[str]:
        """Get list of available providers.
        
        Returns:
            List of provider names that support authentication.
        """
        available = []
        for provider_name in AVAILABLE_PROVIDERS:
            if self.get_authenticator(provider_name):
                available.append(provider_name)
        return available

    def has_authenticator(self, provider_name: str) -> bool:
        """Check if a provider has an authenticator.
        
        Args:
            provider_name: Name of the provider.
            
        Returns:
            True if provider has an authenticator, False otherwise.
        """
        return self.get_authenticator(provider_name) is not None

    def is_logged_in(self, provider_name: str) -> bool:
        """Check if user is logged in to a provider.
        
        Args:
            provider_name: Name of the provider.
            
        Returns:
            True if logged in, False otherwise.
        """
        auth = self.get_authenticator(provider_name)
        if not auth:
            return False
        return auth.is_logged_in()

    def get_login_status(self, provider_name: Optional[str] = None) -> str:
        """Get login status for one or all providers.
        
        Args:
            provider_name: If provided, get status for this provider.
                          If None, get status for all providers.
            
        Returns:
            Human-readable status message.
        """
        if provider_name:
            auth = self.get_authenticator(provider_name)
            if not auth:
                return f"[Auth] Provider '{provider_name}' not found or has no authenticator."
            return auth.get_status()

        # Get status for all providers
        statuses = []
        for name in AVAILABLE_PROVIDERS:
            auth = self.get_authenticator(name)
            if auth:
                status = auth.get_status()
                statuses.append(f"  {name:<15} {status}")

        if not statuses:
            return "[Auth] No authenticators available."

        return "[Auth] Status for all providers:\n" + "\n".join(statuses)
