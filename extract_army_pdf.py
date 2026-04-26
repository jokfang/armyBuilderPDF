from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError as error:
    raise SystemExit("Missing dependency: install pypdf with `python -m pip install pypdf`.") from error

from logging_utils import (
    LOG_FILE_PATH,
    MISSING_TRANSLATIONS_LOG_FILE_PATH,
    get_or_create_file_logger,
    setup_script_logging,
)


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


SYSTEM_NAMES = {
    "AOF": "Age of Fantasy",
    "GF": "Grimdark Future",
    "GFF": "Grimdark Future: Firefight",
}

SECTION_HEADINGS = {
    "INTRO",
    "ABOUT OPR",
    "BACKGROUND STORY",
    "ARMY-WIDE SPECIAL RULE",
    "SPECIAL RULES",
    "AURA SPECIAL RULES",
    "ARMY SPELLS",
}

UNIT_HEADER_RE = re.compile(r"^(?P<unique_marker>[★*✦✭]?\s*)?(?P<name>.+?) \[(?P<size>\d+)\] - (?P<cost>\d+)pts$")
STAT_RE = re.compile(r"^Quality (?P<quality>\d\+) Defense (?P<defense>\d\+)(?: Tough (?P<tough>\d+))?$")
WEAPON_RE = re.compile(r"^(?P<name>.+?) (?P<rng>-|\d+\") (?P<atk>A\d+) (?P<ap>-|\d+) ?(?P<spe>.*)$")
UPGRADE_HEADING_RE = re.compile(r"^(Upgrade|Replace)\b")
PRICED_OPTION_RE = re.compile(r"^(?P<text>.+?) (?P<cost>(?:\+\d+pts)|Free)$")
SPELL_RE = re.compile(r"^(?P<name>.+?) \((?P<cost>\d+)\): (?P<description>.+)$")
TS_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
DEFAULT_DICTIONARY_SOURCE = "https://johammer.netlify.app/api/dictionary"
FALLBACK_DICTIONARY_SOURCE = (
    "https://raw.githubusercontent.com/jokfang/Johammer.github.io/refs/heads/main/public/locales/rules/common-rules.dictionary.ts"
)
DICTIONARY_REQUEST_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


@dataclass
class PdfPage:
    number: int
    text: str


@dataclass
class TranslationEntry:
    title: str
    descriptions: dict[str, str]


@dataclass
class TranslationDictionary:
    source: str
    rules: dict[str, TranslationEntry]
    spells: dict[str, TranslationEntry]
    factions: dict[tuple[str, str], dict[str, str]]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    # Some OPR PDFs expose ligatures as NUL bytes via pypdf. The glyph can be
    # either "ft" (Rift in Beastmen) or "ff" (Buff/effect in Alien Hives), so
    # handle the known words before falling back to the most common case.
    null_replacements = {
        "Ri\x00": "Rift",
        "ri\x00": "rift",
        "a\x00er": "after",
        "A\x00er": "After",
        "Aircra\x00": "Aircraft",
        "aircra\x00": "aircraft",
        "gi\x00": "gift",
        "o\x00spring": "offspring",
        "e\x00orts": "efforts",
        "e\x00ect": "effect",
        "e\x00ects": "effects",
        "di\x00icult": "difficult",
        "Bu\x00": "Buff",
        "bu\x00": "buff",
        "Debu\x00": "Debuff",
        "debu\x00": "debuff",
        "o\x00 ": "off ",
        "o\x00.": "off.",
        "o\x00,": "off,",
        "o\x00\n": "off\n",
    }
    for source, replacement in null_replacements.items():
        normalized = normalized.replace(source, replacement)
    normalized = normalized.replace("\x00", "ff")
    normalized = normalized.replace("\uFFFD", "")
    normalized = normalized.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff")
    normalized = normalized.replace("ARMY-W IDE", "ARMY-WIDE")
    return normalized


