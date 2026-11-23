"""Desktop app entry point (CustomTkinter, dark theme)."""
from __future__ import annotations


def main(config_path: str = "endpoints.yaml", demo: bool = False) -> None:
    from .ui.app import main as run
    run(config_path, demo=demo)
