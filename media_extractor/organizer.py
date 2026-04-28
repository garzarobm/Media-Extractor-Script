from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .classify import FileClassifier
from .config import CollisionPolicy, Operation, OrganizerConfig
from .hooks import FileOperationContext, HookRegistry
from .tags import MacOSTagManager, TagManager


class TransferStatus(str, Enum):
    COPIED = "copied"
    MOVED = "moved"
    SKIPPED = "skipped"
    ERROR = "error"
    PLANNED = "planned"


@dataclass
class TransferResult:
    source_path: Path
    status: TransferStatus
    message: str
    category: str | None = None
    destination_path: Path | None = None
    tag_count: int = 0


class MediaOrganizer:
    def __init__(
        self,
        config: OrganizerConfig,
        *,
        classifier: FileClassifier | None = None,
        hooks: HookRegistry | None = None,
        tag_manager: TagManager | None = None,
    ) -> None:
        self.config = config
        self.classifier = classifier or FileClassifier()
        self.hooks = hooks or HookRegistry()
        self.tag_manager = tag_manager or MacOSTagManager()
        self._resolved_destination = self.config.destination.resolve()

    def run(self) -> list[TransferResult]:
        self.config.validate()
        if self.config.preserve_tags:
            self.tag_manager.ensure_available()
        return [self.process_file(path) for path in self.iter_source_files()]

    def iter_source_files(self) -> Iterable[Path]:
        for current_root, dir_names, file_names in os.walk(self.config.source):
            current_path = Path(current_root)
            dir_names[:] = [
                name
                for name in sorted(dir_names)
                if not self._is_in_destination(current_path / name)
            ]
            if self._is_in_destination(current_path):
                continue
            for file_name in sorted(file_names):
                file_path = current_path / file_name
                if self._is_in_destination(file_path):
                    continue
                yield file_path

    def process_file(self, source_path: Path) -> TransferResult:
        context = FileOperationContext(
            source_path=source_path,
            destination_root=self.config.destination,
            operation=self.config.operation,
            dry_run=self.config.dry_run,
        )

        try:
            self._attach_tags(context)

            self.hooks.dispatch("before_classify", context)
            if context.skip_reason:
                return self._skip_result(context)

            if context.category is None:
                context.category = self.classifier.classify(source_path)

            self.hooks.dispatch("after_classify", context)
            if context.skip_reason:
                return self._skip_result(context)

            if context.category is None:
                context.skip("No matching category for file extension")
                return self._skip_result(context)

            if context.destination_path is None:
                context.destination_path = self._default_destination_path(context)

            self.hooks.dispatch("before_transfer", context)
            if context.skip_reason:
                return self._skip_result(context)

            if context.destination_path is None:
                context.destination_path = self._default_destination_path(context)

            destination_path = self._resolve_collision(context.destination_path)
            if destination_path is None:
                context.skip("Destination already exists")
                return self._skip_result(context)

            context.destination_path = destination_path

            if self.config.dry_run:
                return TransferResult(
                    source_path=source_path,
                    status=TransferStatus.PLANNED,
                    message=f"Would {self.config.operation.value} file",
                    category=context.category,
                    destination_path=context.destination_path,
                    tag_count=len(context.tags),
                )

            context.destination_path.parent.mkdir(parents=True, exist_ok=True)
            status = self._transfer(source_path, context.destination_path)

            self.hooks.dispatch("after_transfer", context)
            if self._should_write_tags(context):
                self.tag_manager.set_tags(context.destination_path, context.tags)

            return TransferResult(
                source_path=source_path,
                status=status,
                message=f"{status.value.capitalize()} file",
                category=context.category,
                destination_path=context.destination_path,
                tag_count=len(context.tags),
            )
        except Exception as error:
            context.error = error
            try:
                self.hooks.dispatch("on_error", context)
            except Exception as hook_error:
                context.error = hook_error
            return TransferResult(
                source_path=source_path,
                status=TransferStatus.ERROR,
                message=str(context.error),
                category=context.category,
                destination_path=context.destination_path,
                tag_count=len(context.tags),
            )

    def _attach_tags(self, context: FileOperationContext) -> None:
        if not self.config.preserve_tags:
            return
        tags = self.tag_manager.get_tags(context.source_path)
        context.tags = list(tags)
        context.original_tags = tuple(tags)

    def _default_destination_path(self, context: FileOperationContext) -> Path:
        assert context.category is not None
        category_root = self.config.destination / context.category
        if self.config.tagged_subdir and context.tags:
            category_root = category_root / self.config.tagged_subdir
        if self.config.preserve_structure:
            try:
                relative = context.source_path.relative_to(self.config.source)
            except ValueError:
                relative = Path(context.source_path.name)
            return category_root / relative
        return category_root / context.source_path.name

    def _resolve_collision(self, destination_path: Path) -> Path | None:
        if not destination_path.exists():
            return destination_path

        policy = self.config.collision_policy
        if policy is CollisionPolicy.SKIP:
            return None
        if policy is CollisionPolicy.OVERWRITE:
            if destination_path.is_dir():
                raise IsADirectoryError(
                    f"Destination path is a directory: {destination_path}"
                )
            destination_path.unlink()
            return destination_path

        stem = destination_path.stem
        suffix = destination_path.suffix
        counter = 1
        while True:
            candidate = destination_path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _transfer(self, source_path: Path, destination_path: Path) -> TransferStatus:
        if self.config.operation is Operation.MOVE:
            shutil.move(str(source_path), str(destination_path))
            return TransferStatus.MOVED

        shutil.copy2(str(source_path), str(destination_path))
        return TransferStatus.COPIED

    def _should_write_tags(self, context: FileOperationContext) -> bool:
        if not self.config.preserve_tags or context.destination_path is None:
            return False
        if self.config.operation is Operation.COPY:
            return bool(context.tags) or bool(context.original_tags)
        return context.tags_changed

    def _skip_result(self, context: FileOperationContext) -> TransferResult:
        self.hooks.dispatch("on_skip", context)
        return TransferResult(
            source_path=context.source_path,
            status=TransferStatus.SKIPPED,
            message=context.skip_reason or "Skipped",
            category=context.category,
            destination_path=context.destination_path,
            tag_count=len(context.tags),
        )

    def _is_in_destination(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        try:
            return resolved.is_relative_to(self._resolved_destination)
        except ValueError:
            return False