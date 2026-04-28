from __future__ import annotations

from media_extractor.hooks import FileOperationContext


def after_classify(context: FileOperationContext) -> None:
    if context.category != "imageExt":
        return
    if "portrait" not in context.source_path.stem.lower():
        return
    context.set_destination_path(
        context.destination_root / context.category / "portraits" / context.source_path.name
    )


def before_transfer(context: FileOperationContext) -> None:
    if context.destination_path is None:
        return
    if context.category == "audioExt":
        context.rename_destination(f"normalized_{context.source_path.name}")
    if context.tags:
        context.add_tag("organized-by-media-extractor")


def on_skip(context: FileOperationContext) -> None:
    context.metadata["skip_logged"] = True