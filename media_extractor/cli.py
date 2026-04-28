from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Sequence

from .config import CollisionPolicy, Operation, OrganizerConfig
from .hooks import HookRegistry, load_hooks_from_module
from .organizer import MediaOrganizer, TransferResult, TransferStatus
from .tag_rules import build_tag_rules


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Organize media files, preserve Finder tags, and run custom hooks."
    )
    parser.add_argument("--source", type=Path, help="Directory to scan")
    parser.add_argument("--destination", type=Path, help="Directory to receive output")
    parser.add_argument(
        "--operation",
        choices=[operation.value for operation in Operation],
        help="Transfer mode: copy or move",
    )
    parser.add_argument(
        "--collision-policy",
        choices=[policy.value for policy in CollisionPolicy],
        default=CollisionPolicy.SKIP.value,
        help="How to handle destination collisions",
    )
    parser.add_argument(
        "--hooks-module",
        help="Import path or Python file path that defines hook functions",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan transfers without copying or moving files",
    )
    parser.add_argument(
        "--no-preserve-tags",
        action="store_true",
        help="Disable Finder tag read/write integration",
    )
    parser.add_argument(
        "--preserve-structure",
        action="store_true",
        help=(
            "Mirror the source folder layout under each category folder "
            "instead of flattening files. Tags are still copied along with each file."
        ),
    )
    parser.add_argument(
        "--tagged-subdir",
        nargs="?",
        const="tagged",
        default=None,
        metavar="NAME",
        help=(
            "Place files that have any Finder tag into destination/<category>/NAME/... "
            "while leaving untagged files at destination/<category>/.... "
            "NAME defaults to 'tagged' if the flag is given without a value. "
            "--route-tag rules still take precedence when they match."
        ),
    )

    tag_group = parser.add_argument_group(
        "tag rules",
        "Filter, route, rename, and mutate based on Finder tags. "
        "All --*-tag flags can be repeated and match by tag name only.",
    )
    tag_group.add_argument(
        "--require-tag",
        dest="require_tags",
        action="append",
        default=[],
        metavar="NAME",
        help="Only process files that have ALL listed tags",
    )
    tag_group.add_argument(
        "--require-any-tag",
        dest="require_any_tags",
        action="append",
        default=[],
        metavar="NAME",
        help="Only process files that have AT LEAST ONE listed tag",
    )
    tag_group.add_argument(
        "--exclude-tag",
        dest="exclude_tags",
        action="append",
        default=[],
        metavar="NAME",
        help="Skip files that have any of these tags",
    )
    tag_group.add_argument(
        "--require-untagged",
        action="store_true",
        help="Only process files that have no tags",
    )
    tag_group.add_argument(
        "--require-tagged",
        action="store_true",
        help="Only process files that have at least one tag",
    )
    tag_group.add_argument(
        "--route-tag",
        dest="route_tags",
        action="append",
        default=[],
        metavar="NAME=SUBDIR",
        help="If a file has the named tag, place it under destination/SUBDIR/<category>/...",
    )
    tag_group.add_argument(
        "--rename-prefix-tag",
        dest="rename_prefix_tags",
        action="append",
        default=[],
        metavar="NAME=PREFIX",
        help="Prefix the destination filename when the named tag is present",
    )
    tag_group.add_argument(
        "--rename-suffix-tag",
        dest="rename_suffix_tags",
        action="append",
        default=[],
        metavar="NAME=SUFFIX",
        help="Insert SUFFIX before the file extension when the named tag is present",
    )
    tag_group.add_argument(
        "--add-tag",
        dest="add_tags",
        action="append",
        default=[],
        metavar="NAME",
        help="Add a tag to every transferred file (after filtering)",
    )
    tag_group.add_argument(
        "--remove-tag",
        dest="remove_tags",
        action="append",
        default=[],
        metavar="NAME",
        help="Remove a tag by name from every transferred file",
    )
    tag_group.add_argument(
        "--clear-tags",
        action="store_true",
        help="Remove all tags from every transferred file before reapplying add-tag values",
    )

    preset_group = parser.add_argument_group(
        "presets",
        "Save or reuse the full set of flags. Stored under ~/.media-extractor/presets/.",
    )
    preset_group.add_argument(
        "--save-preset",
        metavar="NAME",
        help="After parsing, save these flags as a preset for later --load-preset NAME",
    )
    preset_group.add_argument(
        "--load-preset",
        metavar="NAME",
        help="Load flags from a previously saved preset (CLI flags override preset values)",
    )
    return parser


