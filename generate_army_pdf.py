from __future__ import annotations

import argparse
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract_army_pdf import (
    DEFAULT_DICTIONARY_SOURCE,
    load_translation_dictionary,
    pick_translation_description,
    strip_translation_markup,
)
from logging_utils import LOG_FILE_PATH, setup_script_logging


PAGE_WIDTH = 595.92
PAGE_HEIGHT = 842.88
MARGIN_X = 42.0
MARGIN_TOP = 42.0
MARGIN_BOTTOM = 38.0
HEADER_Y = PAGE_HEIGHT - 27.0
FOOTER_Y = 22.0

LABELS = {
    "intro": "INTRODUCTION",
    "about_opr": "AU SUJET D'OPR",
    "background_story": "HISTOIRE DE LA FACTION",
    "army_list_summary": "SOMMAIRE DE L'ARMEE",
    "name_size": "Nom [Taille]",
    "def": "Déf",
    "special_rules_table": "Règles Spéciales",
    "army_wide_special_rule": "REGLE SPECIALE DE L'ARMEE",
    "special_rules": "REGLE SPECIALES",
    "aura_special_rules": "REGLES SPECIALES D'AURA",
    "army_spells": "SORTS DE LA FACTION",
    "upgrade_spe": "Amélioration",
    "tough": "Coriace",
    "atk": "ATQ",
    "ap": "PA",
}

ABOUT_OPR_PARAGRAPHS = [
    "OPR (www.onepagerules.com) héberge de nombreux jeux gratuits conçus pour être rapides à apprendre et faciles à jouer.",
    "Ce projet a été réalisé par des joueurs, pour des joueurs, et ne peut exister que grace au généreux soutien de notre formidable communauté !",
    "Si vous souhaitez soutenir le développement de nos jeux, vous pouvez faire un don sur : www.patreon.com/onepagerules",
    "Merci de jouer a OPR !",
]

UNIT_TYPE_ORDER = [
    "Héro",
    "Unité de base",
    "Véhicule léger / Petit monstre",
    "Véhicule / Monstre",
    "Artillerie",
    "Aéronef",
    "Titan",
    "Héro Narratif"
]

UNTYPED_UNIT_GROUP_LABEL = "Autres unités"
COMMON_RULES_DICTIONARY_PATH = DEFAULT_DICTIONARY_SOURCE
_TRANSLATION_CACHE: dict[str, Any] = {}
PRINT_FRIENDLY_FILL = (0.0, 0.0, 0.0)
logger = logging.getLogger(__name__)


def pdf_text(value: Any) -> str:
    encoded = str(value).encode("cp1252", errors="replace")
    escaped: list[str] = []
    for byte in encoded:
        char = chr(byte)
        if char in {"\\", "(", ")"}:
            escaped.append(f"\\{char}")
        elif byte < 32 or byte > 126:
            escaped.append(f"\\{byte:03o}")
        else:
            escaped.append(char)
    return "".join(escaped)


def repair_text(value: Any) -> str:
    text = str(value or "")
    if any(marker in text for marker in ("Ã", "Â", "â", "Ä")):
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


def parse_hex_color(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6 or any(char not in "0123456789abcdefABCDEF" for char in text):
        return default
    return tuple(int(text[index : index + 2], 16) / 255 for index in range(0, 6, 2))


def color_luminance(color: tuple[float, float, float]) -> float:
    red, green, blue = color
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def is_print_friendly(data: dict[str, Any]) -> bool:
    return bool(data.get("__print_friendly"))


def get_section_fill(data: dict[str, Any]) -> tuple[float, float, float]:
    if is_print_friendly(data):
        return PRINT_FRIENDLY_FILL
    return parse_hex_color(data.get("factionColor"), (0.13, 0.12, 0.12))


def text_width(value: str, font_size: float) -> float:
    wide = sum(1 for char in value if char in "MW@#%&")
    narrow = sum(1 for char in value if char in " .,;:'!|ilIj")
    other = max(len(value) - wide - narrow, 0)
    return font_size * (wide * 0.78 + narrow * 0.28 + other * 0.48)


def wrap_text(value: str, max_width: float, font_size: float) -> list[str]:
    wrapped: list[str] = []

    for paragraph in str(value or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            wrapped.append("")
            continue

        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if text_width(candidate, font_size) <= max_width:
                line = candidate
            else:
                wrapped.append(line)
                line = word
        wrapped.append(line)

    return wrapped


def normalize_sort_text(value: Any) -> str:
    text = str(value or "").strip()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def sorted_rule_names(rule_names: list[Any]) -> list[str]:
    return sorted((str(rule).strip() for rule in rule_names if str(rule).strip()), key=normalize_sort_text)


@dataclass
class TextStyle:
    font: str = "F1"
    size: float = 8.0
    leading: float = 10.0


@dataclass
class Page:
    number: int
    header: str
    show_default_header: bool = True
    commands: list[str] = field(default_factory=list)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        style: TextStyle = TextStyle(),
        rgb: tuple[float, float, float] | None = None,
    ) -> None:
        if rgb is None:
            self.commands.append(f"BT /{style.font} {style.size:.2f} Tf {x:.2f} {y:.2f} Td ({pdf_text(value)}) Tj ET")
            return
        red, green, blue = rgb
        self.commands.append(
            f"BT {red:.3f} {green:.3f} {blue:.3f} rg /{style.font} {style.size:.2f} Tf {x:.2f} {y:.2f} Td ({pdf_text(value)}) Tj ET 0 g"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5, gray: float = 0.0) -> None:
        self.commands.append(f"{gray:.2f} G {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S 0 G")

    def rect(self, x: float, y: float, width: float, height: float, stroke_width: float = 0.5, gray: float = 0.0) -> None:
        self.commands.append(f"{gray:.2f} G {stroke_width:.2f} w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S 0 G")

    def fill_rect(self, x: float, y: float, width: float, height: float, gray: float = 0.92) -> None:
        self.commands.append(f"{gray:.2f} g {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g")

    def fill_rect_rgb(self, x: float, y: float, width: float, height: float, rgb: tuple[float, float, float]) -> None:
        red, green, blue = rgb
        self.commands.append(f"{red:.3f} {green:.3f} {blue:.3f} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g")

    def render(self) -> str:
        commands: list[str] = []
        if self.show_default_header:
            commands.extend(
                [
                    f"BT /F2 9.00 Tf {MARGIN_X:.2f} {HEADER_Y:.2f} Td ({pdf_text(self.header)}) Tj ET",
                    f"0.50 w {MARGIN_X:.2f} {HEADER_Y - 7:.2f} m {PAGE_WIDTH - MARGIN_X:.2f} {HEADER_Y - 7:.2f} l S",
                ]
            )
        commands.extend(
            [
                *self.commands,
                f"BT /F1 8.00 Tf {PAGE_WIDTH / 2 - 5:.2f} {FOOTER_Y:.2f} Td ({self.number}) Tj ET",
            ]
        )
        return "\n".join(commands)


class PdfBuilder:
    def __init__(self, header: str) -> None:
        self.header = header
        self.pages: list[Page] = []
        self.current = self.new_page()

    def new_page(self) -> Page:
        page = Page(number=len(self.pages) + 1, header=self.header)
        self.pages.append(page)
        self.current = page
        return page

    def write_pdf(self, output_path: Path) -> None:
        objects: list[bytes] = []

        def add_object(body: str) -> int:
            objects.append(body.encode("cp1252"))
            return len(objects)

        catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
        pages_id = add_object("PAGES_PLACEHOLDER")
        font_regular_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        page_ids: list[int] = []

        for page in self.pages:
            content = page.render().encode("cp1252", errors="replace")
            stream_id = add_object(f"<< /Length {len(content)} >>\nstream\n{content.decode('cp1252')}\nendstream")
            page_id = add_object(
                "<< /Type /Page "
                f"/Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
                f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
                f"/Contents {stream_id} 0 R >>"
            )
            page_ids.append(page_id)

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("cp1252")

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode("latin-1"))
            output.extend(body)
            output.extend(b"\nendobj\n")

        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
        output.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode("latin-1")
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output)
        logger.info("Wrote PDF file to %s", output_path)


