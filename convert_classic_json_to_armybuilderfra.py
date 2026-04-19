from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from extract_army_pdf import (
    DEFAULT_DICTIONARY_SOURCE,
    load_translation_dictionary,
    pick_translation_description,
    strip_translation_markup,
)
from extract_army_web import normalize_text
from logging_utils import LOG_FILE_PATH, setup_script_logging


logger = logging.getLogger(__name__)

CLASSIC_OUTPUT_DIR = Path("generated/JsonArmyBuilderFRA")

ARMY_WIDE_RULE_DETAIL = "Règle spéciale de l'armée"
SPECIAL_RULE_DETAIL = "Règles spéciales"
AURA_RULE_DETAIL = "Règles spéciales d'Aura"

HERO_UNIT_TYPES = {"Héro", "Hero", "Héro Narratif", "Hero Narratif"}
LIGHT_VEHICLE_UNIT_TYPES = {"Véhicule léger / Petit monstre", "Vehicule leger / Petit monstre"}
_TRANSLATION_CACHE: dict[str, Any] = {}
LOCAL_DICTIONARY_CANDIDATES = [
    Path("__tmp_common_rules_utf8.ts"),
    Path("__tmp_common_rules.ts"),
]


def is_classic_json(data: Any) -> bool:
    return isinstance(data, dict) and "faction" in data and "game" in data and "units" in data


def is_generated_json(data: Any) -> bool:
    return isinstance(data, dict) and "systemCode" in data and "armyName" in data and "units" in data


def strip_version_prefix(value: Any) -> str:
    version = normalize_text(value)
    return re.sub(r"^[A-Za-z]{2,5}-", "", version)


def add_fr_version_prefix(value: Any) -> str:
    version = strip_version_prefix(value)
    return f"FR-{version}" if version else ""


def slugify_classic_filename(value: Any) -> str:
    normalized = normalize_text(value).lower()
    ascii_text = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def make_classic_output_name(data: dict[str, Any]) -> str:
    faction_slug = slugify_classic_filename(data.get("faction", "")) or "unknown_faction"
    game_slug = slugify_classic_filename(data.get("game", ""))
    system_suffix = ""
    if "age_of_fantasy_regiments" in game_slug:
        system_suffix = "aofr"
    elif "age_of_fantasy_skirmish" in game_slug:
        system_suffix = "aofs"
    elif "age_of_fantasy" in game_slug:
        system_suffix = "aof"
    elif "grimdark_future_firefight" in game_slug:
        system_suffix = "gff"
    elif "grimdark_future" in game_slug:
        system_suffix = "gf"
    else:
        system_suffix = game_slug or "game"
    return f"{faction_slug}_{system_suffix}.json"


def parse_numeric_string(value: Any) -> int:
    match = re.search(r"\d+", normalize_text(value))
    return int(match.group(0)) if match else 0


def parse_cost_string(value: Any) -> int:
    text = normalize_text(value)
    if not text or text.casefold() == "free":
        return 0
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 0


def parse_coriace_from_rules(rule_names: list[Any]) -> int:
    for rule_name in rule_names:
        match = re.match(r"^Coriace\((\d+)\)$", normalize_text(rule_name))
        if match:
            return int(match.group(1))
    return 0


def get_translation_dictionary(language: str = "fr") -> Any:
    cache_key = language.lower()
    if cache_key not in _TRANSLATION_CACHE:
        last_error: Exception | None = None
        for candidate in LOCAL_DICTIONARY_CANDIDATES:
            if not candidate.exists():
                continue
            try:
                _TRANSLATION_CACHE[cache_key] = load_translation_dictionary(candidate, cache_key)
                return _TRANSLATION_CACHE[cache_key]
            except Exception as error:
                last_error = error

        try:
            _TRANSLATION_CACHE[cache_key] = load_translation_dictionary(DEFAULT_DICTIONARY_SOURCE, cache_key)
        except Exception as error:
            if last_error is not None:
                raise RuntimeError(
                    f"Unable to load translation dictionary from local cache or remote source: {last_error}; {error}"
                ) from error
            raise
    return _TRANSLATION_CACHE[cache_key]


