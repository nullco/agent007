"""Multi-provider authentication support."""

from .base import Authenticator
from .manager import AuthManager

__all__ = ["Authenticator", "AuthManager"]