class Layout:
    def __init__(self, pdf: PdfBuilder) -> None:
        self.pdf = pdf
        self.page = pdf.current
        self.y = PAGE_HEIGHT - MARGIN_TOP - 18

    def ensure(self, height: float) -> None:
        if self.y - height < MARGIN_BOTTOM:
            self.page = self.pdf.new_page()
            self.y = PAGE_HEIGHT - MARGIN_TOP - 18

    def heading(self, value: str, gap_before: float = 8.0) -> None:
        self.ensure(gap_before + 16)
        self.y -= gap_before
        self.page.text(MARGIN_X, self.y, value.upper(), TextStyle("F2", 10, 12))
        self.y -= 4
        self.page.line(MARGIN_X, self.y, PAGE_WIDTH - MARGIN_X, self.y, 0.4)
        self.y -= 12

    def paragraph(self, value: str, font_size: float = 8.2, line_gap: float = 2.0) -> None:
        style = TextStyle("F1", font_size, font_size + line_gap)
        for line in wrap_text(value, PAGE_WIDTH - 2 * MARGIN_X, font_size):
            self.ensure(style.leading)
            if line:
                self.page.text(MARGIN_X, self.y, line, style)
            self.y -= style.leading

    def columns(self, blocks: list[tuple[str, str]], heading: str) -> None:
        self.heading(heading)
        col_gap = 18.0
        col_width = (PAGE_WIDTH - 2 * MARGIN_X - col_gap) / 2
        x_values = [MARGIN_X, MARGIN_X + col_width + col_gap]
        y_values = [self.y, self.y]
        col = 0
        styles = {"title": TextStyle("F2", 7.7, 9), "body": TextStyle("F1", 7.4, 8.7)}

        for title, body in blocks:
            lines = [(title, styles["title"])] + [(line, styles["body"]) for line in wrap_text(body, col_width, 7.4)]
            block_height = sum(style.leading for _, style in lines) + 3
            if y_values[col] - block_height < MARGIN_BOTTOM:
                col = 1 if col == 0 else 0
                if y_values[col] - block_height < MARGIN_BOTTOM:
                    self.page = self.pdf.new_page()
                    y_values = [PAGE_HEIGHT - MARGIN_TOP - 18, PAGE_HEIGHT - MARGIN_TOP - 18]
                    col = 0

            for line, style in lines:
                self.page.text(x_values[col], y_values[col], line, style)
                y_values[col] -= style.leading
            y_values[col] -= 3

        self.y = min(y_values)


def format_header(data: dict[str, Any]) -> str:
    system_code = repair_text(data.get("systemCode") or data.get("systemName") or "ARMY")
    army_name = repair_text(data.get("armyName") or "Unknown Army").upper()
    version = repair_text(data.get("version") or "")
    return f"{system_code} - {army_name} V{version}".strip()


def get_translation_dictionary(language: str = "fr") -> Any:
    normalized_language = language.lower()
    if normalized_language not in _TRANSLATION_CACHE:
        _TRANSLATION_CACHE[normalized_language] = load_translation_dictionary(
            COMMON_RULES_DICTIONARY_PATH, normalized_language
        )
    return _TRANSLATION_CACHE[normalized_language]