def reconstruct_entry_description(
    entry: dict[str, Any],
    *,
    translations_by_keyword: dict[str, Any],
    system_code: str,
) -> str:
    explicit_description = normalize_text(entry.get("description", ""))
    if explicit_description:
        return explicit_description

    for keyword in entry.get("keywords", []):
        translation = translations_by_keyword.get(normalize_text(keyword))
        if translation is None:
            continue
        description = pick_translation_description(translation.descriptions, system_code)
        if description:
            return strip_translation_markup(description)

    return ""


def format_classic_rule_name(entry: dict[str, Any], *, use_keyword_prefix: bool = False) -> str:
    name = normalize_text(entry.get("name", ""))
    if not use_keyword_prefix:
        return name

    keywords = [normalize_text(keyword) for keyword in entry.get("keywords", []) if normalize_text(keyword)]
    if not keywords:
        return name
    return f"{keywords[0]} [ {name} ]"


def split_csv_details(value: Any) -> list[str]:
    text = normalize_text(value)
    return [part.strip() for part in text.split(",") if part.strip()]


def looks_like_weapon_details(details: str) -> bool:
    tokens = split_csv_details(details)
    return any(
        token.startswith("A")
        or token.startswith("PA(")
        or token.endswith('"')
        for token in tokens
    )


def parse_range_value(value: Any) -> int | str:
    text = normalize_text(value)
    if not text or text == "-":
        return "Mêlée"
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return text


def format_classic_weapon_from_generated(weapon: dict[str, Any]) -> dict[str, Any]:
    special_rules = split_csv_details(weapon.get("special", ""))
    if special_rules == ["-"]:
        special_rules = []
    return {
        "name": normalize_text(weapon.get("name", "")),
        "range": parse_range_value(weapon.get("range", "")),
        "attacks": parse_numeric_string(weapon.get("attacks", 0)),
        "armor_piercing": parse_numeric_string(weapon.get("ap", 0)),
        "special_rules": special_rules,
    }


def format_generated_weapon_from_classic(weapon: dict[str, Any]) -> dict[str, Any]:
    range_value = weapon.get("range")
    if isinstance(range_value, (int, float)) and range_value > 0:
        formatted_range: int | str = int(range_value)
    else:
        formatted_range = "Mêlée"

    return {
        "name": normalize_text(weapon.get("name", "")),
        "range": formatted_range,
        "attacks": int(weapon.get("attacks") or 0),
        "armor_piercing": int(weapon.get("armor_piercing") or 0),
        "special_rules": [
            normalize_text(rule)
            for rule in weapon.get("special_rules", [])
            if normalize_text(rule)
        ],
    }


def parse_weapon_details_to_classic(name: str, details: str) -> dict[str, Any]:
    range_value: int | str = "Mêlée"
    attacks = 0
    armor_piercing = 0
    special_rules: list[str] = []

    for token in split_csv_details(details):
        if re.match(r'^\d+"$', token):
            range_value = int(token[:-1])
            continue
        if re.match(r"^A\d+$", token):
            attacks = parse_numeric_string(token)
            continue
        if re.match(r"^PA\(\d+\)$", token):
            armor_piercing = parse_numeric_string(token)
            continue
        special_rules.append(token)

    return {
        "name": normalize_text(name),
        "range": range_value,
        "attacks": attacks,
        "armor_piercing": armor_piercing,
        "special_rules": special_rules,
    }


def parse_mount_details_to_classic(name: str, details: str) -> dict[str, Any]:
    mount: dict[str, Any] = {
        "name": normalize_text(name),
        "weapon": [],
        "special_rules": [],
    }
    tokens = split_csv_details(details)
    if not tokens:
        return mount

    weapon_label = ""
    weapon_tokens: list[str] = []
    in_weapon = False

    for token in tokens:
        coriace_match = re.match(r"^Coriace\(\+?(\d+)\)$", token)
        if coriace_match and not in_weapon:
            mount["coriace_bonus"] = int(coriace_match.group(1))
            continue

        if ": " in token:
            in_weapon = True
            weapon_label, first_details = token.split(": ", 1)
            if first_details:
                weapon_tokens.append(first_details)
            continue

        if in_weapon:
            weapon_tokens.append(token)
            continue

        mount["special_rules"].append(token)

    if weapon_label:
        mount["weapon"].append(parse_weapon_details_to_classic(weapon_label, ", ".join(weapon_tokens)))

    return mount


