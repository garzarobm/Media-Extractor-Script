"""
Configuration models for the media organizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Operation(str, Enum):
    """
    Specifies the file transfer operation.
    """
    COPY = "copy"
    MOVE = "move"

    @classmethod
    def from_value(cls, value: str) -> "Operation":
        normalized = value.strip().lower()
        if normalized in {"1", "copy", "c"}:
            return cls.COPY
        if normalized in {"0", "move", "m"}:
            return cls.MOVE
        raise ValueError(f"Unsupported operation: {value}")


class CollisionPolicy(str, Enum):
    """
    Specifies how to handle file name collisions at the destination.
    """
    SKIP = "skip"
    RENAME = "rename"
    OVERWRITE = "overwrite"

    @classmethod
    def from_value(cls, value: str) -> "CollisionPolicy":
        normalized = value.strip().lower()
        try:
            return cls(normalized)
        except ValueError as error:
            raise ValueError(f"Unsupported collision policy: {value}") from error


@dataclass
class OrganizerConfig:
    """
    Configuration for the media organization process.
    """
    source: Path
    destination: Path
    operation: Operation = Operation.COPY
    collision_policy: CollisionPolicy = CollisionPolicy.SKIP
    dry_run: bool = False
    preserve_tags: bool = True
    preserve_structure: bool = False
    tagged_subdir: str | None = None
    suffix_tags: bool = False
    rushes_layout: bool = False

    def __post_init__(self) -> None:
        self.source = Path(self.source).expanduser()
        self.destination = Path(self.destination).expanduser()

    def validate(self) -> None:
        if not self.source.exists():
            raise FileNotFoundError(f"Source directory does not exist: {self.source}")
        if not self.source.is_dir():
            raise NotADirectoryError(f"Source path is not a directory: {self.source}")