def resolve_section_item_description(item: dict[str, Any], data: dict[str, Any], *, is_spell: bool = False) -> str:
    direct_description = repair_text(item.get("description") or "")
    keywords = [str(keyword).strip() for keyword in item.get("keywords", []) if str(keyword).strip()]
    if not keywords:
        return direct_description

    translations = get_translation_dictionary("fr")
    dictionary = translations.spells if is_spell else translations.rules
    system_code = str(data.get("systemCode", ""))
    resolved_parts: list[str] = []

    for keyword in keywords:
        translation = dictionary.get(keyword)
        if not translation:
            continue
        description = pick_translation_description(translation.descriptions, system_code)
        if description:
            resolved_parts.append(strip_translation_markup(description))

    if resolved_parts:
        return " ".join(part for part in resolved_parts if part).strip()

    return direct_description


def weapon_summary(weapons: list[dict[str, Any]]) -> str:
    def inline_ap(value: Any) -> str:
        text = str(value or "").strip()
        if not text or text == "-":
            return ""
        return f"{LABELS['ap']}({text})"

    return "; ".join(
        f"{weapon.get('name', '')} ({', '.join(part for part in [weapon.get('range'), weapon.get('attacks'), inline_ap(weapon.get('ap')), weapon.get('special')] if part and part != '-')})"
        for weapon in weapons
    )


def draw_summary_page(layout: Layout, data: dict[str, Any]) -> None:
    layout.page = layout.pdf.new_page()
    layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
    layout.heading(LABELS["army_list_summary"], gap_before=0)

    headers = [LABELS["name_size"], "Qua", LABELS["def"], "Equipment", LABELS["special_rules_table"], "Coût"]
    table_width = PAGE_WIDTH - 2 * MARGIN_X
    widths = [108, 25, 25, 145, 164, table_width - 108 - 25 - 25 - 145 - 164]
    padding_x = 3.0
    padding_top = 4.0
    padding_bottom = 3.0
    line_height = 7.2
    header_style = TextStyle("F2", 6.5, line_height)
    body_style = TextStyle("F1", 6.5, line_height)
    section_fill = get_section_fill(data)
    unit_type_index = {unit_type: index for index, unit_type in enumerate(UNIT_TYPE_ORDER)}
    units = list(data.get("units", []))
    current_group_label = ""

    def summary_group_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        original_index, unit = item
        unit_type = str(unit.get("unitType") or "").strip()
        if unit_type in unit_type_index:
            return (0, unit_type_index[unit_type] * 1000 + original_index)
        return (1, original_index)

    def group_label_for_unit(unit: dict[str, Any]) -> str:
        unit_type = str(unit.get("unitType") or "").strip()
        if unit_type in unit_type_index:
            return unit_type
        return UNTYPED_UNIT_GROUP_LABEL

    def draw_group_header(label: str) -> None:
        nonlocal current_group_label
        header_height = 18.0
        if layout.y - header_height < MARGIN_BOTTOM:
            layout.page = layout.pdf.new_page()
            layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
        layout.y = draw_unit_type_header(layout.page, label, layout.y, PAGE_WIDTH - 2 * MARGIN_X, section_fill)
        layout.y += 4.0
        current_group_label = label

    def draw_table_row(values: list[str], style: TextStyle) -> None:
        cell_wrap_margin = 10.0
        wrapped_cells = [
            wrap_text(value, width - padding_x * 2 - cell_wrap_margin, style.size) for value, width in zip(values, widths)
        ]
        row_lines = max(len(lines) for lines in wrapped_cells)
        row_height = row_lines * style.leading + padding_top + padding_bottom

        if layout.y - row_height < MARGIN_BOTTOM:
            layout.page = layout.pdf.new_page()
            layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
            if current_group_label:
                layout.y = draw_unit_type_header(
                    layout.page, current_group_label, layout.y, PAGE_WIDTH - 2 * MARGIN_X, section_fill
                )
            if values != headers:
                draw_table_row(headers, header_style)

        row_top = layout.y
        cell_x = MARGIN_X
        for cell_lines, width in zip(wrapped_cells, widths):
            layout.page.rect(cell_x, row_top - row_height, width, row_height, stroke_width=0.2, gray=0.72)
            text_y = row_top - padding_top - style.size
            for line in cell_lines:
                layout.page.text(cell_x + padding_x, text_y, line, style)
                text_y -= style.leading
            cell_x += width

        layout.y -= row_height

    last_group_label = ""

    iterable_units = units if is_print_friendly(data) else [unit for _, unit in sorted(enumerate(units), key=summary_group_key)]

    if is_print_friendly(data):
        draw_table_row(headers, header_style)

    for unit in iterable_units:
        group_label = group_label_for_unit(unit)
        if not is_print_friendly(data) and group_label != last_group_label:
            draw_group_header(group_label)
            draw_table_row(headers, header_style)
            last_group_label = group_label

        equipment = weapon_summary(unit.get("weapons", []))
        rules = ", ".join(sorted_rule_names(unit.get("specialRules", [])))
        name = f"{unit.get('name')} [{unit.get('size')}]"
        draw_table_row([
            name,
            str(unit.get("quality", "")),
            str(unit.get("defense", "")),
            equipment,
            rules,
            f"{unit.get('cost')}pts",
        ], body_style)


