"""
Tests for tag-based rules and filtering.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_extractor.config import Operation, OrganizerConfig
from media_extractor.organizer import MediaOrganizer, TransferStatus
from media_extractor.tag_rules import build_tag_rules

from test_media_extractor import FakeTagManager


class TagRulesTests(unittest.TestCase):
    """
    Test cases for TagRules functionality.
    """
    def _setup_tree(self, tmp_dir: str):
        root = Path(tmp_dir)
        source = root / "source"
        destination = root / "output"
        source.mkdir()
        keep = source / "keep.jpg"
        drop = source / "drop.jpg"
        bare = source / "bare.jpg"
        keep.write_text("k", encoding="utf-8")
        drop.write_text("d", encoding="utf-8")
        bare.write_text("b", encoding="utf-8")
        return source, destination, keep, drop, bare

    def test_require_tag_filters_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, drop, bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({keep: ["alpha"], drop: ["beta"]})
            rules = build_tag_rules(require_tags=["alpha"])
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            results = {result.source_path.name: result for result in organizer.run()}

            self.assertEqual(results["keep.jpg"].status, TransferStatus.COPIED)
            self.assertEqual(results["drop.jpg"].status, TransferStatus.SKIPPED)
            self.assertEqual(results["bare.jpg"].status, TransferStatus.SKIPPED)

    def test_exclude_tag_skips_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, drop, bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({drop: ["nope"]})
            rules = build_tag_rules(exclude_tags=["nope"])
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            results = {result.source_path.name: result for result in organizer.run()}

            self.assertEqual(results["drop.jpg"].status, TransferStatus.SKIPPED)
            self.assertEqual(results["keep.jpg"].status, TransferStatus.COPIED)
            self.assertEqual(results["bare.jpg"].status, TransferStatus.COPIED)

    def test_route_tag_changes_destination_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, _drop, _bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({keep: ["important"]})
            rules = build_tag_rules(
                require_tags=["important"],
                route_tags=["important=priority"],
            )
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            results = {result.source_path.name: result for result in organizer.run()}

            expected = destination / "priority" / "imageExt" / "keep.jpg"
            self.assertEqual(results["keep.jpg"].status, TransferStatus.COPIED)
            self.assertTrue(expected.exists())

    def test_rename_prefix_and_suffix_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, _drop, _bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({keep: ["alpha"]})
            rules = build_tag_rules(
                require_tags=["alpha"],
                rename_prefix_tags=["alpha=PRE_"],
                rename_suffix_tags=["alpha=_SUF"],
            )
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            organizer.run()

            expected = destination / "imageExt" / "PRE_keep_SUF.jpg"
            self.assertTrue(expected.exists())

    def test_add_and_remove_tags_apply_to_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, _drop, _bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({keep: ["alpha", "beta"]})
            rules = build_tag_rules(
                require_tags=["alpha"],
                remove_tags=["beta"],
                add_tags=["organized"],
            )
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            organizer.run()

            written = tag_manager.written[(destination / "imageExt" / "keep.jpg").resolve()]
            self.assertEqual(written, ["alpha", "organized"])

    def test_require_untagged_skips_files_with_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, destination, keep, _drop, bare = self._setup_tree(tmp_dir)
            tag_manager = FakeTagManager({keep: ["whatever"]})
            rules = build_tag_rules(require_untagged=True)
            organizer = MediaOrganizer(
                OrganizerConfig(source=source, destination=destination, operation=Operation.COPY),
                hooks=rules.to_registry(),
                tag_manager=tag_manager,
            )

            results = {result.source_path.name: result for result in organizer.run()}

            self.assertEqual(results["keep.jpg"].status, TransferStatus.SKIPPED)
            self.assertEqual(results["bare.jpg"].status, TransferStatus.COPIED)


if __name__ == "__main__":
    unittest.main()
