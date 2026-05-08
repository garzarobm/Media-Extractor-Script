"""
macOS Finder tags management.
"""

from __future__ import annotations

import importlib
import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Protocol, Sequence


class TagManager(Protocol):
    """
    Protocol for managing file tags.
    """
    available: bool
    reason_unavailable: str | None

    def ensure_available(self) -> None: ...

    def get_tags(self, file_path: Path) -> list[Any]: ...

    def set_tags(self, file_path: Path, tags: Sequence[Any]) -> None: ...


class MacOSTagManager:
    """
    Manages macOS Finder tags, using various backends as fallbacks.
    """
    def __init__(self) -> None:
        self.available = False
        self.reason_unavailable: str | None = None
        self._backend: Any | None = None
        try:
            self._backend = _ImportedMacOSTagsBackend(_import_macos_tags())
            self.available = True
        except Exception as import_error:
            try:
                self._backend = _StandardLibraryMacOSTagsBackend()
                self.available = True
            except Exception as stdlib_error:
                try:
                    self._backend = _CliMacOSTagsBackend()
                    self.available = True
                except Exception as cli_error:  # pragma: no cover - platform specific
                    self.reason_unavailable = (
                        f"{import_error}; stdlib fallback failed: {stdlib_error}; "
                        f"CLI fallback failed: {cli_error}"
                    )

    def ensure_available(self) -> None:
        if self.available:
            return
        message = self.reason_unavailable or "macos_tags is unavailable"
        raise RuntimeError(message)

    def get_tags(self, file_path: Path) -> list[Any]:
        self.ensure_available()
        return list(self._backend.get_tags(file_path))

    def set_tags(self, file_path: Path, tags: Sequence[Any]) -> None:
        self.ensure_available()
        self._backend.set_tags(file_path, list(tags))


class _ImportedMacOSTagsBackend:
    def __init__(self, module: Any) -> None:
        self._module = module

    def get_tags(self, file_path: Path) -> list[Any]:
        return list(self._module.get_all(str(file_path)))

    def set_tags(self, file_path: Path, tags: Sequence[Any]) -> None:
        self._module.set_all(list(tags), file=str(file_path))


@dataclass(frozen=True)
class _FallbackTag:
    name: str
    color: int = 0

    def __str__(self) -> str:
        return f"{self.name}\n{self.color}"

    @classmethod
    def from_string(cls, tag: str) -> "_FallbackTag":
        if "\n" not in tag:
            return cls(name=tag, color=0)
        name, color = tag.splitlines()
        return cls(name=name, color=int(color))


class _FallbackColor(IntEnum):
    NONE = 0
    GRAY = 1
    GREEN = 2
    PURPLE = 3
    BLUE = 4
    YELLOW = 5
    RED = 6
    ORANGE = 7


class _StandardLibraryMacOSTagsBackend:
    _XATTR_TAGS = "com.apple.metadata:_kMDItemUserTags"
    _XATTR_FINDER_INFO = "com.apple.FinderInfo"

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("Finder tag support requires macOS.")
        required = ("getxattr", "setxattr", "listxattr", "removexattr")
        missing = [name for name in required if not hasattr(os, name)]
        if missing:
            missing_names = ", ".join(missing)
            raise RuntimeError(f"Missing xattr functions in os module: {missing_names}")

    def get_tags(self, file_path: Path) -> list[_FallbackTag]:
        try:
            plist = os.getxattr(str(file_path), self._XATTR_TAGS)
        except OSError:
            return []
        raw_tags = plistlib.loads(plist)
        return [_FallbackTag.from_string(tag) for tag in raw_tags]

    def set_tags(self, file_path: Path, tags: Sequence[Any]) -> None:
        self._remove_finder_info(file_path)
        serialized_tags = [self._serialize_tag(tag) for tag in tags]
        plist = plistlib.dumps(serialized_tags)
        os.setxattr(str(file_path), self._XATTR_TAGS, plist)

    def _remove_finder_info(self, file_path: Path) -> None:
        attributes = os.listxattr(str(file_path))
        if self._XATTR_FINDER_INFO in attributes:
            os.removexattr(str(file_path), self._XATTR_FINDER_INFO)

    def _serialize_tag(self, tag: Any) -> str:
        if isinstance(tag, str):
            return str(_FallbackTag.from_string(tag))
        name = getattr(tag, "name", None)
        color = getattr(tag, "color", _FallbackColor.NONE)
        if name is None:
            raise TypeError(f"Unsupported tag value: {tag!r}")
        try:
            color_value = int(color)
        except TypeError:
            color_value = int(getattr(color, "value", 0))
        return str(_FallbackTag(name=name, color=color_value))


class _CliMacOSTagsBackend(_StandardLibraryMacOSTagsBackend):
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("Finder tag support requires macOS.")
        if shutil.which("xattr") is None:
            raise RuntimeError("The xattr command-line tool is not available.")

    def get_tags(self, file_path: Path) -> list[_FallbackTag]:
        result = subprocess.run(
            ["xattr", "-px", self._XATTR_TAGS, str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No such xattr" in stderr:
                return []
            raise RuntimeError(stderr or "Failed to read Finder tags via xattr")

        raw_value = "".join(result.stdout.split())
        if not raw_value:
            return []

        raw_tags = plistlib.loads(bytes.fromhex(raw_value))
        return [_FallbackTag.from_string(tag) for tag in raw_tags]

    def set_tags(self, file_path: Path, tags: Sequence[Any]) -> None:
        self._remove_finder_info(file_path)
        serialized_tags = [self._serialize_tag(tag) for tag in tags]
        plist = plistlib.dumps(serialized_tags).hex()
        result = subprocess.run(
            ["xattr", "-wx", self._XATTR_TAGS, plist, str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(stderr or "Failed to write Finder tags via xattr")

    def _remove_finder_info(self, file_path: Path) -> None:
        list_result = subprocess.run(
            ["xattr", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if list_result.returncode != 0:
            stderr = list_result.stderr.strip()
            raise RuntimeError(stderr or "Failed to list xattrs via xattr")

        attributes = {line.strip() for line in list_result.stdout.splitlines() if line.strip()}
        if self._XATTR_FINDER_INFO not in attributes:
            return

        remove_result = subprocess.run(
            ["xattr", "-d", self._XATTR_FINDER_INFO, str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if remove_result.returncode != 0:
            stderr = remove_result.stderr.strip()
            raise RuntimeError(stderr or "Failed to remove FinderInfo via xattr")


def _import_macos_tags() -> Any:
    try:
        return importlib.import_module("macos_tags")
    except ModuleNotFoundError:
        vendor_root = Path(__file__).resolve().parents[1] / "macos-tags-master"
        if vendor_root.exists() and str(vendor_root) not in sys.path:
            sys.path.insert(0, str(vendor_root))
        try:
            return importlib.import_module("macos_tags")
        except ModuleNotFoundError as error:
            missing_name = error.name or "dependency"
            raise RuntimeError(
                "macos_tags could not be imported. Install the bundled project "
                f"dependencies first. Missing module: {missing_name}"
            ) from error
    except RuntimeError as error:
        raise RuntimeError("macos_tags is available only on macOS.") from error