def draw_rule_pages(layout: Layout, data: dict[str, Any]) -> None:
    layout.page = layout.pdf.new_page()
    layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
    column_count = 3
    col_gap = 12.0
    col_width = (PAGE_WIDTH - 2 * MARGIN_X - col_gap * (column_count - 1)) / column_count
    x_values = [MARGIN_X + index * (col_width + col_gap) for index in range(column_count)]
    y_values = [layout.y for _ in range(column_count)]
    heading_style = TextStyle("F2", 8.2, 9.4)
    title_style = TextStyle("F2", 7.1, 8.1)
    body_style = TextStyle("F1", 6.8, 7.7)
    section_fill = get_section_fill(data)
    spells = list(data.get("armySpells", []))

    def build_item_block(item: dict[str, Any], width: float, *, is_spell: bool = False) -> list[tuple[str, TextStyle]]:
        title = f"{item.get('name')} ({item.get('cost')}):" if "cost" in item else f"{item.get('name')}:"
        lines = [(title, title_style)]
        body_lines = wrap_text(resolve_section_item_description(item, data, is_spell=is_spell), width, body_style.size)
        lines.extend((line, body_style) for line in body_lines)
        return lines

    def block_height(lines: list[tuple[str, TextStyle]], extra_gap: float = 3.0) -> float:
        return sum(style.leading for _, style in lines) + extra_gap

    def draw_lines_in_column(col: int, lines: list[tuple[str, TextStyle]], extra_gap: float = 3.0) -> None:
        for line, style in lines:
            layout.page.text(x_values[col], y_values[col], line, style)
            y_values[col] -= style.leading
        y_values[col] -= extra_gap

    def draw_section_in_column(col: int, heading: str, items: list[dict[str, Any]], *, show_heading: bool = True) -> None:
        if not items:
            return
        if show_heading:
            draw_lines_in_column(col, [(heading.upper(), heading_style)], extra_gap=2.0)
        for item in items:
            draw_lines_in_column(col, build_item_block(item, col_width))

    def ensure_top_section_fit(columns: list[list[tuple[str, list[dict[str, Any]], bool]]]) -> None:
        nonlocal y_values
        estimated_heights: list[float] = []
        for column_sections in columns:
            total = 0.0
            for heading, items, show_heading in column_sections:
                if not items:
                    continue
                if show_heading:
                    total += block_height([(heading.upper(), heading_style)], extra_gap=2.0)
                for item in items:
                    total += block_height(build_item_block(item, col_width))
            estimated_heights.append(total)
        if estimated_heights and layout.y - max(estimated_heights) < MARGIN_BOTTOM:
            layout.page = layout.pdf.new_page()
            layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
            y_values[:] = [layout.y for _ in range(column_count)]

    def rule_sort_key(item: dict[str, Any]) -> str:
        return normalize_sort_text(item.get("name", ""))

    army_wide_rules = sorted(list(data.get("armyWideSpecialRule", [])), key=rule_sort_key)
    special_rules = sorted(list(data.get("specialRules", [])), key=rule_sort_key)
    aura_rules = sorted(list(data.get("auraSpecialRules", [])), key=rule_sort_key)

    army_wide_height = block_height([(LABELS["army_wide_special_rule"].upper(), heading_style)], extra_gap=2.0) if army_wide_rules else 0.0
    army_wide_height += sum(block_height(build_item_block(item, col_width)) for item in army_wide_rules)
    special_rule_heights = [block_height(build_item_block(item, col_width)) for item in special_rules]
    total_special_height = sum(special_rule_heights)

    split_index = len(special_rules)
    best_delta = float("inf")
    running_height = 0.0
    for index in range(len(special_rules) + 1):
        left_height = army_wide_height
        if index > 0:
            left_height += block_height([(LABELS["special_rules"].upper(), heading_style)], extra_gap=2.0) + running_height
        center_height = 0.0
        if index < len(special_rules):
            center_height = block_height([(LABELS["special_rules"].upper(), heading_style)], extra_gap=2.0) + (total_special_height - running_height)
        delta = abs(left_height - center_height)
        if delta <= best_delta:
            best_delta = delta
            split_index = index
        if index < len(special_rule_heights):
            running_height += special_rule_heights[index]

    left_column_sections = [
        (LABELS["army_wide_special_rule"], army_wide_rules, True),
        (LABELS["special_rules"], special_rules[:split_index], True),
    ]
    center_column_sections = [
        (LABELS["special_rules"], special_rules[split_index:], split_index == 0),
    ]
    right_column_sections = [
        (LABELS["aura_special_rules"], aura_rules, True),
    ]

    ensure_top_section_fit([left_column_sections, center_column_sections, right_column_sections])
    draw_section_in_column(0, LABELS["army_wide_special_rule"], army_wide_rules)
    draw_section_in_column(0, LABELS["special_rules"], special_rules[:split_index])
    draw_section_in_column(1, LABELS["special_rules"], special_rules[split_index:], show_heading=split_index == 0)
    draw_section_in_column(2, LABELS["aura_special_rules"], aura_rules)

    layout.y = min(y_values) - 2.0

    if not spells:
        return

    spells_header_height = 18.0
    if layout.y - spells_header_height < MARGIN_BOTTOM:
        layout.page = layout.pdf.new_page()
        layout.y = PAGE_HEIGHT - MARGIN_TOP - 18

    layout.y = draw_unit_type_header(layout.page, LABELS["army_spells"], layout.y, PAGE_WIDTH - 2 * MARGIN_X, section_fill)
    layout.y -= 6.0

    spell_column_count = 3
    spell_col_gap = 12.0
    spell_col_width = (PAGE_WIDTH - 2 * MARGIN_X - spell_col_gap * (spell_column_count - 1)) / spell_column_count
    spell_x_values = [MARGIN_X + index * (spell_col_width + spell_col_gap) for index in range(spell_column_count)]
    spell_y_values = [layout.y for _ in range(spell_column_count)]
    spell_col = 0

    for spell in spells:
        lines = build_item_block(spell, spell_col_width, is_spell=True)
        height = block_height(lines)
        if spell_y_values[spell_col] - height < MARGIN_BOTTOM:
            spell_col = 1 if spell_col < spell_column_count - 1 else 0
            if spell_y_values[spell_col] - height < MARGIN_BOTTOM:
                layout.page = layout.pdf.new_page()
                layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
                layout.y = draw_unit_type_header(
                    layout.page, LABELS["army_spells"], layout.y, PAGE_WIDTH - 2 * MARGIN_X, section_fill
                )
                layout.y -= 6.0
                spell_y_values = [layout.y for _ in range(spell_column_count)]
                spell_col = 0

        for line, style in lines:
            layout.page.text(spell_x_values[spell_col], spell_y_values[spell_col], line, style)
            spell_y_values[spell_col] -= style.leading
        spell_y_values[spell_col] -= 3.0
        spell_col = (spell_col + 1) % spell_column_count

    layout.y = min(spell_y_values)


