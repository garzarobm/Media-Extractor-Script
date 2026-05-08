"""
Core tests for the media extractor.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_extractor.config import CollisionPolicy, Operation, OrganizerConfig
from media_extractor.hooks import HookRegistry
from media_extractor.organizer import MediaOrganizer, TransferStatus


class FakeTagManager:
    """
    Fake tag manager for testing purposes.
    """
    def __init__(self, initial_tags: dict[Path, list[str]] | None = None) -> None:
        self.available = True
        self.reason_unavailable = None
        self.initial_tags = {path.resolve(): list(tags) for path, tags in (initial_tags or {}).items()}
        self.written: dict[Path, list[str]] = {}

    def ensure_available(self) -> None:
        return

    def get_tags(self, file_path: Path) -> list[str]:
        return list(self.initial_tags.get(file_path.resolve(), []))

    def set_tags(self, file_path: Path, tags: list[str]) -> None:
        self.written[file_path.resolve()] = list(tags)


class MediaExtractorTests(unittest.TestCase):
    """
    Test cases for the MediaOrganizer class.
    """
    def test_copy_preserves_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = root / "output"
            source.mkdir()
            sample = source / "photo.JPG"
            sample.write_text("image-data", encoding="utf-8")

            tag_manager = FakeTagManager({sample: ["tag-one", "tag-two"]})
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                tag_manager=tag_manager,
            )

            [result] = organizer.run()

            copied_path = destination / "imageExt" / sample.name
            self.assertEqual(result.status, TransferStatus.COPIED)
            self.assertTrue(sample.exists())
            self.assertTrue(copied_path.exists())
            self.assertEqual(tag_manager.written[copied_path.resolve()], ["tag-one", "tag-two"])

    def test_move_keeps_file_and_does_not_rewrite_unchanged_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = root / "output"
            source.mkdir()
            sample = source / "clip.mp4"
            sample.write_text("video-data", encoding="utf-8")

            tag_manager = FakeTagManager({sample: ["keep-me"]})
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.MOVE),
                tag_manager=tag_manager,
            )

            [result] = organizer.run()

            moved_path = destination / "videoExt" / sample.name
            self.assertEqual(result.status, TransferStatus.MOVED)
            self.assertFalse(sample.exists())
            self.assertTrue(moved_path.exists())
            self.assertEqual(tag_manager.written, {})

    def test_before_transfer_hook_can_change_name_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = root / "output"
            source.mkdir()
            sample = source / "song.mp3"
            sample.write_text("audio-data", encoding="utf-8")

            tag_manager = FakeTagManager({sample: ["original"]})
            hooks = HookRegistry()

            def before_transfer(context):
                context.rename_destination("renamed.mp3")
                context.add_tag("added-by-hook")

            hooks.add("before_transfer", before_transfer)
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=hooks,
                tag_manager=tag_manager,
            )

            [result] = organizer.run()

            copied_path = destination / "audioExt" / "renamed.mp3"
            self.assertEqual(result.status, TransferStatus.COPIED)
            self.assertTrue(copied_path.exists())
            self.assertEqual(
                tag_manager.written[copied_path.resolve()],
                ["original", "added-by-hook"],
            )

    def test_skip_existing_destination_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = root / "output"
            source.mkdir()
            existing_directory = destination / "docExt"
            existing_directory.mkdir(parents=True)

            sample = source / "note.txt"
            sample.write_text("new-data", encoding="utf-8")
            existing = existing_directory / sample.name
            existing.write_text("existing-data", encoding="utf-8")

            organizer = MediaOrganizer(
                OrganizerConfig(
                    source=source,
                    destination=destination,
                    operation=Operation.COPY,
                    collision_policy=CollisionPolicy.SKIP,
                ),
                tag_manager=FakeTagManager(),
            )

            [result] = organizer.run()

            self.assertEqual(result.status, TransferStatus.SKIPPED)
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing-data")

    def test_destination_subtree_is_ignored_while_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = source / "organized"
            source.mkdir()
            destination.mkdir()

            original = source / "scan-me.pdf"
            original.write_text("document", encoding="utf-8")
            nested_destination_file = destination / "docExt" / "already-there.pdf"
            nested_destination_file.parent.mkdir(parents=True)
            nested_destination_file.write_text("ignore-me", encoding="utf-8")

            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                tag_manager=FakeTagManager(),
            )

            results = organizer.run()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].source_path, original)

    def test_preserve_structure_mirrors_source_tree_with_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            destination = root / "output"
            (source / "vacation" / "day1").mkdir(parents=True)
            sample = source / "vacation" / "day1" / "photo.JPG"
            sample.write_text("image-data", encoding="utf-8")

            tag_manager = FakeTagManager({sample: ["favorite", "vacation"]})
            organizer = MediaOrganizer(
                OrganizerConfig(
                    source=source,
                    destination=destination,
                    operation=Operation.COPY,
                    preserve_structure=True,
                ),
                tag_manager=tag_manager,
            )

            [result] = organizer.run()

            mirrored = destination / "imageExt" / "vacation" / "day1" / "photo.JPG"
            self.assertEqual(result.status, TransferStatus.COPIED)
            self.assertTrue(mirrored.exists())
            self.assertEqual(result.destination_path, mirrored)
            self.assertEqual(tag_manager.written[mirrored.resolve()], ["favorite", "vacation"])


if __name__ == "__main__":
    unittest.main()