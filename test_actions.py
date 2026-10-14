from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from copy_entry import copy_entry
from status_davfs import read_token_expiry


class LocalActionTests(unittest.TestCase):
    def test_copy_preserves_source_and_existing_destination_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cloud"
            destination = root / "downloads"
            source.mkdir()
            destination.mkdir()
            (source / "Report.pdf").write_bytes(b"new fixture")
            (destination / "Report.pdf").write_bytes(b"existing fixture")
            copy_entry(source / "Report.pdf", destination, [source])
            self.assertEqual((destination / "Report.pdf").read_bytes(), b"existing fixture")
            self.assertEqual((source / "Report.pdf").read_bytes(), b"new fixture")
            (source / "Other.pdf").write_bytes(b"other fixture")
            copy_entry(source, destination, [source], contents=True)
            self.assertEqual((destination / "Other.pdf").read_bytes(), b"other fixture")

    def test_copy_cannot_write_into_any_cloud_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            (first / "Report.pdf").write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                copy_entry(first / "Report.pdf", second / "nested", [first, second])
            self.assertFalse((second / "nested").exists())

    def test_status_never_opens_oauth_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "token.json").write_bytes(b"not opened or parsed")
            with patch("builtins.open", side_effect=AssertionError("OAuth tokens must not be opened")):
                self.assertEqual(read_token_expiry(directory), (True, 0))


if __name__ == "__main__":
    unittest.main()