def upgrade_line(option: dict[str, Any]) -> str:
    details = str(option.get("details") or "")
    suffix = f" ({details})" if details and not details.startswith("(") else f" {details}" if details else ""
    cost = f" {option.get('cost')}" if option.get("cost") else ""
    return f"{option.get('name', '')}{suffix}{cost}".strip()


def format_pts_cost(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    match = re.fullmatch(r"([+-]?\d+)\s*pts?", text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)} pts"

    if re.fullmatch(r"[+-]?\d+", text):
        return f"{text} pts"

    return text


def upgrade_group_label(value: str) -> str:
    if value == "Upgrade SPE":
        return LABELS["upgrade_spe"]

    normalized = " ".join(value.split())
    lower = normalized.lower()
    if lower == "upgrade all models with one":
        return "Améliore toutes les figurines avec une option:"
    if lower == "upgrade one model with one":
        return "Améliore une figurine avec une option:"
    exact_labels = {
        "upgrade all models with any": "Améliore toutes les figurines avec une option:",
        "upgrade with any": "Améliore avec une option:",
        "upgrade with one": "Améliore avec une option:",
        "upgrade up to three models with one": "Améliore jusqu'à trois figurines avec:",
        "upgrade one model with": "Améliore une figurine avec:",
        "upgrade all models with": "Améliore toutes les figurines avec:",
        "upgrade all model with": "Améliore toutes les figurines avec:",
        "upgrade with": "Améliore avec:",
    }
    if lower in exact_labels:
        return exact_labels[lower]

    def translate_replace_targets(targets: str) -> str:
        return targets.replace(" and ", " et ")

    if lower.startswith("replace all "):
        return f"Remplace les {translate_replace_targets(normalized[len('Replace all '):])}"

    if lower.startswith("replace any "):
        return f"Remplace {translate_replace_targets(normalized[len('Replace any '):])}"

    if lower.startswith("replace "):
        return f"Remplace {translate_replace_targets(normalized[len('Replace '):])}"

    return value


def split_upgrade_spe_option(option: dict[str, Any]) -> tuple[str, str]:
    name = str(option.get("name", "")).strip()
    details = str(option.get("details", "")).strip()
    if details:
        return name, details

    known_suffixes = [
        "Furious Aura",
        "Bestial Boost Aura",
        "Melee Evasion Aura",
        "Piercing Assault Aura",
        "Precision Shooter Aura",
        "Unpredictable Fighter",
        "Fast",
        "Strider",
        "Scout",
        "Resistance",
    ]

    if "," in name:
        first_part, rest = name.split(",", 1)
        for suffix in known_suffixes:
            marker = f" {suffix}"
            if first_part.endswith(marker):
                return first_part[: -len(marker)].strip(), f"{suffix}, {rest.strip()}"

    for suffix in known_suffixes:
        marker = f" {suffix}"
        if name.endswith(marker):
            return name[: -len(marker)].strip(), suffix

    return name, ""


def unit_block_lines(unit: dict[str, Any], max_width: float) -> list[tuple[str, TextStyle]]:
    lines: list[tuple[str, TextStyle]] = []
    lines.append((f"{unit.get('name')} [{unit.get('size')}] - {unit.get('cost')}pts", TextStyle("F2", 8.4, 9.8)))

    stats = f"Quality {unit.get('quality')} Defense {unit.get('defense')}"
    if unit.get("tough"):
        stats += f" {LABELS['tough']} {unit.get('tough')}"
    lines.append((stats, TextStyle("F2", 7.4, 8.5)))
    lines.extend(
        (line, TextStyle("F1", 7.2, 8.3))
        for line in wrap_text(", ".join(sorted_rule_names(unit.get("specialRules", []))), max_width, 7.2)
    )
    lines.append((f"Weapon RNG {LABELS['atk']} {LABELS['ap']} SPE", TextStyle("F2", 7.0, 8.2)))

    for weapon in unit.get("weapons", []):
        weapon_line = f"{weapon.get('name')} {weapon.get('range')} {weapon.get('attacks')} {weapon.get('ap')} {weapon.get('special')}"
        lines.extend((line, TextStyle("F1", 7.0, 8.1)) for line in wrap_text(weapon_line, max_width, 7.0))

    for group in unit.get("upgrades", []):
        lines.append((upgrade_group_label(str(group.get("type", ""))), TextStyle("F2", 7.0, 8.2)))
        for option in group.get("options", []):
            lines.extend((line, TextStyle("F1", 6.8, 7.8)) for line in wrap_text(upgrade_line(option), max_width - 8, 6.8))

    return lines


