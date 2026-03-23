"""UI layer wrappers and extracted Qt widgets for the TDM platform."""

from .auth_dialog import AuthDialog
from .main_window import MainWindow, run_app

__all__ = ["AuthDialog", "MainWindow", "run_app"]