STATE_DIR = Path(os.path.expanduser("~/.media-extractor"))
PRESET_DIR = STATE_DIR / "presets"
LAST_RUN_PATH = STATE_DIR / "last-run.sh"


def _preset_path(name: str) -> Path:
    safe = name.strip().replace("/", "_")
    if not safe:
        raise ValueError("Preset name cannot be empty.")
    return PRESET_DIR / f"{safe}.json"


def _load_preset_args(name: str) -> list[str]:
    path = _preset_path(name)
    if not path.is_file():
        raise SystemExit(f"Preset not found: {path}")
    data = json.loads(path.read_text())
    args = data.get("args", [])
    if not isinstance(args, list):
        raise SystemExit(f"Preset {path} is malformed: 'args' must be a list.")
    return [str(a) for a in args]


def _save_preset(name: str, args: Sequence[str]) -> Path:
    path = _preset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"args": list(args)}, indent=2) + "\n")
    return path


def _save_last_run(args: Sequence[str]) -> Path:
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = "#!/usr/bin/env bash\nexec python3 media_ext.py " + \
        " ".join(shlex.quote(a) for a in args) + "\n"
    LAST_RUN_PATH.write_text(body)
    LAST_RUN_PATH.chmod(0o755)
    return LAST_RUN_PATH


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:]) if argv is None else list(argv)
    if not raw_args and sys.stdin.isatty():
        raw_args = run_interactive_menu(parser)

    # Expand --load-preset NAME by prepending the preset's args (so explicit
    # flags on the command line still override preset values).
    if "--load-preset" in raw_args:
        idx = raw_args.index("--load-preset")
        if idx + 1 >= len(raw_args):
            parser.error("--load-preset requires a NAME")
        name = raw_args[idx + 1]
        preset_args = _load_preset_args(name)
        raw_args = preset_args + raw_args[:idx] + raw_args[idx + 2:]
        print(f"Loaded preset '{name}' from {_preset_path(name)}")

    args = parser.parse_args(raw_args)

    # Strip --save-preset / --load-preset (and their values) from the persisted
    # args so reusing the preset or last-run script doesn't re-save them.
    persisted_args: list[str] = []
    skip_next = False
    for token in raw_args:
        if skip_next:
            skip_next = False
            continue
        if token in {"--save-preset", "--load-preset"}:
            skip_next = True
            continue
        persisted_args.append(token)

    config = OrganizerConfig(
        source=_resolve_directory(args.source, "Source directory", Path.cwd()),
        destination=_resolve_directory(
            args.destination,
            "Destination directory",
            Path.cwd(),
        ),
        operation=_resolve_operation(args.operation),
        collision_policy=CollisionPolicy.from_value(args.collision_policy),
        dry_run=args.dry_run,
        preserve_tags=not args.no_preserve_tags,
        preserve_structure=args.preserve_structure,
        tagged_subdir=args.tagged_subdir,
    )

    tag_rules = build_tag_rules(
        require_tags=args.require_tags,
        require_any_tags=args.require_any_tags,
        exclude_tags=args.exclude_tags,
        require_untagged=args.require_untagged,
        require_tagged=args.require_tagged,
        route_tags=args.route_tags,
        rename_prefix_tags=args.rename_prefix_tags,
        rename_suffix_tags=args.rename_suffix_tags,
        add_tags=args.add_tags,
        remove_tags=args.remove_tags,
        clear_tags=args.clear_tags,
    )

    if not tag_rules.is_empty and not config.preserve_tags:
        parser.error("Tag rule flags require Finder tag support; remove --no-preserve-tags.")

    hooks = HookRegistry()
    tag_rules.install(hooks)
    if args.hooks_module:
        hooks.extend(load_hooks_from_module(args.hooks_module))

    organizer = MediaOrganizer(config, hooks=hooks)
    exit_code = 0
    try:
        results = organizer.run()
    except Exception as exc:
        print(f"[error] {exc}")
        exit_code = 1
        results = []

    for result in results:
        print(_format_result(result))

    if results:
        print(_build_summary(results))
        if any(result.status is TransferStatus.ERROR for result in results):
            exit_code = 1

    print()
    print("Final command (re-run with the same options):")
    print("  python3 media_ext.py " + " ".join(_quote(arg) for arg in persisted_args))
    print(f"Exit status: {'success' if exit_code == 0 else 'failure'} (code {exit_code})")

    try:
        last_run = _save_last_run(persisted_args)
        print(f"Saved last run to {last_run} (run with: bash {last_run})")
    except OSError as exc:
        print(f"[warn] could not save last-run script: {exc}")

    if args.save_preset:
        try:
            saved = _save_preset(args.save_preset, persisted_args)
            print(f"Saved preset '{args.save_preset}' to {saved}")
            print(f"Reuse with: python3 media_ext.py --load-preset {args.save_preset}")
        except (OSError, ValueError) as exc:
            print(f"[warn] could not save preset: {exc}")

    return exit_code