def unit_card_layout(unit: dict[str, Any], width: float) -> list[dict[str, Any]]:
    inner_width = width - 14.0
    weapon_widths = {
        "name": inner_width * 0.42,
        "range": 26.0,
        "attacks": 24.0,
        "ap": 18.0,
    }
    weapon_widths["special"] = inner_width - sum(weapon_widths.values())

    layout: list[dict[str, Any]] = [
        {"kind": "header", "height": 14.0},
        {"kind": "stats", "height": 10.0},
    ]

    rules = ", ".join(sorted_rule_names(unit.get("specialRules", [])))
    rule_lines = wrap_text(rules, inner_width, 6.7) if rules else []
    if rule_lines:
        layout.append({"kind": "rules", "lines": rule_lines, "height": len(rule_lines) * 7.4 + 3})

    weapons = []
    for weapon in unit.get("weapons", []):
        name_lines = wrap_text(str(weapon.get("name", "")), weapon_widths["name"] - 3, 6.4)
        special_lines = wrap_text(str(weapon.get("special", "")), weapon_widths["special"] - 3, 6.4)
        row_lines = max(len(name_lines), len(special_lines), 1)
        weapons.append(
            {
                "weapon": weapon,
                "name_lines": name_lines,
                "special_lines": special_lines,
                "height": row_lines * 7.0 + 2,
            }
        )
    if weapons:
        layout.append({"kind": "weapon_header", "height": 9.0, "widths": weapon_widths})
        for weapon_layout in weapons:
            weapon_layout["kind"] = "weapon"
            weapon_layout["widths"] = weapon_widths
            layout.append(weapon_layout)

    spe_name_width = inner_width * 0.44
    spe_details_width = inner_width - spe_name_width - 6.0
    upgrade_cost_width = 40.0
    upgrade_text_width = inner_width - 10.0 - upgrade_cost_width

    for group in unit.get("upgrades", []):
        group_type = str(group.get("type", ""))
        layout.append(
            {
                "kind": "upgrade_spe_heading" if group_type == "Upgrade SPE" else "upgrade_heading",
                "text": upgrade_group_label(group_type),
                "name_width": spe_name_width,
                "height": 8.3,
            }
        )
        for option in group.get("options", []):
            if group_type == "Upgrade SPE":
                name, details = split_upgrade_spe_option(option)
                name_lines = wrap_text(name, spe_name_width, 6.2)
                details_lines = wrap_text(details, spe_details_width, 6.2)
                layout.append(
                    {
                        "kind": "upgrade_spe_option",
                        "name_lines": name_lines,
                        "details_lines": details_lines,
                        "name_width": spe_name_width,
                        "details_width": spe_details_width,
                        "height": max(len(name_lines), len(details_lines), 1) * 6.9 + 1.5,
                    }
                )
                continue
            name = str(option.get("name", "")).strip()
            details = str(option.get("details", "")).strip()
            name_lines = wrap_text(name, upgrade_text_width, 6.35) or [""]
            details_lines = wrap_text(details, upgrade_text_width, 5.75) if details else []
            layout.append(
                {
                    "kind": "upgrade_option",
                    "name_lines": name_lines,
                    "details_lines": details_lines,
                    "cost": format_pts_cost(option.get("cost")),
                    "cost_width": upgrade_cost_width,
                    "height": len(name_lines) * 6.9 + len(details_lines) * 6.3 + 2.2,
                }
            )

    return layout


def unit_card_height(unit: dict[str, Any], width: float) -> float:
    return sum(item["height"] for item in unit_card_layout(unit, width)) + 14.0


def draw_unit_card(page: Page, unit: dict[str, Any], x: float, y: float, width: float) -> float:
    layout = unit_card_layout(unit, width)
    height = sum(item["height"] for item in layout) + 14.0
    top = y
    bottom = top - height
    inner_x = x + 7.0
    inner_width = width - 14.0
    cursor = top - 6.0

    page.rect(x, bottom, width, height, stroke_width=0.45, gray=0.35)
    page.fill_rect(x, top - 16.0, width, 16.0, gray=0.90)
    page.line(x, top - 16.0, x + width, top - 16.0, width=0.35, gray=0.55)

    for item in layout:
        kind = item["kind"]

        if kind == "header":
            unique_prefix = "* " if unit.get("uniqueHero") else ""
            title = f"{unique_prefix}{unit.get('name')} [{unit.get('size')}]"
            cost = format_pts_cost(unit.get("cost"))
            page.text(inner_x, cursor - 6.2, title, TextStyle("F2", 7.9, 9.0))
            page.text(x + width - text_width(cost, 7.4) - 7.0, cursor - 6.2, cost, TextStyle("F2", 7.4, 9.0))
            cursor -= item["height"]
            continue

        if kind == "stats":
            stats = f"Qualité {unit.get('quality')}   Défense {unit.get('defense')}"
            if unit.get("tough"):
                stats += f"   {LABELS['tough']} {unit.get('tough')}"
            page.text(inner_x, cursor - 5.0, stats, TextStyle("F2", 6.8, 8.0))
            page.line(inner_x, cursor - 9.0, inner_x + inner_width, cursor - 9.0, width=0.25, gray=0.75)
            cursor -= item["height"]
            continue

        if kind == "rules":
            for line in item["lines"]:
                page.text(inner_x, cursor - 5.0, line, TextStyle("F1", 6.7, 7.4))
                cursor -= 7.4
            cursor -= 3.0
            continue

        if kind == "weapon_header":
            widths = item["widths"]
            page.fill_rect(inner_x, cursor - 8.0, inner_width, 8.4, gray=0.94)
            column_x = inner_x + 2.0
            for label, key in [("Arme", "name"), ("RNG", "range"), (LABELS["atk"], "attacks"), (LABELS["ap"], "ap"), ("SPE", "special")]:
                page.text(column_x, cursor - 5.7, label, TextStyle("F2", 5.8, 6.5))
                column_x += widths[key]
            page.line(inner_x, cursor - 8.0, inner_x + inner_width, cursor - 8.0, width=0.18, gray=0.82)
            cursor -= item["height"]
            continue

        if kind == "weapon":
            weapon = item["weapon"]
            widths = item["widths"]
            row_bottom = cursor - item["height"]
            column_x = inner_x + 2.0
            text_y = cursor - 5.2
            for line in item["name_lines"]:
                page.text(column_x, text_y, line, TextStyle("F1", 6.4, 7.0))
                text_y -= 7.0
            column_x += widths["name"]
            page.text(column_x, cursor - 5.2, str(weapon.get("range", "")), TextStyle("F1", 6.3, 7.0))
            column_x += widths["range"]
            page.text(column_x, cursor - 5.2, str(weapon.get("attacks", "")), TextStyle("F1", 6.3, 7.0))
            column_x += widths["attacks"]
            page.text(column_x, cursor - 5.2, str(weapon.get("ap", "")), TextStyle("F1", 6.3, 7.0))
            column_x += widths["ap"]
            text_y = cursor - 5.2
            for line in item["special_lines"]:
                page.text(column_x, text_y, line, TextStyle("F1", 6.3, 7.0))
                text_y -= 7.0
            page.line(inner_x, row_bottom, inner_x + inner_width, row_bottom, width=0.18, gray=0.86)
            cursor -= item["height"]
            continue

        if kind == "upgrade_heading":
            cursor -= 1.0
            page.fill_rect(inner_x, cursor - 7.0, inner_width, 7.5, gray=0.94)
            page.text(inner_x + 5.0, cursor - 5.0, item["text"], TextStyle("F2", 6.4, 7.3))
            cursor -= item["height"]
            continue

        if kind == "upgrade_spe_heading":
            cursor -= 1.0
            page.fill_rect(inner_x, cursor - 7.0, inner_width, 7.5, gray=0.94)
            page.text(inner_x + 5.0, cursor - 5.0, item["text"], TextStyle("F2", 6.4, 7.3))
            page.text(inner_x + 5.0 + item["name_width"] + 6.0, cursor - 5.0, "SPE", TextStyle("F2", 6.4, 7.3))
            cursor -= item["height"]
            continue

        if kind == "upgrade_option":
            row_top = cursor
            row_bottom = cursor - item["height"] + 0.8
            text_x = inner_x + 5.0
            cost = str(item.get("cost", ""))
            cost_x = inner_x + inner_width - text_width(cost, 5.9) - 3.0 if cost else inner_x + inner_width - 3.0
            text_y = cursor - 4.8

            page.line(inner_x, row_top, inner_x + inner_width, row_top, width=0.16, gray=0.88)

            for line in item["name_lines"]:
                page.text(text_x, text_y, line, TextStyle("F2", 6.1, 6.9))
                text_y -= 6.9

            for line in item["details_lines"]:
                page.text(text_x + 3.0, text_y, line, TextStyle("F1", 5.75, 6.3))
                text_y -= 6.3

            if cost:
                page.text(cost_x, cursor - 4.8, cost, TextStyle("F2", 5.9, 6.9))

            page.line(inner_x, row_bottom, inner_x + inner_width, row_bottom, width=0.16, gray=0.9)
            cursor -= item["height"]
            continue

        if kind == "upgrade_spe_option":
            row_top = cursor
            row_height = item["height"]
            page.line(inner_x, row_top, inner_x + inner_width, row_top, width=0.18, gray=0.86)
            text_y = cursor - 4.8
            for line in item["name_lines"]:
                page.text(inner_x + 5.0, text_y, line, TextStyle("F1", 6.2, 6.9))
                text_y -= 6.9
            text_y = cursor - 4.8
            details_x = inner_x + 5.0 + item["name_width"] + 6.0
            for line in item["details_lines"]:
                page.text(details_x, text_y, line, TextStyle("F1", 6.2, 6.9))
                text_y -= 6.9
            cursor -= row_height
            continue

    return bottom


