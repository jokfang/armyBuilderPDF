from __future__ import annotations

import argparse
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from extract_army_pdf import apply_translations, load_translation_dictionary


GAME_SYSTEMS = {
    "grimdark-future": {"id": 2, "code": "GF", "name": "Grimdark Future"},
    "grimdark-future-firefight": {"id": 3, "code": "GFF", "name": "Grimdark Future: Firefight"},
    "age-of-fantasy": {"id": 4, "code": "AOF", "name": "Age of Fantasy"},
    "age-of-fantasy-skirmish": {"id": 5, "code": "AOFS", "name": "Age of Fantasy: Skirmish"},
    "age-of-fantasy-regiments": {"id": 6, "code": "AOFR", "name": "Age of Fantasy: Regiments"},
}


def normalize_text(value: str) -> str:
    replacements = {
        "</key>": "",
        "<key>": "",
        "â€™": "'",
        "â??": "'",
        "ā??": "'",
        "â€œ": '"',
        "â€": '"',
        "â€": '"',
        "â€\"": '"',
        "ā?¯": '"',
        "â?": '"',
        "â?¯": '"',
        "Arâ??": "Ar'",
        "Arā??": "Ar'",
        "Motherâ??": "Mother's",
        "Motherā??": "Mother's",
    }
    normalized = str(value or "")
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    if any(marker in normalized for marker in ("Ã", "Â", "â", "Ä")):
        try:
            normalized = normalized.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    normalized = re.sub(r"(\r\n|\r|\n){3,}", "\n\n", normalized)
    return normalized.strip()


