from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_army_pdf import build_pdf
from extract_army_web import make_output_basename


def iter_json_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.glob("*.json") if path.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate army PDF files for every JSON file in a directory."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        default=Path("ArmyForgeFR/src/data/generated"),
        help="Directory containing army JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where PDFs should be written. Defaults to the input directory.",
    )
    parser.add_argument(
        "--print-friendly",
        action="store_true",
        help="Generate print-friendly PDFs without faction colors or unit-type group separators.",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir}")
    if not input_dir.is_dir():
        raise SystemExit(f"Input path is not a directory: {input_dir}")

    json_files = iter_json_files(input_dir)
    if not json_files:
        raise SystemExit(f"No JSON files found in directory: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for json_path in json_files:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        basename = make_output_basename(data)
        pdf_path = output_dir / f"{basename}.pdf"
        build_pdf(data, pdf_path, print_friendly=args.print_friendly)
        print(f"Generated {pdf_path.as_posix()} from {json_path.as_posix()}")


if __name__ == "__main__":
    main()