def draw_unit_type_header(
    page: Page,
    unit_type: str,
    y: float,
    width: float,
    fill_rgb: tuple[float, float, float],
) -> float:
    bar_height = 12.0
    text_color = (1.0, 1.0, 1.0) if color_luminance(fill_rgb) < 0.5 else (0.0, 0.0, 0.0)
    page.fill_rect_rgb(MARGIN_X, y - bar_height, width, bar_height, fill_rgb)
    page.text(MARGIN_X + 8.0, y - 8.4, unit_type, TextStyle("F2", 8.0, 9.0), rgb=text_color)
    return y - bar_height - 4.0


def draw_intro_banner(page: Page, data: dict[str, Any]) -> float:
    fill_rgb = get_section_fill(data)
    text_rgb = (1.0, 1.0, 1.0) if color_luminance(fill_rgb) < 0.5 else (0.0, 0.0, 0.0)
    banner_top = PAGE_HEIGHT - 28.0
    banner_height = 38.0
    title = repair_text(data.get("armyName") or "Unknown Army").upper()
    subtitle_bits = [repair_text(data.get("systemName") or data.get("systemCode") or "")]
    version = repair_text(data.get("version") or "")
    if version:
        subtitle_bits.append(f"v{version}")
    subtitle = " — ".join(bit for bit in subtitle_bits if bit)

    page.show_default_header = False
    page.fill_rect_rgb(MARGIN_X, banner_top - banner_height, PAGE_WIDTH - 2 * MARGIN_X, banner_height, fill_rgb)
    title_x = PAGE_WIDTH / 2 - text_width(title, 15.5) / 2
    subtitle_x = PAGE_WIDTH / 2 - text_width(subtitle, 7.0) / 2
    page.text(title_x, banner_top - 20.0, title, TextStyle("F2", 15.5, 16.0), rgb=text_rgb)
    if subtitle:
        page.text(subtitle_x, banner_top - 32.0, subtitle, TextStyle("F1", 7.0, 8.0), rgb=text_rgb)
    return banner_top - banner_height - 14.0