def compact_lines(value: str) -> list[str]:
    return [line.strip() for line in normalize_text(value).splitlines() if line.strip()]


def read_pages(pdf_path: Path) -> list[PdfPage]:
    reader = PdfReader(str(pdf_path))
    pages: list[PdfPage] = []

    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(PdfPage(number=index, text=normalize_text(text)))

    return pages


def parse_header(header: str) -> dict[str, str]:
    match = re.match(r"^(?P<system>[A-Z]+) - (?P<army>.+?) V(?P<version>[\d.]+)$", header)
    if not match:
        return {
            "systemCode": "",
            "systemName": "",
            "armyName": "",
            "version": "",
        }

    system_code = match.group("system")
    army_name = match.group("army").title()
    return {
        "systemCode": system_code,
        "systemName": SYSTEM_NAMES.get(system_code, system_code),
        "armyName": army_name,
        "version": match.group("version"),
    }


def extract_section(lines: list[str], start: str, end: str | None = None) -> str:
    try:
        start_index = lines.index(start) + 1
    except ValueError:
        return ""

    if end is None:
        end_index = len(lines)
    else:
        try:
            end_index = lines.index(end, start_index)
        except ValueError:
            end_index = len(lines)

    section_lines = [line for line in lines[start_index:end_index] if not line.isdigit()]
    return "\n".join(section_lines).strip()


def unwrap_rule_lines(value: str) -> list[str]:
    entries: list[str] = []
    current = ""

    for line in compact_lines(value):
        if re.match(r"^[A-Z][^:]{1,80}:", line):
            if current:
                entries.append(current.strip())
            current = line
        else:
            current = f"{current} {line}".strip()

    if current:
        entries.append(current.strip())

    return entries


def parse_rules(value: str) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []

    for entry in unwrap_rule_lines(value):
        if ":" not in entry:
            continue
        name, description = entry.split(":", 1)
        rules.append({"name": name.strip(), "description": description.strip()})

    return rules


def parse_spells(value: str) -> list[dict[str, Any]]:
    spells: list[dict[str, Any]] = []

    for entry in unwrap_rule_lines(value):
        match = SPELL_RE.match(entry)
        if not match:
            continue
        spells.append(
            {
                "name": match.group("name").strip(),
                "cost": int(match.group("cost")),
                "description": match.group("description").strip(),
            }
        )

    return spells


def parse_ts_string(raw_value: str) -> str:
    return json.loads(f'"{raw_value}"')


def find_matching_brace(value: str, start_index: int) -> int:
    return find_matching_delimiter(value, start_index, "{", "}")


