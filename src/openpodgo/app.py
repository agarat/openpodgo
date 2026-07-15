"""Entry point for the PodGo Lab application."""

from __future__ import annotations


def main() -> int:
    from .ui.main_window import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
