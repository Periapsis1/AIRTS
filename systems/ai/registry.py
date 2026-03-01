"""AI registry — auto-discovers BaseAI subclasses from systems/ai/ and ais/."""
from __future__ import annotations
import importlib
import inspect
import os
import sys
from pathlib import Path
from systems.ai.base import BaseAI


class AIRegistry:
    """Scans directories for BaseAI subclasses and provides factory access."""

    def __init__(self):
        self._registry: dict[str, type[BaseAI]] = {}
        self.errors: list[str] = []

    def discover(self) -> None:
        """Scan built-in and user AI directories."""
        project_root = Path(__file__).resolve().parent.parent.parent
        builtin_dir = project_root / "systems" / "ai"
        user_dir = project_root / "ais"

        self._scan_dir(builtin_dir, "systems.ai")
        if user_dir.is_dir():
            self._scan_dir(user_dir, "ais")

    def _scan_dir(self, directory: Path, package: str) -> None:
        for filepath in directory.glob("*.py"):
            if filepath.name.startswith("_"):
                continue
            module_name = f"{package}.{filepath.stem}"
            try:
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                else:
                    module = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseAI)
                            and obj is not BaseAI
                            and getattr(obj, "ai_id", "")):
                        self._registry[obj.ai_id] = obj
            except Exception as exc:
                self.errors.append(f"{filepath.name}: {exc}")

    def get_choices(self) -> list[tuple[str, str]]:
        """Return (ai_id, ai_name) pairs sorted by name."""
        return sorted(
            [(cls.ai_id, cls.ai_name or cls.ai_id)
             for cls in self._registry.values()],
            key=lambda t: t[1],
        )

    def create(self, ai_id: str) -> BaseAI:
        """Instantiate an AI by its id."""
        cls = self._registry[ai_id]
        return cls()