def find_matching_delimiter(value: str, start_index: int, opening: str, closing: str) -> int:
    depth = 0
    in_string = False
    escaped = False

    for index in range(start_index, len(value)):
        char = value[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index

    raise ValueError(f"Unmatched delimiter {opening}{closing} in translation dictionary.")


def extract_export_object(content: str, export_name: str) -> str:
    marker = f"export const {export_name}"
    marker_index = content.find(marker)
    if marker_index < 0:
        raise ValueError(f"Missing export {export_name} in translation dictionary.")

    start_index = content.find("{", marker_index)
    if start_index < 0:
        raise ValueError(f"Missing object body for export {export_name}.")

    end_index = find_matching_brace(content, start_index)
    return content[start_index : end_index + 1]


def extract_language_object(content: str, language: str) -> str:
    match = re.search(rf'^\s*"?{re.escape(language)}"?\s*:\s*\{{', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing language {language} in translation dictionary.")

    start_index = content.find("{", match.start())
    end_index = find_matching_brace(content, start_index)
    return content[start_index : end_index + 1]


def extract_language_array(content: str, language: str) -> str:
    match = re.search(rf'^\s*"?{re.escape(language)}"?\s*:\s*\[', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing language {language} in translation dictionary.")

    start_index = content.find("[", match.start())
    end_index = find_matching_delimiter(content, start_index, "[", "]")
    return content[start_index : end_index + 1]


def parse_top_level_entries(object_content: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    index = 1

    while index < len(object_content) - 1:
        while index < len(object_content) - 1 and object_content[index] in " \t\r\n,":
            index += 1

        if index >= len(object_content) - 1 or object_content[index] == "}":
            break

        key_match = TS_STRING_RE.match(object_content, index)
        if not key_match:
            index += 1
            continue

        key = parse_ts_string(key_match.group(1))
        index = key_match.end()

        while index < len(object_content) and object_content[index] in " \t\r\n":
            index += 1

        if index >= len(object_content) or object_content[index] != ":":
            continue
        index += 1

        while index < len(object_content) and object_content[index] in " \t\r\n":
            index += 1

        if index >= len(object_content) or object_content[index] != "{":
            continue

        block_start = index
        block_end = find_matching_brace(object_content, block_start)
        entries[key] = object_content[block_start : block_end + 1]
        index = block_end + 1

    return entries


def parse_description_map(entry_block: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    description_match = re.search(r'"description"\s*:\s*\[(.*?)\]', entry_block, re.DOTALL)
    if not description_match:
        return descriptions

    for item_match in re.finditer(r"\{(.*?)\}", description_match.group(1), re.DOTALL):
        item_block = item_match.group(1)
        system_match = re.search(r'"system"\s*:\s*"((?:\\.|[^"\\])*)"', item_block)
        text_match = re.search(r'"text"\s*:\s*"((?:\\.|[^"\\])*)"', item_block)
        if not system_match or not text_match:
            continue
        system = parse_ts_string(system_match.group(1)).lower()
        text = parse_ts_string(text_match.group(1))
        descriptions[system] = text

    return descriptions


def parse_translation_entries(content: str, export_name: str, language: str) -> dict[str, TranslationEntry]:
    export_object = extract_export_object(content, export_name)
    language_object = extract_language_object(export_object, language)
    entries: dict[str, TranslationEntry] = {}

    for key, block in parse_top_level_entries(language_object).items():
        title_match = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', block)
        if not title_match:
            continue
        entries[key] = TranslationEntry(
            title=parse_ts_string(title_match.group(1)),
            descriptions=parse_description_map(block),
        )

    return entries


def parse_ts_field(block: str, field_name: str) -> str:
    match = re.search(rf'"?{re.escape(field_name)}"?\s*:\s*"((?:\\.|[^"\\])*)"', block)
    return parse_ts_string(match.group(1)) if match else ""


def parse_faction_entry_list(array_content: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    index = 1

    while index < len(array_content) - 1:
        while index < len(array_content) - 1 and array_content[index] in " \t\r\n,":
            index += 1

        if index >= len(array_content) - 1 or array_content[index] == "]":
            break

        if array_content[index] != "{":
            index += 1
            continue

        block_end = find_matching_brace(array_content, index)
        block = array_content[index : block_end + 1]
        entries.append(
            {
                "systemCode": parse_ts_field(block, "systemCode").upper(),
                "armyName": parse_ts_field(block, "armyName"),
                "introduction": parse_ts_field(block, "introduction"),
                "backgroundStory": parse_ts_field(block, "backgroundStory"),
            }
        )
        index = block_end + 1

    return entries


def parse_faction_entries(content: str, language: str) -> dict[tuple[str, str], dict[str, str]]:
    try:
        export_object = extract_export_object(content, "factionData")
        source_entries = parse_faction_entry_list(extract_language_array(export_object, "en"))
        translated_entries = parse_faction_entry_list(extract_language_array(export_object, language))
    except ValueError:
        return {}
    entries: dict[tuple[str, str], dict[str, str]] = {}

    for source_entry, translated_entry in zip(source_entries, translated_entries):
        system_code = source_entry.get("systemCode", "").upper()
        army_name = source_entry.get("armyName", "")
        if not system_code or not army_name:
            continue
        entries[(system_code, army_name)] = translated_entry

    return entries


def parse_json_description_map(entry: dict[str, Any]) -> dict[str, str]:
    descriptions: dict[str, str] = {}

    for item in entry.get("description") or []:
        if not isinstance(item, dict):
            continue
        system = str(item.get("system", "")).lower()
        text = item.get("text")
        if system and isinstance(text, str):
            descriptions[system] = text

    return descriptions


def parse_json_translation_entries(payload: dict[str, Any], section_name: str, language: str) -> dict[str, TranslationEntry]:
    section = payload.get(section_name)
    if not isinstance(section, dict):
        return {}

    language_entries = section.get(language)
    if not isinstance(language_entries, dict):
        return {}

    entries: dict[str, TranslationEntry] = {}
    for key, entry in language_entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str):
            continue
        entries[key] = TranslationEntry(title=title, descriptions=parse_json_description_map(entry))

    return entries


def parse_json_faction_entries(payload: dict[str, Any], language: str) -> dict[tuple[str, str], dict[str, str]]:
    faction_data = payload.get("factionData")
    if not isinstance(faction_data, dict):
        return {}

    source_entries = faction_data.get("en")
    translated_entries = faction_data.get(language)
    if not isinstance(source_entries, list) or not isinstance(translated_entries, list):
        return {}

    entries: dict[tuple[str, str], dict[str, str]] = {}
    for source_entry, translated_entry in zip(source_entries, translated_entries):
        if not isinstance(source_entry, dict) or not isinstance(translated_entry, dict):
            continue
        system_code = str(source_entry.get("systemCode", "")).upper()
        army_name = str(source_entry.get("armyName", ""))
        if not system_code or not army_name:
            continue
        entries[(system_code, army_name)] = {
            "armyName": str(translated_entry.get("armyName", "")),
            "introduction": str(translated_entry.get("introduction", "")),
            "backgroundStory": str(translated_entry.get("backgroundStory", "")),
        }

    return entries


def strip_translation_markup(value: str) -> str:
    cleaned = value.replace("<key>", "").replace("</key>", "")
    cleaned = cleaned.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"').replace("â€", '"')
    return normalize_text(cleaned).strip()


def extract_dictionary_payload(raw_content: str, source: str) -> str:
    stripped = raw_content.lstrip("\ufeff").strip()
    if stripped.startswith("export const "):
        return raw_content

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return raw_content

    if isinstance(payload, str) and payload.strip():
        return payload

    if isinstance(payload, dict):
        if isinstance(payload.get("commonRules"), dict) or isinstance(payload.get("commonSpells"), dict):
            return stripped

        for key in ("content", "dictionary", "raw", "source", "ts", "typescript"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

    raise ValueError(f"Unsupported dictionary response format from {source}.")


def fetch_dictionary_url(source: str) -> tuple[str, str]:
    logger.info("Loading translation dictionary from URL: %s", source)
    with urllib.request.urlopen(source, timeout=DICTIONARY_REQUEST_TIMEOUT_SECONDS) as response:
        content = response.read().decode("utf-8")
    return extract_dictionary_payload(content, source), source


def read_dictionary_source(dictionary_source: str | Path) -> tuple[str, str]:
    if isinstance(dictionary_source, Path):
        logger.info("Loading translation dictionary from local path: %s", dictionary_source)
        return dictionary_source.read_text(encoding="utf-8"), str(dictionary_source)

    source = str(dictionary_source).strip()
    if source.startswith(("http://", "https://")):
        if source == DEFAULT_DICTIONARY_SOURCE:
            try:
                return fetch_dictionary_url(source)
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                logger.warning(
                    "Primary dictionary source unavailable or invalid (%s). Falling back to legacy source: %s",
                    error,
                    FALLBACK_DICTIONARY_SOURCE,
                )
                return fetch_dictionary_url(FALLBACK_DICTIONARY_SOURCE)
        return fetch_dictionary_url(source)

    logger.info("Loading translation dictionary from path string: %s", source)
    return Path(source).read_text(encoding="utf-8"), source


def parse_translation_dictionary_content(content: str, resolved_source: str, language: str) -> TranslationDictionary:
    stripped_content = content.lstrip("\ufeff").strip()
    if stripped_content.startswith("{"):
        payload = json.loads(stripped_content)
        if isinstance(payload, dict):
            return TranslationDictionary(
                source=resolved_source,
                rules=parse_json_translation_entries(payload, "commonRules", language),
                spells=parse_json_translation_entries(payload, "commonSpells", language),
                factions=parse_json_faction_entries(payload, language),
            )

    return TranslationDictionary(
        source=resolved_source,
        rules=parse_translation_entries(content, "commonRules", language),
        spells=parse_translation_entries(content, "commonSpells", language),
        factions=parse_faction_entries(content, language),
    )


def merge_translation_dictionaries(primary: TranslationDictionary, fallback: TranslationDictionary) -> TranslationDictionary:
    rules = dict(primary.rules)
    for key, fallback_entry in fallback.rules.items():
        primary_entry = rules.get(key)
        if primary_entry is None:
            rules[key] = fallback_entry
            continue
        rules[key] = TranslationEntry(
            title=primary_entry.title or fallback_entry.title,
            descriptions={**fallback_entry.descriptions, **primary_entry.descriptions},
        )

    spells = dict(primary.spells)
    for key, fallback_entry in fallback.spells.items():
        primary_entry = spells.get(key)
        if primary_entry is None:
            spells[key] = fallback_entry
            continue
        spells[key] = TranslationEntry(
            title=primary_entry.title or fallback_entry.title,
            descriptions={**fallback_entry.descriptions, **primary_entry.descriptions},
        )

    factions = dict(primary.factions)
    for key, fallback_entry in fallback.factions.items():
        primary_entry = factions.get(key)
        if primary_entry is None:
            factions[key] = fallback_entry
            continue
        factions[key] = {
            "armyName": primary_entry.get("armyName") or fallback_entry.get("armyName", ""),
            "introduction": primary_entry.get("introduction") or fallback_entry.get("introduction", ""),
            "backgroundStory": primary_entry.get("backgroundStory") or fallback_entry.get("backgroundStory", ""),
        }

    return TranslationDictionary(
        source=primary.source,
        rules=rules,
        spells=spells,
        factions=factions,
    )


def load_translation_dictionary(dictionary_source: str | Path, language: str) -> TranslationDictionary:
    content, resolved_source = read_dictionary_source(dictionary_source)
    translations = parse_translation_dictionary_content(content, resolved_source, language)

    if str(dictionary_source).strip() == DEFAULT_DICTIONARY_SOURCE and resolved_source == DEFAULT_DICTIONARY_SOURCE:
        try:
            fallback_content, fallback_source = fetch_dictionary_url(FALLBACK_DICTIONARY_SOURCE)
            fallback_translations = parse_translation_dictionary_content(fallback_content, fallback_source, language)
            translations = merge_translation_dictionaries(translations, fallback_translations)
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            logger.warning("Legacy dictionary fallback unavailable or invalid: %s", error)

    return translations


def pick_translation_description(descriptions: dict[str, str], system_code: str) -> str:
    normalized_system = system_code.lower()
    return descriptions.get(normalized_system) or descriptions.get("all") or next(iter(descriptions.values()), "")


def translate_rule_name(value: str, title_map: dict[str, str]) -> str:
    for source, target in sorted(title_map.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(
            rf"(?<![A-Za-z]){re.escape(source)}(?P<suffix>\([^()]+\))?(?![A-Za-z])"
        )
        value = pattern.sub(lambda match: f"{target}{match.group('suffix') or ''}", value)
    return value


def should_log_missing_translation(translations: TranslationDictionary) -> bool:
    return str(translations.source).strip() in {DEFAULT_DICTIONARY_SOURCE, FALLBACK_DICTIONARY_SOURCE}


def log_missing_translation(message: str, *args: Any) -> None:
    missing_logger = get_or_create_file_logger("missing_translations", MISSING_TRANSLATIONS_LOG_FILE_PATH)
    missing_logger.info(message, *args)


def apply_translations(data: dict[str, Any], translations: TranslationDictionary) -> dict[str, Any]:
    title_map = {
        **{key: entry.title for key, entry in translations.rules.items()},
        **{key: entry.title for key, entry in translations.spells.items()},
    }
    system_code = str(data.get("systemCode", ""))
    army_name = str(data.get("armyName", ""))
    source_url = str(data.get("sourceUrl", "")).strip() or str(data.get("sourcePdf", "")).strip() or translations.source
    faction_translation = translations.factions.get((system_code.upper(), army_name))
    log_missing = should_log_missing_translation(translations)

    if faction_translation:
        for field_name in ("armyName", "introduction", "backgroundStory"):
            translated_value = faction_translation.get(field_name, "")
            if translated_value:
                data[field_name] = strip_translation_markup(translated_value)
            elif log_missing:
                log_missing_translation(
                    "Missing faction field translation: system=%s army=%s field=%s sourceUrl=%s",
                    system_code.upper(),
                    army_name,
                    field_name,
                    source_url,
                )
    elif log_missing:
        log_missing_translation(
            "Missing faction translation entry: system=%s army=%s sourceUrl=%s",
            system_code.upper(),
            army_name,
            source_url,
        )

    def translate_rules_section(items: list[dict[str, Any]], section_name: str) -> None:
        for item in items:
            source_name = str(item.get("name", ""))
            source_description = str(item.get("description", "")).strip()
            item["keywords"] = [source_name] if source_name else []
            translation = translations.rules.get(source_name)
            if not translation:
                if log_missing and source_name:
                    log_missing_translation(
                        "Missing rule translation: system=%s army=%s section=%s rule=%s englishDescription=%s sourceUrl=%s",
                        system_code.upper(),
                        army_name,
                        section_name,
                        source_name,
                        source_description,
                        source_url,
                    )
                continue
            item["name"] = strip_translation_markup(translation.title)
            description = pick_translation_description(translation.descriptions, system_code)
            if description:
                item.pop("description", None)
            elif item.get("description"):
                item["description"] = strip_translation_markup(str(item.get("description", "")))
            elif log_missing:
                log_missing_translation(
                    "Missing rule description translation: system=%s army=%s section=%s rule=%s englishDescription=%s sourceUrl=%s",
                    system_code.upper(),
                    army_name,
                    section_name,
                    source_name,
                    source_description,
                    source_url,
                )

    def translate_spells_section(items: list[dict[str, Any]]) -> None:
        for item in items:
            source_name = str(item.get("name", ""))
            source_description = str(item.get("description", "")).strip()
            item["keywords"] = [source_name] if source_name else []
            translation = translations.spells.get(source_name)
            if not translation:
                if log_missing and source_name:
                    log_missing_translation(
                        "Missing spell translation: system=%s army=%s spell=%s englishDescription=%s sourceUrl=%s",
                        system_code.upper(),
                        army_name,
                        source_name,
                        source_description,
                        source_url,
                    )
                continue
            item["name"] = strip_translation_markup(translation.title)
            description = pick_translation_description(translation.descriptions, system_code)
            if description:
                item.pop("description", None)
            elif item.get("description"):
                item["description"] = strip_translation_markup(str(item.get("description", "")))
            elif log_missing:
                log_missing_translation(
                    "Missing spell description translation: system=%s army=%s spell=%s englishDescription=%s sourceUrl=%s",
                    system_code.upper(),
                    army_name,
                    source_name,
                    source_description,
                    source_url,
                )

    translate_rules_section(data.get("armyWideSpecialRule", []), "armyWideSpecialRule")
    translate_rules_section(data.get("specialRules", []), "specialRules")
    translate_rules_section(data.get("auraSpecialRules", []), "auraSpecialRules")
    translate_spells_section(data.get("armySpells", []))

    for unit in data.get("units", []):
        unit["specialRules"] = [strip_translation_markup(translate_rule_name(rule, title_map)) for rule in unit.get("specialRules", [])]
        for weapon in unit.get("weapons", []):
            weapon["special"] = strip_translation_markup(translate_rule_name(weapon.get("special", ""), title_map))
        for upgrade in unit.get("upgrades", []):
            for option in upgrade.get("options", []):
                option["details"] = strip_translation_markup(translate_rule_name(option.get("details", ""), title_map))

    return data


def split_units(unit_lines: list[str]) -> list[list[str]]:
    units: list[list[str]] = []
    current: list[str] = []

    for line in unit_lines:
        if UNIT_HEADER_RE.match(line):
            if current:
                units.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        units.append(current)

    return units


def parse_weapon(line: str) -> dict[str, str] | None:
    match = WEAPON_RE.match(line)
    if not match:
        return None

    return {
        "name": match.group("name").strip(),
        "range": match.group("rng").strip(),
        "attacks": match.group("atk").strip(),
        "ap": match.group("ap").strip(),
        "special": match.group("spe").strip(),
    }


def parse_upgrade_option(line: str) -> dict[str, str]:
    match = PRICED_OPTION_RE.match(line)
    if not match:
        return {"name": line, "details": "", "cost": ""}

    text = match.group("text").strip()
    details = ""
    name = text
    if " (" in text and text.endswith(")"):
        name, details = text.split(" (", 1)
        name = name.strip()
        if "), " in details:
            details = f"({details}".strip()
        else:
            details = details[:-1].strip()

    return {"name": name, "details": details, "cost": match.group("cost").strip()}


def parse_upgrades(lines: list[str], start_index: int) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None
    pending_option = ""

    def flush_pending() -> None:
        nonlocal pending_option
        if pending_option and current_group is not None:
            current_group["options"].append(parse_upgrade_option(pending_option))
        pending_option = ""

    for line in lines[start_index:]:
        if UPGRADE_HEADING_RE.match(line):
            flush_pending()
            current_group = {"type": line, "options": []}
            groups.append(current_group)
            continue

        if current_group is None:
            continue

        if pending_option:
            pending_option = f"{pending_option} {line}"
        else:
            pending_option = line

        if PRICED_OPTION_RE.match(pending_option) or current_group["type"] == "Upgrade SPE":
            flush_pending()

    flush_pending()
    return groups


def parse_unit(lines: list[str], page_number: int) -> dict[str, Any] | None:
    header = UNIT_HEADER_RE.match(lines[0])
    if not header:
        return None

    unit: dict[str, Any] = {
        "name": header.group("name").strip(),
        "size": int(header.group("size")),
        "cost": int(header.group("cost")),
        "page": page_number,
        "uniqueHero": bool((header.group("unique_marker") or "").strip()),
        "quality": "",
        "defense": "",
        "tough": "",
        "specialRules": [],
        "weapons": [],
        "upgrades": [],
    }

    stat_index = next((index for index, line in enumerate(lines) if STAT_RE.match(line)), -1)
    if stat_index >= 0:
        stat_match = STAT_RE.match(lines[stat_index])
        if stat_match:
            unit["quality"] = stat_match.group("quality")
            unit["defense"] = stat_match.group("defense")
            unit["tough"] = stat_match.group("tough") or ""

        weapon_header_index = next((index for index, line in enumerate(lines) if line == "Weapon RNG ATK AP SPE"), -1)
        if weapon_header_index > stat_index:
            special_rules = " ".join(lines[stat_index + 1 : weapon_header_index]).strip()
            unit["specialRules"] = [rule.strip() for rule in special_rules.split(",") if rule.strip()]
            unit["uniqueHero"] = unit["uniqueHero"] or ("Hero" in unit["specialRules"] and "Unique" in unit["specialRules"])
        else:
            weapon_header_index = -1

        upgrade_index = next(
            (index for index, line in enumerate(lines) if index > weapon_header_index and UPGRADE_HEADING_RE.match(line)),
            len(lines),
        )

        if weapon_header_index >= 0:
            for weapon_line in lines[weapon_header_index + 1 : upgrade_index]:
                weapon = parse_weapon(weapon_line)
                if weapon is not None:
                    unit["weapons"].append(weapon)

        unit["upgrades"] = parse_upgrades(lines, upgrade_index)

    return unit


def parse_units(pages: list[PdfPage]) -> list[dict[str, Any]]:
    parsed_units: list[dict[str, Any]] = []

    for page in pages[3:]:
        lines = compact_lines(page.text)
        if lines and re.match(r"^[A-Z]+ - .+ V[\d.]+$", lines[0]):
            lines = lines[1:]
        lines = [line for line in lines if not line.isdigit()]

        for unit_lines in split_units(lines):
            unit = parse_unit(unit_lines, page.number)
            if unit is not None:
                parsed_units.append(unit)

    return parsed_units


def parse_pdf(pdf_path: Path) -> dict[str, Any]:
    pages = read_pages(pdf_path)
    cover_lines = compact_lines(pages[0].text if pages else "")
    rules_lines = compact_lines(pages[2].text if len(pages) >= 3 else "")
    header = next((line for line in cover_lines if re.match(r"^[A-Z]+ - .+ V[\d.]+$", line)), "")
    header_data = parse_header(header)

    army_wide_rule_text = extract_section(rules_lines, "ARMY-WIDE SPECIAL RULE", "SPECIAL RULES")

    return {
        "sourcePdf": pdf_path.as_posix(),
        **header_data,
        "introduction": extract_section(cover_lines, "INTRO", "ABOUT OPR"),
        "backgroundStory": extract_section(cover_lines, "BACKGROUND STORY"),
        "armyWideSpecialRule": parse_rules(army_wide_rule_text),
        "specialRules": parse_rules(extract_section(rules_lines, "SPECIAL RULES", "AURA SPECIAL RULES")),
        "auraSpecialRules": parse_rules(extract_section(rules_lines, "AURA SPECIAL RULES", "ARMY SPELLS")),
        "armySpells": parse_spells(extract_section(rules_lines, "ARMY SPELLS")),
        "units": parse_units(pages),
    }


def main() -> None:
    cli_logger = setup_script_logging("extract_army_pdf")
    parser = argparse.ArgumentParser(description="Extract an OPR army PDF into a JSON data file.")
    parser.add_argument("pdf", type=Path, help="Path to the PDF to extract.")
    parser.add_argument("-o", "--output", type=Path, help="Path to write JSON output.")
    parser.add_argument(
        "--language",
        default="fr",
        help="Target translation language from common-rules.dictionary.ts. Use 'en' to keep extracted text as-is.",
    )
    parser.add_argument(
        "--dictionary",
        default=DEFAULT_DICTIONARY_SOURCE,
        help="Path or URL to the common rules dictionary file.",
    )
    args = parser.parse_args()
    cli_logger.info(
        "Starting PDF extraction: pdf=%s output=%s language=%s",
        args.pdf,
        args.output,
        args.language,
    )

    try:
        data = parse_pdf(args.pdf)
        translations = load_translation_dictionary(args.dictionary, args.language.lower())
        data = apply_translations(data, translations)
        output = json.dumps(data, ensure_ascii=False, indent=2)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(f"{output}\n", encoding="utf-8")
            cli_logger.info("Wrote extracted JSON to %s", args.output)
        else:
            cli_logger.info("Printed extracted JSON to stdout")
            print(output)

        cli_logger.info("PDF extraction completed successfully. Log file: %s", LOG_FILE_PATH)
    except Exception:
        cli_logger.exception("PDF extraction failed for pdf=%s", args.pdf)
        raise


if __name__ == "__main__":
    main()