def _resolve_directory(value: Path | None, label: str, default: Path) -> Path:
    if value is not None:
        return value.expanduser()

    print(f"Press ENTER to use {default}. Type 'browse' to open a folder picker.")
    response = input(f"{label}: ").strip()
    if not response:
        return default
    if response.lower() == "browse":
        return _pick_directory(label, default)
    return Path(response).expanduser()


def _resolve_operation(value: str | None) -> Operation:
    if value is not None:
        return Operation.from_value(value)

    prompt = "Operation [copy/move or 1/0] (default: copy): "
    response = input(prompt).strip()
    if not response:
        return Operation.COPY
    return Operation.from_value(response)


def _pick_directory(label: str, default: Path) -> Path:
    try:
        from tkinter import Tk, filedialog
    except Exception:
        return default

    root = Tk()
    root.withdraw()
    directory = filedialog.askdirectory(title=label, mustexist=True)
    root.destroy()
    return Path(directory).expanduser() if directory else default


def run_interactive_menu(parser: argparse.ArgumentParser) -> list[str]:
    print("=" * 60)
    print("Media Extractor - interactive mode")
    print("=" * 60)
    print("No flags were provided. Walking through the options below.")
    print("Press ENTER at any prompt to accept the default in [brackets].")
    print("Run 'python3 media_ext.py --help' to see every flag.")
    print()

    args: list[str] = []

    source = _prompt_directory("Source directory", Path.cwd())
    args += ["--source", str(source)]

    destination = _prompt_directory("Destination directory", Path.cwd())
    args += ["--destination", str(destination)]

    operation = _prompt_choice(
        "Operation",
        [op.value for op in Operation],
        default=Operation.COPY.value,
    )
    args += ["--operation", operation]

    collision = _prompt_choice(
        "Collision policy",
        [policy.value for policy in CollisionPolicy],
        default=CollisionPolicy.SKIP.value,
    )
    args += ["--collision-policy", collision]

    if _prompt_yes_no("Dry run only (plan without copying or moving)?", default=False):
        args.append("--dry-run")

    preserve_tags = _prompt_yes_no("Preserve macOS Finder tags?", default=True)
    if not preserve_tags:
        args.append("--no-preserve-tags")

    print()
    print("Output layout:")
    print("  No  -> flat by type: destination/<category>/<filename>  (original behavior)")
    print("  Yes -> mirror source tree: destination/<category>/<original/subfolders>/<filename>")
    if _prompt_yes_no(
        "Mirror the source folder structure under each category?",
        default=False,
    ):
        args.append("--preserve-structure")

    print()
    print("Tagged-vs-untagged split:")
    print("  No  -> tagged and untagged files share destination/<category>/...")
    print("  Yes -> tagged files go to destination/<category>/<NAME>/..., untagged stay at destination/<category>/...")
    if _prompt_yes_no(
        "Place tagged files into a separate subfolder under each category?",
        default=False,
    ):
        name = _prompt_optional("Subfolder name for tagged files [default: tagged]") or "tagged"
        args += ["--tagged-subdir", name]

    hooks_module = _prompt_optional("Hooks module path or import name (blank for none)")
    if hooks_module:
        args += ["--hooks-module", hooks_module]

    if preserve_tags and _prompt_yes_no("Configure tag rules?", default=False):
        args.extend(_prompt_tag_rules())

    print()
    print("Resolved command:")
    print("  python3 media_ext.py " + " ".join(_quote(arg) for arg in args))
    print()
    return args