def infer_classic_group_type(group_name: str, options: list[dict[str, Any]]) -> str:
    lowered = normalize_text(group_name).casefold()
    if "monture" in lowered:
        return "mount"
    if lowered.startswith("remplacer"):
        has_replaces = any(option.get("replaces") for option in options)
        return "conditional_weapon" if has_replaces else "weapon"
    if "rôle" in lowered or "role" in lowered:
        return "role"
    if any(isinstance(option.get("weapon"), dict) for option in options):
        return "weapon"
    return "upgrades"


def infer_classic_group_description(group_name: str, group_type: str) -> str:
    normalized_name = normalize_text(group_name).rstrip(":").strip()
    if normalized_name.casefold().startswith("remplacer"):
        return f"{normalized_name} :"
    if group_type in {"role", "mount", "upgrades", "weapon", "conditional_weapon"}:
        return "Améliorer avec une des options suivantes :"
    return normalized_name


def convert_upgrade_option_to_classic(group_name: str, option: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": normalize_text(option.get("name", "")),
        "cost": parse_cost_string(option.get("cost", 0)),
    }
    details = normalize_text(option.get("details", ""))

    if "monture" in normalize_text(group_name).casefold():
        result["mount"] = parse_mount_details_to_classic(result["name"], details)
        return result

    if normalize_text(group_name).casefold().startswith("remplacer") or looks_like_weapon_details(details):
        result["weapon"] = parse_weapon_details_to_classic(result["name"], details)
        return result

    result["special_rules"] = split_csv_details(details)
    return result


def convert_generated_unit_to_classic(unit: dict[str, Any]) -> dict[str, Any]:
    unit_type_label = normalize_text(unit.get("unitType", ""))
    unit_type = "hero" if unit_type_label in HERO_UNIT_TYPES else "unit"
    unit_detail = "light_vehicle" if unit_type_label in LIGHT_VEHICLE_UNIT_TYPES else unit_type

    special_rules = [
        normalize_text(rule)
        for rule in unit.get("specialRules", [])
        if normalize_text(rule) and not re.match(r"^Coriace\(\d+\)$", normalize_text(rule))
    ]
    coriace = parse_numeric_string(unit.get("tough", "")) or parse_coriace_from_rules(unit.get("specialRules", []))

    upgrade_groups: list[dict[str, Any]] = []
    for upgrade in unit.get("upgrades", []):
        group_name = normalize_text(upgrade.get("type", ""))
        options = [convert_upgrade_option_to_classic(group_name, option) for option in upgrade.get("options", [])]
        group_type = infer_classic_group_type(group_name, options)
        upgrade_groups.append(
            {
                "group": group_name,
                "type": group_type,
                "description": infer_classic_group_description(group_name, group_type),
                "options": options,
            }
        )

    result: dict[str, Any] = {
        "name": normalize_text(unit.get("name", "")),
        "type": unit_type,
        "unit_detail": unit_detail,
        "size": int(unit.get("size") or 0),
        "base_cost": int(unit.get("cost") or 0),
        "quality": parse_numeric_string(unit.get("quality", 0)),
        "defense": parse_numeric_string(unit.get("defense", 0)),
        "special_rules": special_rules,
        "weapon": [format_classic_weapon_from_generated(weapon) for weapon in unit.get("weapons", [])],
        "upgrade_groups": upgrade_groups,
    }
    if coriace:
        result["coriace"] = coriace
    return result


