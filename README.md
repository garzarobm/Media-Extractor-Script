---
marp: true
---

# Media Extractor Script

This project organizes images, documents, videos, and audio files from a source tree into category folders while preserving macOS Finder tags.

## Quick Start

Install Python 3 on macOS (and `tkinter` if you want folder-picker support).
Run `python3 media_ext.py --source /path/to/source --destination /path/to/output --operation copy` to sort files into media categories.
If you run `python3 media_ext.py` with no flags, the script prompts for paths and accepts `browse` to open the picker.
You can add tag-based behavior with flags like `--require-tag favorite`, `--route-tag favorite=priority`, and `--add-tag organized`.
Repeat your most recent run anytime with `bash ~/.media-extractor/last-run.sh`.

## What Changed

- The old one-file script is now a thin entry point at `media_ext.py`.
- The reusable logic lives in the `media_extractor` package.
- Copy mode now reapplies Finder tags with the bundled `macos_tags` project or a macOS `xattr` fallback.
- Move mode keeps native tag preservation and only rewrites tags if a hook changes them.
- Custom hook functions can run before classification, before transfer, after transfer, on skip, and on error.

## Layout

- `media_ext.py` starts the CLI.
- `media_extractor/classify.py` maps file extensions to `imageExt`, `docExt`, `videoExt`, and `audioExt`.
- `media_extractor/organizer.py` scans, classifies, copies or moves files, and applies collision handling.
- `media_extractor/tags.py` prefers `macos_tags` and falls back to the macOS `xattr` command-line tool for tag read and write.
- `media_extractor/hooks.py` defines the hook context and loads custom hook modules.
- `example_hooks.py` is a ready-to-edit hook template.

## Requirements

- macOS
- Python 3
- `tkinter` if you want to use the folder picker fallback
- Finder tag preservation works out of the box via the macOS `xattr` command-line tool

## Basic Usage

Run with flags:

```bash
python3 media_ext.py --source /path/to/source --destination /path/to/output --operation copy
```

Run interactively:

```bash
python3 media_ext.py
```

Available options:

- `--operation copy|move`
- `--collision-policy skip|rename|overwrite`
- `--dry-run`
- `--no-preserve-tags`
- `--preserve-structure` (mirror source folder layout under each category)
- `--tagged-subdir [NAME]` (route any tagged file to `destination/<category>/NAME/...`; untagged files stay at `destination/<category>/...`. NAME defaults to `tagged`.)
- `--suffix-tags` (append `_<category>_<tag1>_<tag2>...` to every destination filename. Category suffixes: audio → `_audiobyte`, video → `_video`, image → `_image`, doc → `_doc`. Example: `clip.mp4` with tags `favorite`, `archive` becomes `clip_video_favorite_archive.mp4`.)
- `--rushes-layout` (video-editing layout: `audio`, `video`, and `images` go under `destination/rushes/{audio,video,images}/...`; `docs` go under `destination/docs/` with an mtime prefix `YYYY-MM-DD_HHMMSS_` so they sort alphanumerically by filming time.)
- `--hooks-module path/to/hooks.py`
- `--save-preset NAME` / `--load-preset NAME` (stored under `~/.media-extractor/presets/`)

Every run also writes the resolved command to `~/.media-extractor/last-run.sh`, so you can repeat the previous run with:

```bash
bash ~/.media-extractor/last-run.sh
```

Tag-rule options (see the section below for details):

- `--require-tag NAME`, `--require-any-tag NAME`, `--exclude-tag NAME`
- `--require-tagged`, `--require-untagged`
- `--route-tag NAME=SUBDIR`
- `--rename-prefix-tag NAME=PREFIX`, `--rename-suffix-tag NAME=SUFFIX`
- `--add-tag NAME`, `--remove-tag NAME`, `--clear-tags`

When no source or destination is passed, the CLI prompts for it. Enter `browse` to open the folder picker.

## Tag-Based Routing, Renaming, and Filtering

These flags act on Finder tags read from each source file. They match by tag name only (color is ignored), can be repeated, and run before any custom hook module. Tag rules require the tag adapter, so they cannot be combined with `--no-preserve-tags`.

Filtering:

- `--require-tag NAME` keeps only files that have ALL listed tags.
- `--require-any-tag NAME` keeps files with AT LEAST ONE listed tag.
- `--exclude-tag NAME` skips files that have any of these tags.
- `--require-tagged` keeps only files that have at least one tag.
- `--require-untagged` keeps only files that have no tags.

Routing:

- `--route-tag NAME=SUBDIR` places matching files under `destination/SUBDIR/<category>/...` instead of `destination/<category>/...`. The first matching rule wins.

Renaming:

- `--rename-prefix-tag NAME=PREFIX` prefixes the destination filename when the tag is present.
- `--rename-suffix-tag NAME=SUFFIX` inserts the suffix before the file extension when the tag is present.

Tag mutation on the destination:

- `--add-tag NAME` appends a tag to every transferred file.
- `--remove-tag NAME` removes a tag by name.
- `--clear-tags` drops every tag before any `--add-tag` values are applied.

Examples:

```bash
python3 media_ext.py \
  --source ~/Pictures/Inbox \
  --destination ~/Pictures/Sorted \
  --operation copy \
  --require-tag favorite \
  --route-tag favorite=priority \
  --rename-prefix-tag favorite=FAV_ \
  --add-tag organized
```

```bash
python3 media_ext.py \
  --source ~/Downloads \
  --destination ~/Downloads/Sorted \
  --operation move \
  --exclude-tag temp \
  --require-tagged
```

## Hook Modules

Hook modules can be passed with `--hooks-module`. The loader accepts either a Python import path or a file path. You can define any of these function names:

- `before_classify(context)`
- `after_classify(context)`
- `before_transfer(context)`
- `after_transfer(context)`
- `on_skip(context)`
- `on_error(context)`

Each hook receives a `FileOperationContext` with the source path, destination root, operation, category, destination path, tags, skip reason, and metadata dictionary.

Example hook file:

```python
def before_transfer(context):
    if context.category == "imageExt":
        context.rename_destination(f"tagged_{context.source_path.name}")
    if context.tags:
        context.add_tag("copied-by-media-extractor")
```

You can also start from the included template:

```bash
python3 media_ext.py \
  --source /path/to/source \
  --destination /path/to/output \
  --operation copy \
  --hooks-module ./example_hooks.py
```

## Finder Tag Behavior

- Copy mode reads tags from the source file and writes them to the copied file.
- Move mode relies on the filesystem move to keep tags.
- If a hook changes `context.tags`, the destination file gets the updated tag list after transfer.
- The organizer first tries the bundled `macos_tags` project and falls back to the macOS `xattr` CLI when Python dependencies are missing.