def _prompt_directory(label: str, default: Path) -> Path:
    while True:
        print(f"{label} [default: {default}, 'browse' for picker]:")
        response = input("> ").strip()
        if not response:
            return default
        if response.lower() == "browse":
            return _pick_directory(label, default)
        return Path(response).expanduser()


def _prompt_choice(label: str, choices: Sequence[str], *, default: str) -> str:
    options = "/".join(choices)
    while True:
        print(f"{label} [{options}] [default: {default}]:")
        response = input("> ").strip().lower()
        if not response:
            return default
        if response in choices:
            return response
        print(f"  Invalid choice. Pick one of: {options}")


def _prompt_yes_no(label: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        print(f"{label} [{suffix}]:")
        response = input("> ").strip().lower()
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("  Please answer y or n.")


def _prompt_optional(label: str) -> str:
    print(f"{label}:")
    return input("> ").strip()


def _prompt_repeated(label: str, *, hint: str = "") -> list[str]:
    print(f"{label} (one per line, blank to finish){(' ' + hint) if hint else ''}:")
    values: list[str] = []
    while True:
        response = input("> ").strip()
        if not response:
            return values
        values.append(response)


def _prompt_tag_rules() -> list[str]:
    args: list[str] = []
    print()
    print("-- Tag rules --")
    print("Filtering: only these files will be processed.")
    for value in _prompt_repeated("--require-tag NAME (must have ALL)"):
        args += ["--require-tag", value]
    for value in _prompt_repeated("--require-any-tag NAME (must have AT LEAST ONE)"):
        args += ["--require-any-tag", value]
    for value in _prompt_repeated("--exclude-tag NAME (skip if present)"):
        args += ["--exclude-tag", value]

    presence = _prompt_choice(
        "Tag presence requirement",
        ["none", "tagged", "untagged"],
        default="none",
    )
    if presence == "tagged":
        args.append("--require-tagged")
    elif presence == "untagged":
        args.append("--require-untagged")

    print("Routing: place files under destination/SUBDIR/<category>/...")
    for value in _prompt_repeated("--route-tag NAME=SUBDIR", hint="e.g. favorite=priority"):
        args += ["--route-tag", value]

    print("Renaming based on tags.")
    for value in _prompt_repeated("--rename-prefix-tag NAME=PREFIX", hint="e.g. favorite=FAV_"):
        args += ["--rename-prefix-tag", value]
    for value in _prompt_repeated("--rename-suffix-tag NAME=SUFFIX", hint="e.g. archive=_arc"):
        args += ["--rename-suffix-tag", value]

    print("Tag mutation on the destination file.")
    if _prompt_yes_no("Clear all tags before applying add-tag values?", default=False):
        args.append("--clear-tags")
    for value in _prompt_repeated("--remove-tag NAME"):
        args += ["--remove-tag", value]
    for value in _prompt_repeated("--add-tag NAME"):
        args += ["--add-tag", value]

    return args


def _quote(value: str) -> str:
    if value and all(ch.isalnum() or ch in "-_./=" for ch in value):
        return value
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def _format_result(result: TransferResult) -> str:
    details = result.source_path.as_posix()
    if result.destination_path is not None:
        details = f"{details} -> {result.destination_path.as_posix()}"
    suffix = f" ({result.tag_count} tags)" if result.tag_count else ""
    return f"[{result.status.value}] {details}: {result.message}{suffix}"


def _build_summary(results: Sequence[TransferResult]) -> str:
    counts = {status: 0 for status in TransferStatus}
    for result in results:
        counts[result.status] += 1
    return (
        "Summary: "
        f"planned={counts[TransferStatus.PLANNED]}, "
        f"copied={counts[TransferStatus.COPIED]}, "
        f"moved={counts[TransferStatus.MOVED]}, "
        f"skipped={counts[TransferStatus.SKIPPED]}, "
        f"errors={counts[TransferStatus.ERROR]}"
    )