def convert_generated_to_classic(data: dict[str, Any]) -> dict[str, Any]:
    translations = get_translation_dictionary("fr")
    system_code = normalize_text(data.get("systemCode", ""))
    rule_translations_by_keyword = {
        normalize_text(keyword): translation
        for keyword, translation in translations.rules.items()
    }
    spell_translations_by_keyword = {
        normalize_text(keyword): translation
        for keyword, translation in translations.spells.items()
    }
    faction_special_rules: list[dict[str, Any]] = []

    for rule in data.get("armyWideSpecialRule", []):
        faction_special_rules.append(
            {
                "name": format_classic_rule_name(rule, use_keyword_prefix=True),
                "detail": ARMY_WIDE_RULE_DETAIL,
                "description": reconstruct_entry_description(
                    rule,
                    translations_by_keyword=rule_translations_by_keyword,
                    system_code=system_code,
                ),
            }
        )
    for rule in data.get("specialRules", []):
        faction_special_rules.append(
            {
                "name": format_classic_rule_name(rule, use_keyword_prefix=True),
                "detail": SPECIAL_RULE_DETAIL,
                "description": reconstruct_entry_description(
                    rule,
                    translations_by_keyword=rule_translations_by_keyword,
                    system_code=system_code,
                ),
            }
        )
    for rule in data.get("auraSpecialRules", []):
        faction_special_rules.append(
            {
                "name": format_classic_rule_name(rule, use_keyword_prefix=True),
                "detail": AURA_RULE_DETAIL,
                "description": reconstruct_entry_description(
                    rule,
                    translations_by_keyword=rule_translations_by_keyword,
                    system_code=system_code,
                ),
            }
        )

    spells: dict[str, dict[str, Any]] = {}
    for spell in data.get("armySpells", []):
        spell_name = normalize_text(spell.get("name", ""))
        spell_cost = int(spell.get("cost") or 0)
        spells[f"{spell_name} ({spell_cost})"] = {
            "cost": spell_cost,
            "description": reconstruct_entry_description(
                spell,
                translations_by_keyword=spell_translations_by_keyword,
                system_code=system_code,
            ),
        }

    return {
        "faction": normalize_text(data.get("armyName", "")),
        "game": normalize_text(data.get("systemName", "")),
        "version": add_fr_version_prefix(data.get("version", "")),
        "status": "complete",
        "description": normalize_text(data.get("introduction", "")),
        "history": normalize_text(data.get("backgroundStory", "")),
        "faction_special_rules": faction_special_rules,
        "spells": spells,
        "units": [convert_generated_unit_to_classic(unit) for unit in data.get("units", [])],
    }


def write_output_json(data: dict[str, Any], output_dir: Path, output_name: str | None = None) -> Path:
    final_name = output_name or make_classic_output_name(data)
    output_path = output_dir / final_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json.dumps(data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    return output_path


def process_file(input_path: Path, output_dir: Path) -> tuple[Path, str]:
    logger.info("Processing JSON file: %s", input_path)
    source_data = json.loads(input_path.read_text(encoding="utf-8"))

    if is_classic_json(source_data):
        output_path = write_output_json(source_data, output_dir)
        logger.info("Copied classic-format JSON to %s", output_path)
        return output_path, "copied"

    if is_generated_json(source_data):
        converted = convert_generated_to_classic(source_data)
        output_path = write_output_json(converted, output_dir)
        logger.info("Converted generated-format JSON to classic format in %s", output_path)
        return output_path, "converted"

    raise ValueError(f"Unsupported JSON structure for conversion: {input_path}")


def collect_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        output_dir_name = CLASSIC_OUTPUT_DIR.name.casefold()
        return sorted(
            path
            for path in input_path.rglob("*.json")
            if path.is_file() and output_dir_name not in {part.casefold() for part in path.parts}
        )
    raise FileNotFoundError(f"Input path not found: {input_path}")


def main() -> None:
    cli_logger = setup_script_logging("convert_classic_json_to_armybuilderfra")
    parser = argparse.ArgumentParser(
        description="Normalize JSON files to the classic schema used by legions_spectrales_aof.json."
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        default=Path("generated"),
        help="Path to a JSON file or a directory containing JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CLASSIC_OUTPUT_DIR,
        help="Directory where normalized JSON files should be written.",
    )
    args = parser.parse_args()
    cli_logger.info("Starting JSON normalization: input=%s output_dir=%s", args.input_path, args.output_dir)

    try:
        input_files = collect_input_files(args.input_path)
        if not input_files:
            raise SystemExit(f"No JSON files found in {args.input_path}")

        converted_count = 0
        copied_count = 0
        skipped_count = 0

        for input_file in input_files:
            try:
                output_path, action = process_file(input_file, args.output_dir)
                if action == "converted":
                    converted_count += 1
                else:
                    copied_count += 1
                print(output_path.as_posix())
            except ValueError as error:
                skipped_count += 1
                cli_logger.warning("Skipped file: %s ; %s", input_file, error)
                print(f"Skipped {input_file.as_posix()}: {error}")

        if converted_count == 0 and copied_count == 0:
            raise SystemExit("No supported JSON files were processed.")

        cli_logger.info(
            "JSON normalization completed: converted=%s copied=%s skipped=%s. Log file: %s",
            converted_count,
            copied_count,
            skipped_count,
            LOG_FILE_PATH,
        )
    except Exception:
        cli_logger.exception("JSON normalization failed for input=%s", args.input_path)
        raise


if __name__ == "__main__":
    main()
