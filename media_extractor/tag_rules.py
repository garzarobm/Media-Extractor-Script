from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .hooks import FileOperationContext, HookRegistry


def tag_name(tag: Any) -> str:
    name = getattr(tag, "name", None)
    if name is not None:
        return str(name)
    text = str(tag)
    return text.split("\n", 1)[0]


def tag_names(tags: Iterable[Any]) -> set[str]:
    return {tag_name(tag) for tag in tags}


def parse_mapping(value: str, *, flag: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{flag} expects NAME=VALUE, got: {value!r}")
    name, mapped = value.split("=", 1)
    name = name.strip()
    mapped = mapped.strip()
    if not name or not mapped:
        raise ValueError(f"{flag} expects non-empty NAME and VALUE, got: {value!r}")
    return name, mapped


@dataclass
class TagRules:
    require_tags: tuple[str, ...] = ()
    require_any_tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    require_untagged: bool = False
    require_tagged: bool = False
    route_tags: tuple[tuple[str, str], ...] = ()
    rename_prefix_tags: tuple[tuple[str, str], ...] = ()
    rename_suffix_tags: tuple[tuple[str, str], ...] = ()
    add_tags: tuple[str, ...] = ()
    remove_tags: tuple[str, ...] = ()
    clear_tags: bool = False

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.require_tags,
                self.require_any_tags,
                self.exclude_tags,
                self.require_untagged,
                self.require_tagged,
                self.route_tags,
                self.rename_prefix_tags,
                self.rename_suffix_tags,
                self.add_tags,
                self.remove_tags,
                self.clear_tags,
            )
        )

    def install(self, registry: HookRegistry) -> None:
        if self.is_empty:
            return
        registry.add("after_classify", self._filter_hook)
        registry.add("before_transfer", self._route_hook)
        registry.add("before_transfer", self._rename_hook)
        registry.add("before_transfer", self._mutate_tags_hook)

    def to_registry(self) -> HookRegistry:
        registry = HookRegistry()
        self.install(registry)
        return registry

    def _filter_hook(self, context: FileOperationContext) -> None:
        names = tag_names(context.tags)

        if self.require_untagged and names:
            context.skip("File has tags but --require-untagged is set")
            return
        if self.require_tagged and not names:
            context.skip("File has no tags but --require-tagged is set")
            return
        if self.require_tags:
            missing = [tag for tag in self.require_tags if tag not in names]
            if missing:
                context.skip(f"Missing required tags: {', '.join(missing)}")
                return
        if self.require_any_tags and not any(tag in names for tag in self.require_any_tags):
            context.skip(
                f"None of the required-any tags present: {', '.join(self.require_any_tags)}"
            )
            return
        if self.exclude_tags:
            present = [tag for tag in self.exclude_tags if tag in names]
            if present:
                context.skip(f"Excluded by tag: {', '.join(present)}")
                return

    def _route_hook(self, context: FileOperationContext) -> None:
        if not self.route_tags or context.skip_reason or context.destination_path is None:
            return
        names = tag_names(context.tags)
        for tag, subdir in self.route_tags:
            if tag in names:
                current = context.destination_path
                relative = current.relative_to(context.destination_root)
                context.set_destination_path(
                    context.destination_root / subdir / relative
                )
                return

    def _rename_hook(self, context: FileOperationContext) -> None:
        if context.skip_reason or context.destination_path is None:
            return
        if not self.rename_prefix_tags and not self.rename_suffix_tags:
            return
        names = tag_names(context.tags)
        current = context.destination_path
        prefixes = [
            value for tag, value in self.rename_prefix_tags if tag in names
        ]
        suffixes = [
            value for tag, value in self.rename_suffix_tags if tag in names
        ]
        if not prefixes and not suffixes:
            return
        prefix = "".join(prefixes)
        suffix_text = "".join(suffixes)
        if suffix_text:
            new_name = f"{prefix}{current.stem}{suffix_text}{current.suffix}"
        else:
            new_name = f"{prefix}{current.name}"
        context.rename_destination(new_name)

    def _mutate_tags_hook(self, context: FileOperationContext) -> None:
        if context.skip_reason:
            return
        if self.clear_tags:
            context.update_tags([])
        if self.remove_tags:
            removed = set(self.remove_tags)
            context.update_tags(
                [tag for tag in context.tags if tag_name(tag) not in removed]
            )
        if self.add_tags:
            existing = tag_names(context.tags)
            for tag in self.add_tags:
                if tag not in existing:
                    context.add_tag(tag)
                    existing.add(tag)


def build_tag_rules(
    *,
    require_tags: Sequence[str] = (),
    require_any_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
    require_untagged: bool = False,
    require_tagged: bool = False,
    route_tags: Sequence[str] = (),
    rename_prefix_tags: Sequence[str] = (),
    rename_suffix_tags: Sequence[str] = (),
    add_tags: Sequence[str] = (),
    remove_tags: Sequence[str] = (),
    clear_tags: bool = False,
) -> TagRules:
    if require_untagged and require_tagged:
        raise ValueError("--require-untagged and --require-tagged cannot be combined")
    return TagRules(
        require_tags=tuple(require_tags),
        require_any_tags=tuple(require_any_tags),
        exclude_tags=tuple(exclude_tags),
        require_untagged=require_untagged,
        require_tagged=require_tagged,
        route_tags=tuple(parse_mapping(value, flag="--route-tag") for value in route_tags),
        rename_prefix_tags=tuple(
            parse_mapping(value, flag="--rename-prefix-tag") for value in rename_prefix_tags
        ),
        rename_suffix_tags=tuple(
            parse_mapping(value, flag="--rename-suffix-tag") for value in rename_suffix_tags
        ),
        add_tags=tuple(add_tags),
        remove_tags=tuple(remove_tags),
        clear_tags=clear_tags,
    )
