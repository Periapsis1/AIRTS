"""AI registry — auto-discovers BaseAI subclasses from systems/ai/ and ais/."""
from __future__ import annotations
import importlib
import inspect
import os
import pkgutil
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
        # Built-in AIs (always available, works in frozen builds via pkgutil)
        self._scan_package("systems.ai")

        # User AIs — try as a package first (frozen build), then scan loose files
        self._scan_package("ais")
        self._scan_loose_ais()

    def _scan_package(self, package: str) -> None:
        """Discover AI modules within an importable package using pkgutil."""
        try:
            pkg = importlib.import_module(package)
        except ImportError:
            return

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            return

        for importer, module_name, is_pkg in pkgutil.iter_modules(pkg_path):
            if module_name.startswith("_"):
                continue
            full_name = f"{package}.{module_name}"
            self._try_load(full_name)

    def _scan_loose_ais(self) -> None:
        """Scan for .py files in an ais/ folder next to the exe (user-added AIs)."""
        from core.paths import app_path
        user_dir = Path(app_path("ais"))
        if not user_dir.is_dir():
            return

        parent = str(user_dir.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for filepath in user_dir.glob("*.py"):
            if filepath.name.startswith("_"):
                continue
            module_name = f"ais.{filepath.stem}"
            # Skip if already loaded via _scan_package
            if module_name in sys.modules:
                self._register_from_module(sys.modules[module_name])
                continue
            self._try_load(module_name)

    def _try_load(self, module_name: str) -> None:
        """Import a module and register any BaseAI subclasses found."""
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                module = importlib.import_module(module_name)
            self._register_from_module(module)
        except Exception as exc:
            self.errors.append(f"{module_name}: {exc}")

    def _register_from_module(self, module) -> None:
        """Register all BaseAI subclasses in the given module."""
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, BaseAI)
                    and obj is not BaseAI
                    and getattr(obj, "ai_id", "")):
                self._registry[obj.ai_id] = obj

    def get_choices(self, include_deprecated: bool = False) -> list[tuple[str, str]]:
        """Return (ai_id, ai_name) pairs sorted by name.

        Deprecated AIs are excluded by default; pass ``include_deprecated=True``
        to get every registered AI (e.g. for the lobby's "Show Outdated AIs"
        toggle).
        """
        return sorted(
            [(cls.ai_id, cls.ai_name or cls.ai_id)
             for cls in self._registry.values()
             if include_deprecated or not getattr(cls, "deprecated", False)],
            key=lambda t: t[1],
        )

    def get_deprecated_ids(self) -> set[str]:
        """Return the set of ai_ids that are marked deprecated."""
        return {cls.ai_id for cls in self._registry.values()
                if getattr(cls, "deprecated", False)}

    def create(self, ai_id: str) -> BaseAI:
        """Instantiate an AI by its id."""
        cls = self._registry[ai_id]
        return cls()
