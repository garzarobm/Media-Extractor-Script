"""
Extensibility system through hooks.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from .config import Operation

HookName = Literal[
    "before_classify",
    "after_classify",
    "before_transfer",
    "after_transfer",
    "on_skip",
    "on_error",
]
HookHandler = Callable[["FileOperationContext"], None]
HOOK_NAMES: tuple[HookName, ...] = (
    "before_classify",
    "after_classify",
    "before_transfer",
    "after_transfer",
    "on_skip",
    "on_error",
)


@dataclass
class FileOperationContext:
    """
    Context for a single file operation, passed to hook handlers.
    """
    source_path: Path
    destination_root: Path
    operation: Operation
    dry_run: bool = False
    category: str | None = None
    destination_path: Path | None = None
    tags: list[Any] = field(default_factory=list)
    original_tags: tuple[Any, ...] = field(default_factory=tuple)
    skip_reason: str | None = None
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tags_changed(self) -> bool:
        return list(self.original_tags) != list(self.tags)

    def skip(self, reason: str) -> None:
        self.skip_reason = reason

    def set_destination_path(self, value: Path) -> None:
        self.destination_path = Path(value)

    def rename_destination(self, new_name: str) -> None:
        if self.destination_path is None:
            raise ValueError("Destination path is not set yet.")
        self.destination_path = self.destination_path.with_name(new_name)

    def update_tags(self, tags: Iterable[Any]) -> None:
        self.tags = list(tags)

    def add_tag(self, tag: Any) -> None:
        self.tags.append(tag)


class HookRegistry:
    """
    Registry for hook handlers.
    """
    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = {name: [] for name in HOOK_NAMES}

    def add(self, name: HookName, handler: HookHandler) -> None:
        self._handlers[name].append(handler)

    def extend(self, other: "HookRegistry") -> None:
        for name in HOOK_NAMES:
            self._handlers[name].extend(other._handlers[name])

    def dispatch(self, name: HookName, context: FileOperationContext) -> None:
        for handler in self._handlers[name]:
            handler(context)


def load_hooks_from_module(reference: str) -> HookRegistry:
    """
    Loads hooks from a Python module or file.
    """
    module = _load_module(reference)
    registry = HookRegistry()

    register = getattr(module, "register_hooks", None)
    if callable(register):
        register(registry)

    hooks = getattr(module, "HOOKS", None)
    if isinstance(hooks, Mapping):
        _register_mapping_hooks(registry, hooks)

    for name in HOOK_NAMES:
        handler = getattr(module, name, None)
        if callable(handler):
            registry.add(name, handler)

    return registry


def _register_mapping_hooks(
    registry: HookRegistry,
    hooks: Mapping[str, HookHandler | Iterable[HookHandler]],
) -> None:
    for name, handler_or_handlers in hooks.items():
        if name not in HOOK_NAMES:
            continue
        if callable(handler_or_handlers):
            registry.add(name, handler_or_handlers)
            continue
        for handler in handler_or_handlers:
            registry.add(name, handler)


def _load_module(reference: str) -> ModuleType:
    path = Path(reference).expanduser()
    if path.exists():
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load hooks module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(reference)