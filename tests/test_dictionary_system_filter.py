from __future__ import annotations

import unittest
from unittest.mock import patch

from extract_army_pdf import (
    TranslationDictionary,
    TranslationEntry,
    add_dictionary_system_filter,
    filter_translation_dictionary,
    parse_description_map,
    parse_json_description_map,
    pick_translation_description,
    read_dictionary_source,
)


class DictionarySystemFilterTests(unittest.TestCase):
    def test_adds_optional_system_filter_and_preserves_existing_query(self) -> None:
        source = "https://example.test/api/dictionary/rules/fr?preview=1"

        self.assertEqual(
            "https://example.test/api/dictionary/rules/fr?preview=1&system=GF",
            add_dictionary_system_filter(source, "gf"),
        )
        self.assertEqual(source, add_dictionary_system_filter(source, None))

    def test_replaces_an_existing_system_filter(self) -> None:
        source = "https://example.test/api/dictionary?system=GFF&preview=1"

        self.assertEqual(
            "https://example.test/api/dictionary?preview=1&system=AOF",
            add_dictionary_system_filter(source, "aof"),
        )

    def test_remote_dictionary_request_uses_system_filter(self) -> None:
        with patch(
            "extract_army_pdf.fetch_dictionary_url",
            return_value=("{}", "https://example.test/api/dictionary?system=GF"),
        ) as fetch:
            read_dictionary_source("https://example.test/api/dictionary", "gf")

        fetch.assert_called_once_with("https://example.test/api/dictionary?system=GF")

    def test_compound_system_tags_are_split_case_insensitively(self) -> None:
        descriptions = parse_json_description_map(
            {"description": [{"system": " GF / AoF ", "text": "Shared"}]}
        )

        self.assertEqual({"gf": "Shared", "aof": "Shared"}, descriptions)
        self.assertEqual("Shared", pick_translation_description(descriptions, "GF"))
        self.assertEqual("Shared", pick_translation_description(descriptions, "aof"))
        self.assertEqual("", pick_translation_description(descriptions, "G"))

    def test_typescript_dictionary_uses_the_same_compound_tag_rules(self) -> None:
        descriptions = parse_description_map(
            '{"description": [{"system": "GF/AOF", "text": "Shared"}]}'
        )

        self.assertEqual({"gf": "Shared", "aof": "Shared"}, descriptions)

    def test_local_fallback_filter_uses_exact_tags(self) -> None:
        shared = TranslationEntry("Shared", {"gf": "Shared text", "aof": "Shared text"})
        universal = TranslationEntry("Universal", {"all": "Universal text"})
        other = TranslationEntry("Other", {"gff": "Other text"})
        translations = TranslationDictionary(
            source="legacy.ts",
            rules={"shared": shared, "universal": universal, "other": other},
            spells={"shared": shared, "other": other},
            factions={
                ("GF", "Army"): {"armyName": "Armee"},
                ("GFF", "Army"): {"armyName": "Escarmouche"},
            },
        )

        filtered = filter_translation_dictionary(translations, "gf")

        self.assertEqual({"shared"}, set(filtered.rules))
        self.assertEqual({"shared"}, set(filtered.spells))
        self.assertEqual({("GF", "Army")}, set(filtered.factions))

    def test_omitting_system_keeps_complete_dictionary(self) -> None:
        translations = TranslationDictionary(
            source="dictionary.ts",
            rules={"gf": TranslationEntry("GF", {"gf": "Text"})},
            spells={"aof": TranslationEntry("AOF", {"aof": "Text"})},
            factions={("GFF", "Army"): {"armyName": "Army"}},
        )

        self.assertIs(translations, filter_translation_dictionary(translations, None))


if __name__ == "__main__":
    unittest.main()
