"""Provider selection modal screen for the TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from app.config import AppConfig


class ProviderSelectionScreen(ModalScreen[str | None]):
    """Modal screen for selecting a provider to log in with."""

    CSS = """
    ProviderSelectionScreen {
        align: center middle;
    }

    #provider-dialog {
        width: 50;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    #provider-title {
        dock: top;
        width: 100%;
        margin-bottom: 1;
        text-align: center;
        color: $text;
    }

    #provider-buttons {
        width: 100%;
        height: auto;
    }

    Button {
        width: 100%;
        margin: 1 0;
    }

    Button:focus {
        background: $accent;
    }
    """

    def __init__(self, app_config: AppConfig):
        """Initialize the provider selection screen.
        
        Args:
            app_config: Application configuration with auth manager.
        """
        super().__init__()
        self.app_config = app_config

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        with Vertical(id="provider-dialog"):
            yield Static("Select Provider to Login", id="provider-title")
            
            with Vertical(id="provider-buttons"):
                providers = self.app_config.auth_manager.get_available_providers()
                
                if not providers:
                    yield Static("No providers available", id="no-providers")
                else:
                    for provider in providers:
                        is_logged_in = self.app_config.auth_manager.is_logged_in(provider)
                        status = "✓" if is_logged_in else "○"
                        label = f"{status} {provider.capitalize()}"
                        yield Button(label, id=f"btn-{provider}", variant="primary")
                
                yield Static("")  # Spacer
                yield Button("Cancel", id="btn-cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id
        
        if button_id == "btn-cancel":
            self.dismiss(None)
        elif button_id and button_id.startswith("btn-"):
            provider = button_id[4:]  # Remove "btn-" prefix
            self.dismiss(provider)
