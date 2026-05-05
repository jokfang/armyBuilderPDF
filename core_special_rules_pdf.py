from __future__ import annotations

import logging
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from extract_army_pdf import (
    DEFAULT_DICTIONARY_SOURCE,
    load_translation_dictionary,
    pick_translation_description,
    strip_translation_markup,
)
from generate_army_pdf import (
    MARGIN_BOTTOM,
    MARGIN_TOP,
    MARGIN_X,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PdfBuilder,
    TextStyle,
    normalize_sort_text,
    original_rule_name,
    repair_text,
    wrap_text,
)


logger = logging.getLogger(__name__)

DEFAULT_CORE_RULES_PDF_LIST = Path("core-rules-pdf.txt")

SYSTEM_LABELS = {
    "GF": "Grimdark Future",
    "AOF": "Age of Fantasy",
}


def normalize_system_code(value: str) -> str:
    normalized = "".join(char for char in value.upper() if char.isalnum())
    aliases = {
        "GRIMDARKFUTURE": "GF",
        "AGEOFFANTASY": "AOF",
        "AOF": "AOF",
        "AOFF": "AOF",
        "GF": "GF",
    }
    return aliases.get(normalized, normalized)


def read_core_rules_pdf_urls(list_path: Path = DEFAULT_CORE_RULES_PDF_LIST) -> dict[str, str]:
    urls: dict[str, str] = {}
    for line_number, raw_line in enumerate(list_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip().lower().startswith(("http://", "https://")):
            system_code, url = parts
        elif "=" in line:
            system_code, url = line.split("=", 1)
        elif ":" in line and not line.lower().startswith(("http://", "https://")):
            system_code, url = line.split(":", 1)
        else:
            if len(parts) != 2:
                raise ValueError(f"Invalid core rules PDF config line {line_number}: {raw_line}")
            system_code, url = parts

        normalized_system_code = normalize_system_code(system_code.strip())
        url = url.strip()
        if not normalized_system_code or not url:
            raise ValueError(f"Invalid core rules PDF config line {line_number}: {raw_line}")
        urls[normalized_system_code] = url

    return urls


def build_system_special_rules_data(
    system_code: str,
    *,
    dictionary_source: str | Path = DEFAULT_DICTIONARY_SOURCE,
    language: str = "fr",
) -> dict[str, Any]:
    translations = load_translation_dictionary(dictionary_source, language.lower())
    normalized_system_code = normalize_system_code(system_code)
    rules: list[dict[str, Any]] = []
    aura_rules: list[dict[str, Any]] = []

    for source_name, entry in translations.rules.items():
        description = pick_translation_description(entry.descriptions, normalized_system_code)
        if not description:
            continue
        rule = {
            "name": strip_translation_markup(entry.title),
            "description": strip_translation_markup(description),
            "keywords": [source_name],
        }
        if rule_contains_aura(rule):
            aura_rules.append(rule)
        else:
            rules.append(rule)

    return {
        "systemCode": normalized_system_code,
        "systemName": SYSTEM_LABELS.get(normalized_system_code, normalized_system_code),
        "armyName": "Regles Speciales",
        "version": "",
        "armyWideSpecialRule": [],
        "specialRules": rules,
        "auraSpecialRules": aura_rules,
        "armySpells": [],
    }


def download_pdf(url: str, output_path: Path) -> None:
    logger.info("Downloading core rules PDF: %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        output_path.write_bytes(response.read())


def rule_contains_aura(item: dict[str, Any]) -> bool:
    names = [str(item.get("name", ""))]
    names.extend(str(keyword) for keyword in item.get("keywords", []))
    return any(re.search(r"\baura\b", name, flags=re.IGNORECASE) for name in names)


def display_core_rule_title(item: dict[str, Any]) -> str:
    translated_name = str(item.get("name", "")).strip()
    source_name = original_rule_name(item)
    if not source_name:
        return translated_name
    if not translated_name:
        return source_name
    return f"{source_name} [ {translated_name} ]"


def build_all_special_rules_pdf(data: dict[str, Any], output_path: Path) -> None:
    system_code = repair_text(data.get("systemCode") or "")
    header = f"{system_code} - REGLES SPECIALES".strip()
    pdf = PdfBuilder(header)
    page = pdf.current
    y = PAGE_HEIGHT - MARGIN_TOP - 18
    column_count = 3
    col_gap = 16.0
    col_width = (PAGE_WIDTH - 2 * MARGIN_X - col_gap * (column_count - 1)) / column_count
    x_values = [MARGIN_X + index * (col_width + col_gap) for index in range(column_count)]
    body_width_safe = max(col_width - 10.0, 24.0)
    title_width_safe = max(col_width - 28.0, 24.0)
    title_style = TextStyle("F2", 7.1, 8.1)
    body_style = TextStyle("F1", 6.8, 7.7)
    heading_style = TextStyle("F2", 10.0, 12.0)
    col = 0
    column_top_y = y

    def start_new_page() -> None:
        nonlocal page, y, col, column_top_y
        page = pdf.new_page()
        column_top_y = PAGE_HEIGHT - MARGIN_TOP - 18
        y = column_top_y
        col = 0

    def start_new_column() -> None:
        nonlocal y, col
        if col < column_count - 1:
            col += 1
            y = column_top_y
            return
        start_new_page()

    def draw_heading(title: str) -> None:
        nonlocal y, column_top_y
        heading_height = heading_style.leading + 18.0
        if y - heading_height < MARGIN_BOTTOM:
            start_new_column()
        page.text(x_values[col] if col else MARGIN_X, y, title, heading_style)
        y -= 4
        page.line(x_values[col] if col else MARGIN_X, y, x_values[col] + col_width, y, 0.4)
        y -= 14
        if col == 0:
            column_top_y = y

    def draw_rule(item: dict[str, Any]) -> None:
        nonlocal y
        title = f"{repair_text(display_core_rule_title(item)).strip()}:"
        description = repair_text(item.get("description") or "")
        lines = [(line, title_style) for line in wrap_text(title, title_width_safe, title_style.size)]
        lines.extend((line, body_style) for line in wrap_text(description, body_width_safe, body_style.size))
        block_height = sum(style.leading for _, style in lines) + 4.0

        if y - block_height < MARGIN_BOTTOM:
            start_new_column()

        for line, style in lines:
            page.text(x_values[col] + 2.0, y, line, style)
            y -= style.leading
        y -= 4.0

    def sorted_rules(section_name: str) -> list[dict[str, Any]]:
        return sorted(
            list(data.get(section_name, [])),
            key=lambda item: normalize_sort_text(original_rule_name(item)),
        )

    for heading, section_name in (
        ("REGLES SPECIALES", "specialRules"),
        ("REGLES SPECIALES D'AURA", "auraSpecialRules"),
    ):
        rules = sorted_rules(section_name)
        if not rules:
            continue
        draw_heading(heading)
        for item in rules:
            draw_rule(item)
        y -= 6.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_pdf(output_path)


def merge_core_pages_with_rules(
    core_pdf_path: Path,
    rules_pdf_path: Path,
    output_path: Path,
    *,
    core_page_count: int = 2,
) -> None:
    writer = PdfWriter()
    core_reader = PdfReader(str(core_pdf_path))
    rules_reader = PdfReader(str(rules_pdf_path))

    for page in core_reader.pages[:core_page_count]:
        writer.add_page(page)
    for page in rules_reader.pages:
        writer.add_page(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        writer.write(output_file)
    logger.info("Wrote system special rules PDF to %s", output_path)


def build_system_special_rules_pdf(
    system_code: str,
    core_pdf_url: str,
    output_path: Path,
    *,
    dictionary_source: str | Path = DEFAULT_DICTIONARY_SOURCE,
    language: str = "fr",
    print_friendly: bool = False,
) -> None:
    data = build_system_special_rules_data(
        system_code,
        dictionary_source=dictionary_source,
        language=language,
    )

    with tempfile.TemporaryDirectory(prefix="opr-core-rules-") as temp_dir:
        temp_path = Path(temp_dir)
        core_pdf_path = temp_path / f"{normalize_system_code(system_code).lower()}-core.pdf"
        rules_pdf_path = temp_path / f"{normalize_system_code(system_code).lower()}-rules.pdf"

        download_pdf(core_pdf_url, core_pdf_path)
        build_all_special_rules_pdf(data, rules_pdf_path)
        merge_core_pages_with_rules(core_pdf_path, rules_pdf_path, output_path)


def build_system_special_rules_pdfs(
    output_dir: Path,
    *,
    config_path: Path = DEFAULT_CORE_RULES_PDF_LIST,
    dictionary_source: str | Path = DEFAULT_DICTIONARY_SOURCE,
    language: str = "fr",
    print_friendly: bool = False,
) -> list[Path]:
    urls = read_core_rules_pdf_urls(config_path)
    generated_paths: list[Path] = []

    for system_code, core_pdf_url in sorted(urls.items()):
        output_path = output_dir / f"{system_code.lower()}-core-special-rules.pdf"
        build_system_special_rules_pdf(
            system_code,
            core_pdf_url,
            output_path,
            dictionary_source=dictionary_source,
            language=language,
            print_friendly=print_friendly,
        )
        generated_paths.append(output_path)

    return generated_paths
