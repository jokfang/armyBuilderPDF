from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_army_pdf import build_pdf
from extract_army_web import make_output_basename
from logging_utils import LOG_FILE_PATH, setup_script_logging


def iter_json_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.glob("*.json") if path.is_file())


def main() -> None:
    logger = setup_script_logging("generate_army_pdfs_from_dir")
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
    logger.info(
        "Starting directory PDF generation: input_dir=%s output_dir=%s print_friendly=%s",
        args.input_dir,
        args.output_dir,
        args.print_friendly,
    )

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    if not input_dir.exists():
        logger.error("Input directory not found: %s", input_dir)
        raise SystemExit(f"Input directory not found: {input_dir}")
    if not input_dir.is_dir():
        logger.error("Input path is not a directory: %s", input_dir)
        raise SystemExit(f"Input path is not a directory: {input_dir}")

    json_files = iter_json_files(input_dir)
    if not json_files:
        logger.error("No JSON files found in directory: %s", input_dir)
        raise SystemExit(f"No JSON files found in directory: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Found %d JSON file(s) in %s", len(json_files), input_dir)
    failures: list[tuple[Path, str]] = []

    for json_path in json_files:
        try:
            logger.info("Generating PDF from JSON: %s", json_path)
            data = json.loads(json_path.read_text(encoding="utf-8"))
            basename = make_output_basename(data)
            pdf_path = output_dir / f"{basename}.pdf"
            build_pdf(data, pdf_path, print_friendly=args.print_friendly)
            logger.info("Generated PDF: %s", pdf_path)
            print(f"Generated {pdf_path.as_posix()} from {json_path.as_posix()}")
        except Exception as error:
            failure_message = f"{type(error).__name__}: {error}"
            failures.append((json_path, failure_message))
            logger.exception("Failed to generate PDF from JSON: %s", json_path)
            print(f"Failed {json_path.as_posix()}: {failure_message}")

    if failures:
        logger.error("Directory PDF generation completed with %d failure(s). Log file: %s", len(failures), LOG_FILE_PATH)
        raise SystemExit(1)

    logger.info("Directory PDF generation completed successfully. Log file: %s", LOG_FILE_PATH)


if __name__ == "__main__":
    main()
