from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_army_pdf import DEFAULT_DICTIONARY_SOURCE
from extract_army_web import extract_from_url
from generate_army_pdf import build_pdf


def read_url_list(list_path: Path) -> list[str]:
    urls: list[str] = []
    for raw_line in list_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build JSON and PDF army book files from a list of Army Forge army-info URLs."
    )
    parser.add_argument(
        "list_path",
        nargs="?",
        type=Path,
        default=Path("army-book-urls.txt"),
        help="Path to a newline-separated list of Army Forge army-info URLs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated"),
        help="Directory where JSON and PDF outputs should be written.",
    )
    parser.add_argument(
        "--language",
        default="fr",
        help="Target translation language. Use 'en' to keep extracted text as-is.",
    )
    parser.add_argument(
        "--dictionary",
        default=DEFAULT_DICTIONARY_SOURCE,
        help="Path or URL to the common rules dictionary file.",
    )
    parser.add_argument(
        "--print-friendly",
        action="store_true",
        help="Generate print-friendly PDFs without faction colors or unit-type group separators.",
    )
    args = parser.parse_args()

    urls = read_url_list(args.list_path)
    if not urls:
        raise SystemExit(f"No URLs found in list: {args.list_path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for url in urls:
        data, basename = extract_from_url(
            url,
            language=args.language,
            dictionary_path=args.dictionary,
        )
        json_path = args.output_dir / f"{basename}.json"
        pdf_path = args.output_dir / f"{basename}.pdf"

        json_path.write_text(f"{json.dumps(data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
        build_pdf(data, pdf_path, print_friendly=args.print_friendly)
        print(f"Generated {json_path.as_posix()} and {pdf_path.as_posix()}")


if __name__ == "__main__":
    main()
