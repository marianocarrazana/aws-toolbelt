"""Entry point for the ``aws-toolbelt`` package."""

from .main import App


def main() -> None:
    """Launch the Textual application."""
    app = App()
    app.run()
