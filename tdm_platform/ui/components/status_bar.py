from __future__ import annotations

from PySide6.QtWidgets import QStatusBar


class AppStatusBar(QStatusBar):
    """Thin named status bar wrapper for the modular main window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.showMessage("Kész")

    def set_ready(self, message: str = "Kész") -> None:
        self.showMessage(message)
