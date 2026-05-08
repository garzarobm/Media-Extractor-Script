"""
Media Extractor Package

This package provides tools for classifying, organizing, and tagging media files
based on their extensions and metadata.
"""

from .classify import DEFAULT_CATEGORY_EXTENSIONS, FileClassifier
from .config import CollisionPolicy, Operation, OrganizerConfig
from .hooks import FileOperationContext, HookRegistry, load_hooks_from_module
from .organizer import MediaOrganizer, TransferResult, TransferStatus
from .tag_rules import TagRules, build_tag_rules

__all__ = [
    "CollisionPolicy",
    "DEFAULT_CATEGORY_EXTENSIONS",
    "FileClassifier",
    "FileOperationContext",
    "HookRegistry",
    "MediaOrganizer",
    "Operation",
    "OrganizerConfig",
    "TagRules",
    "TransferResult",
    "TransferStatus",
    "build_tag_rules",
    "load_hooks_from_module",
]