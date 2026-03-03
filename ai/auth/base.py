"""Base authenticator protocol for multi-provider authentication."""

from __future__ import annotations

from typing import Optional, Protocol, Tuple


class Authenticator(Protocol):
    """Protocol for authentication implementations across different providers.
    
    All authenticators must implement these methods to support:
    - Starting login flows (OAuth, API keys, etc.)
    - Polling for completion (for async flows like device code)
    - Token refresh and expiration
    - Logout and status checks
    """

    def start_login(self) -> Tuple[bool, str]:
        """Start the authentication flow.
        
        Returns:
            Tuple of (success: bool, message: str)
            - success: True if flow started successfully
            - message: User-facing message (may contain instructions like URLs or codes)
        """
        ...

    def poll_for_token(self) -> Tuple[bool, str]:
        """Poll for token completion (for async auth flows like device code).
        
        This blocks until the user completes auth or timeout occurs.
        
        Returns:
            Tuple of (success: bool, message: str)
            - success: True if tokens obtained
            - message: User-facing status/result message
        """
        ...

    def is_logged_in(self) -> bool:
        """Check if user is currently logged in."""
        ...

    def get_status(self) -> str:
        """Get human-readable login status (e.g., "Logged in as: username")."""
        ...

    def logout(self) -> str:
        """Log out and clear tokens.
        
        Returns:
            User-facing status message.
        """
        ...

    def refresh_token(self) -> bool:
        """Refresh token if expired.
        
        Returns:
            True if token was refreshed, False if already valid or refresh failed.
        """
        ...

    def is_token_expired(self) -> bool:
        """Check if the current token has expired."""
        ...