def draw_units(layout: Layout, data: dict[str, Any]) -> None:
    layout.page = layout.pdf.new_page()
    layout.y = PAGE_HEIGHT - MARGIN_TOP - 18
    col_gap = 18.0
    width = (PAGE_WIDTH - 2 * MARGIN_X - col_gap) / 2
    x_values = [MARGIN_X, MARGIN_X + width + col_gap]
    y_values = [layout.y, layout.y]
    col = 0
    units = list(data.get("units", []))
    unit_type_index = {unit_type: index for index, unit_type in enumerate(UNIT_TYPE_ORDER)}
    section_fill = get_section_fill(data)

    def unit_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        original_index, unit = item
        unit_type = str(unit.get("unitType") or "").strip()
        if unit_type in unit_type_index:
            return (0, unit_type_index[unit_type] * 1000 + original_index)
        return (1, original_index)

    last_group_key: str | None = None

    iterable_units = units if is_print_friendly(data) else [unit for _, unit in sorted(enumerate(units), key=unit_sort_key)]

    for unit in iterable_units:
        unit_type = str(unit.get("unitType") or "").strip()
        group_key = unit_type if unit_type in unit_type_index else "__untyped__"
        group_label = unit_type if unit_type in unit_type_index else UNTYPED_UNIT_GROUP_LABEL

        if not is_print_friendly(data) and group_key != last_group_key:
            header_height = 18.0
            first_card_height = unit_card_height(unit, width) + 8.0
            next_y = min(y_values)
            required_height = header_height + first_card_height
            if next_y - required_height < MARGIN_BOTTOM:
                layout.page = layout.pdf.new_page()
                y_values = [PAGE_HEIGHT - MARGIN_TOP - 18, PAGE_HEIGHT - MARGIN_TOP - 18]
                next_y = y_values[0]
            next_y = draw_unit_type_header(layout.page, group_label, next_y, PAGE_WIDTH - 2 * MARGIN_X, section_fill)
            y_values = [next_y, next_y]
            col = 0
            last_group_key = group_key

        height = unit_card_height(unit, width)

        if y_values[col] - height < MARGIN_BOTTOM:
            col = 1 if col == 0 else 0
            if y_values[col] - height < MARGIN_BOTTOM:
                layout.page = layout.pdf.new_page()
                y_values = [PAGE_HEIGHT - MARGIN_TOP - 18, PAGE_HEIGHT - MARGIN_TOP - 18]
                col = 0

        frame_x = x_values[col]
        y_values[col] = draw_unit_card(layout.page, unit, frame_x, y_values[col], width) - 8
        col = 1 if col == 0 else 0

    layout.y = min(y_values)


def draw_intro_page(layout: Layout, data: dict[str, Any]) -> None:
    top_y = draw_intro_banner(layout.page, data)
    col_gap = 22.0
    col_width = (PAGE_WIDTH - 2 * MARGIN_X - col_gap) / 2
    text_width_safe = col_width - 10.0
    sections = [
        (LABELS["intro"], str(data.get("introduction", "")), MARGIN_X),
        (LABELS["background_story"], str(data.get("backgroundStory", "")), MARGIN_X + col_width + col_gap),
    ]
    heading_style = TextStyle("F2", 10.0, 12.0)
    body_style = TextStyle("F1", 8.0, 9.7)

    for heading, body, x in sections:
        y = top_y
        layout.page.text(x, y, heading.upper(), heading_style)
        y -= 4
        layout.page.line(x, y, x + col_width, y, 0.4)
        y -= 13
        for line in wrap_text(body, text_width_safe, body_style.size):
            if y < MARGIN_BOTTOM:
                break
            if line:
                layout.page.text(x, y, line, body_style)
            y -= body_style.leading

        if x != MARGIN_X:
            continue

        y -= 18
        if y < MARGIN_BOTTOM:
            continue

        layout.page.text(x, y, LABELS["about_opr"], heading_style)
        y -= 4
        layout.page.line(x, y, x + col_width, y, 0.4)
        y -= 13

        for index, paragraph in enumerate(ABOUT_OPR_PARAGRAPHS):
            paragraph_style = TextStyle("F2", 8.0, 9.7) if index == len(ABOUT_OPR_PARAGRAPHS) - 1 else body_style
            for line in wrap_text(paragraph, text_width_safe, paragraph_style.size):
                if y < MARGIN_BOTTOM:
                    break
                if line:
                    layout.page.text(x, y, line, paragraph_style)
                y -= paragraph_style.leading
            y -= 9


def build_pdf(data: dict[str, Any], output_path: Path, *, print_friendly: bool = False) -> None:
    logger.info(
        "Building PDF: output_path=%s army=%s print_friendly=%s",
        output_path,
        data.get("armyName", ""),
        print_friendly,
    )
    data = {**data, "__print_friendly": print_friendly}
    pdf = PdfBuilder(format_header(data))
    layout = Layout(pdf)

    draw_intro_page(layout, data)

    draw_summary_page(layout, data)
    draw_rule_pages(layout, data)
    draw_units(layout, data)

    pdf.write_pdf(output_path)


def default_output_path(json_path: Path) -> Path:
    return json_path.with_suffix(".pdf")


def resolve_cli_paths(input_path: Path, output_path: Path | None) -> tuple[Path, Path]:
    if output_path is not None:
        return input_path, output_path

    if input_path.suffix.lower() != ".pdf":
        return input_path, default_output_path(input_path)

    candidates = [
        input_path.with_suffix(".json"),
        Path("ArmyForgeFR/src/data/generated") / input_path.with_suffix(".json").name,
    ]
    json_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    return json_path, input_path


def main() -> None:
    cli_logger = setup_script_logging("generate_army_pdf")
    parser = argparse.ArgumentParser(description="Generate an OPR-style army PDF from an extracted JSON file.")
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the army JSON file, or a PDF output path with a matching JSON file.",
    )
    parser.add_argument("-o", "--output", type=Path, help="Path to write the generated PDF.")
    parser.add_argument(
        "--print-friendly",
        action="store_true",
        help="Generate a print-friendly PDF without faction colors or unit-type group separators.",
    )
    args = parser.parse_args()
    cli_logger.info(
        "Starting single PDF generation: input=%s output=%s print_friendly=%s",
        args.input,
        args.output,
        args.print_friendly,
    )

    try:
        json_path, output_path = resolve_cli_paths(args.input, args.output)
        if not json_path.exists():
            cli_logger.error("JSON input not found: %s", json_path)
            raise SystemExit(f"JSON input not found: {json_path}")

        data = json.loads(json_path.read_text(encoding="utf-8"))
        build_pdf(data, output_path, print_friendly=args.print_friendly)
        cli_logger.info("Single PDF generation completed successfully. Log file: %s", LOG_FILE_PATH)
    except Exception:
        cli_logger.exception("Single PDF generation failed for input=%s", args.input)
        raise


if __name__ == "__main__":
    main()
