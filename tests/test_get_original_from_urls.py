from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from getOriginalFromUrls import (
    build_api_url,
    make_output_name,
    read_url_list,
    write_json_atomic,
)


class GetOriginalFromUrlsTests(unittest.TestCase):
    def test_build_api_url_requests_complete_json(self) -> None:
        source = (
            "https://army-forge.onepagerules.com/army-info/"
            "grimdark-future/abc_123?armyName=Alien+Hives"
        )

        self.assertEqual(
            "https://army-forge.onepagerules.com/api/army-books/abc_123"
            "?gameSystem=2&simpleMode=false",
            build_api_url(source),
        )

    def test_read_url_list_ignores_comments_blanks_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text("# commentaire\n\nhttps://example.test/a\nhttps://example.test/a\n", encoding="utf-8")

            self.assertEqual(["https://example.test/a"], read_url_list(path))

    def test_output_name_uses_raw_payload_name_and_version(self) -> None:
        source = (
            "https://army-forge.onepagerules.com/army-info/"
            "age-of-fantasy/book-id?armyName=Fallback"
        )

        self.assertEqual(
            "age-of-fantasy-beastmen-3-5-2.json",
            make_output_name(source, {"name": "Beastmen", "versionString": "3.5.2"}),
        )

    def test_atomic_writer_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.json"
            write_json_atomic(path, {"name": "Armée"})

            self.assertEqual({"name": "Armée"}, json.loads(path.read_text(encoding="utf-8")))
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
