from dataclasses import dataclass, field
from typing import Protocol

from pana.ai.providers.model import Model, ModelInfo


@dataclass
class AuthPrompt:
    """Describes a credential field the provider needs."""

    key: str
    label: str
    placeholder: str = ""
    sensitive: bool = True


@dataclass
class AuthFlow:
    """Describes the credential fields a provider requires for authentication.

    If ``fields`` is non-empty the caller should collect each via UI and
    pass the resulting ``{key: value}`` dict to :meth:`Provider.authenticate`.
    If ``fields`` is empty the provider handles auth internally (e.g. OAuth
    device flow) and the caller only supplies the ``handler`` callback.
    """

    fields: list[AuthPrompt] = field(default_factory=list)


class Provider(Protocol):

    name: str

    def get_auth_flow(self) -> AuthFlow:
        ...

    async def authenticate(self, handler, credentials: dict[str, str] | None = None):
        ...

    async def reauthenticate(self):
        ...

    def is_authenticated(self) -> bool:
        ...

    def should_reauthenticate(self) -> bool:
        ...

    async def build_model(self, model_name: str) -> Model:
        ...

    def get_models(self) -> dict[str, ModelInfo]:
        ...