def slugify_filename(value: str) -> str:
    normalized = normalize_text(value).lower()
    normalized = (
        normalized.replace("œ", "oe")
        .replace("æ", "ae")
    )
    ascii_text = (
        unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def parse_army_book_url(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url.strip())
    segments = [segment for segment in parsed.path.split("/") if segment]
    try:
        army_info_index = segments.index("army-info")
    except ValueError as error:
        raise ValueError("URL must contain /army-info/") from error

    if len(segments) < army_info_index + 3:
        raise ValueError("Army book URL is missing the game system or book uid.")

    game_system_slug = segments[army_info_index + 1]
    book_uid = segments[army_info_index + 2]
    game_system = GAME_SYSTEMS.get(game_system_slug)
    if game_system is None:
        raise ValueError(f"Unsupported game system slug: {game_system_slug}")

    return {
        "sourceUrl": url.strip(),
        "bookUid": book_uid,
        "gameSystemSlug": game_system_slug,
        "gameSystemId": game_system["id"],
        "isBeta": "beta" in parsed.netloc,
    }


def fetch_army_book(parsed_url: dict[str, Any]) -> dict[str, Any]:
    host = "https://army-forge-beta.onepagerules.com" if parsed_url["isBeta"] else "https://army-forge.onepagerules.com"
    api_url = (
        f"{host}/api/army-books/{parsed_url['bookUid']}?"
        f"gameSystem={parsed_url['gameSystemId']}&simpleMode=false"
    )
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def count_rule_occurrences(units: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        unique_names = {rule.get("name", "") for rule in unit.get("rules", [])}
        for name in unique_names:
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
    return counts


def format_special_rule_label(rule: dict[str, Any]) -> str:
    label = str(rule.get("label") or rule.get("name") or "").strip()
    if label:
        return normalize_text(label)

    name = str(rule.get("name") or "").strip()
    rating = rule.get("rating")
    if rating in {None, ""}:
        return normalize_text(name)
    return normalize_text(f"{name}({rating})")


def format_ap(rules: list[dict[str, Any]]) -> str:
    for rule in rules:
        if rule.get("name") == "AP":
            match = re.search(r"\(([^)]+)\)", format_special_rule_label(rule))
            return match.group(1) if match else str(rule.get("rating") or "-")
    return "-"


def format_rule_list(rules: list[dict[str, Any]]) -> str:
    labels = [format_special_rule_label(rule) for rule in rules if rule.get("name") != "AP"]
    return ", ".join(label for label in labels if label) or "-"


def format_weapon(weapon: dict[str, Any]) -> dict[str, str]:
    weapon_rules = list(weapon.get("specialRules", []))
    range_value = weapon.get("range")
    return {
        "name": normalize_text(weapon.get("name", "")),
        "range": f'{range_value}"' if isinstance(range_value, (int, float)) and range_value > 0 else "-",
        "attacks": f'A{weapon.get("attacks", 0)}',
        "ap": format_ap(weapon_rules),
        "special": format_rule_list(weapon_rules),
    }


def format_gain_name(gain: dict[str, Any]) -> str:
    count = int(gain.get("count") or 1)
    name = normalize_text(gain.get("name", ""))
    return f"{count}x {name}" if count > 1 else name


def format_gain_details(gain: dict[str, Any]) -> str:
    gain_type = gain.get("type")
    if gain_type == "ArmyBookWeapon":
        parts = [f'A{gain.get("attacks", 0)}']
        range_value = gain.get("range")
        if isinstance(range_value, (int, float)) and range_value > 0:
            parts.insert(0, f'{range_value}"')
        ap = format_ap(list(gain.get("specialRules", [])))
        if ap != "-":
            parts.append(f"AP({ap})")
        other_rules = format_rule_list(list(gain.get("specialRules", [])))
        if other_rules != "-":
            parts.append(other_rules)
        return ", ".join(parts)

    if gain_type == "ArmyBookItem":
        content = list(gain.get("content", []))
        return ", ".join(format_special_rule_label(item) for item in content if item.get("name"))

    return normalize_text(gain.get("label") or gain.get("name") or "")


def format_option(option: dict[str, Any]) -> dict[str, str]:
    gains = list(option.get("gains", []))
    first_gain = gains[0] if gains else {}
    raw_cost = option.get("cost")
    if raw_cost in {None, ""}:
        costs = option.get("costs", [])
        raw_cost = costs[0]["cost"] if costs else 0

    return {
        "name": format_gain_name(first_gain) if first_gain else normalize_text(option.get("label", "")),
        "details": format_gain_details(first_gain) if first_gain else normalize_text(option.get("label", "")),
        "cost": "Free" if not raw_cost else f"+{raw_cost}pts",
    }


def build_upgrades(unit: dict[str, Any], package_by_uid: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for package_uid in unit.get("upgrades", []):
        package = package_by_uid.get(package_uid)
        if package is None:
            continue
        for section in package.get("sections", []):
            options = [format_option(option) for option in section.get("options", [])]
            if not options:
                continue
            groups.append(
                {
                    "type": normalize_text(section.get("label", "")),
                    "options": options,
                }
            )
    return groups


def build_unit(unit: dict[str, Any], package_by_uid: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rules = list(unit.get("rules", []))
    special_rules = [format_special_rule_label(rule) for rule in rules if rule.get("name")]
    tough = next((re.search(r"\(([^)]+)\)", label).group(1) for label in special_rules if re.search(r"^Tough\(([^)]+)\)$", label)), "")
    unique_hero = any(rule.get("name") == "Hero" for rule in rules) and any(rule.get("name") == "Unique" for rule in rules)
    result = {
        "name": normalize_text(unit.get("name", "")),
        "size": int(unit.get("size") or 0),
        "cost": int(unit.get("cost") or 0),
        "page": 0,
        "uniqueHero": unique_hero,
        "quality": f'{unit.get("quality", "")}+',
        "defense": f'{unit.get("defense", "")}+',
        "tough": tough,
        "specialRules": special_rules,
        "weapons": [format_weapon(weapon) for weapon in unit.get("weapons", [])],
        "upgrades": build_upgrades(unit, package_by_uid),
    }

    unit_type = normalize_text(unit.get("unitType", ""))
    if unit_type:
        result["unitType"] = unit_type

    return result


def extract_army_book_to_data(source_url: str, source: dict[str, Any]) -> dict[str, Any]:
    game_system = GAME_SYSTEMS.get(str(source.get("gameSystemSlug") or ""), {})
    system_code = str(source.get("aberration") or source.get("gameSystemKey") or game_system.get("code") or "")
    system_name = str(game_system.get("name") or source.get("gameSystemSlug") or "")

    custom_rules = [rule for rule in source.get("specialRules", []) if rule.get("coreType") != 1]
    rule_counts = count_rule_occurrences(list(source.get("units", [])))
    threshold = max(3, (len(source.get("units", [])) + 1) // 2)

    army_wide_rule_names = {
        rule.get("name", "")
        for rule in custom_rules
        if "Aura" not in str(rule.get("name", "")) and rule_counts.get(str(rule.get("name", "")), 0) >= threshold
    }

    package_by_uid = {package.get("uid", ""): package for package in source.get("upgradePackages", [])}

    return {
        "sourcePdf": source_url,
        "sourceUrl": source_url,
        "sourceBookUid": source.get("uid", ""),
        "systemCode": system_code,
        "systemName": system_name,
        "armyName": normalize_text(source.get("name", "")),
        "version": str(source.get("versionString") or ""),
        "introduction": normalize_text(source.get("background", "")),
        "backgroundStory": normalize_text(source.get("backgroundFull") or source.get("background", "")),
        "armyWideSpecialRule": [
            {
                "name": normalize_text(rule.get("name", "")),
                "description": normalize_text(rule.get("description", "")),
            }
            for rule in custom_rules
            if rule.get("name", "") in army_wide_rule_names
        ],
        "specialRules": [
            {
                "name": normalize_text(rule.get("name", "")),
                "description": normalize_text(rule.get("description", "")),
            }
            for rule in custom_rules
            if "Aura" not in str(rule.get("name", "")) and rule.get("name", "") not in army_wide_rule_names
        ],
        "auraSpecialRules": [
            {
                "name": normalize_text(rule.get("name", "")),
                "description": normalize_text(rule.get("description", "")),
            }
            for rule in custom_rules
            if "Aura" in str(rule.get("name", ""))
        ],
        "armySpells": [
            {
                "name": normalize_text(spell.get("name", "")),
                "cost": int(spell.get("threshold") or 0),
                "description": normalize_text(spell.get("effect", "")),
            }
            for spell in source.get("spells", [])
        ],
        "units": [build_unit(unit, package_by_uid) for unit in source.get("units", [])],
    }


def make_output_basename(data: dict[str, Any]) -> str:
    system_code = str(data.get("systemCode") or "army").lower()
    version = str(data.get("version") or "0.0.0")
    army_name = str(data.get("armyName") or "unknown-army")
    army_slug = slugify_filename(army_name) or "unknown-army"
    return f"{system_code}-{army_slug}-{version}"


def extract_from_url(
    url: str,
    *,
    language: str = "fr",
    dictionary_path: Path = Path("public/locales/rules/common-rules.dictionary.ts"),
) -> tuple[dict[str, Any], str]:
    parsed_url = parse_army_book_url(url)
    source = fetch_army_book(parsed_url)
    data = extract_army_book_to_data(url, source)
    translations = load_translation_dictionary(dictionary_path, language.lower())
    data = apply_translations(data, translations)
    return data, make_output_basename(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract an OPR Army Forge army-info URL into a JSON data file.")
    parser.add_argument("url", help="Army Forge army-info URL.")
    parser.add_argument("-o", "--output", type=Path, help="Path to write JSON output.")
    parser.add_argument(
        "--language",
        default="fr",
        help="Target translation language from common-rules.dictionary.ts. Use 'en' to keep extracted text as-is.",
    )
    parser.add_argument(
        "--dictionary",
        type=Path,
        default=Path("public/locales/rules/common-rules.dictionary.ts"),
        help="Path to the common rules dictionary file.",
    )
    args = parser.parse_args()

    data, basename = extract_from_url(args.url, language=args.language, dictionary_path=args.dictionary)
    output_path = args.output or Path("ArmyForgeFR/src/data/generated") / f"{basename}.json"
    output = json.dumps(data, ensure_ascii=False, indent=2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{output}\n", encoding="utf-8")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
