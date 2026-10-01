from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_URL_LIST = Path("army-book-urls.txt")
DEFAULT_OUTPUT_DIR = Path("generated/original")

GAME_SYSTEM_IDS = {
    "grimdark-future": 2,
    "grimdark-future-firefight": 3,
    "age-of-fantasy": 4,
    "age-of-fantasy-skirmish": 5,
    "age-of-fantasy-regiments": 6,
}


def read_url_list(path: Path) -> list[str]:
    """Read non-empty, non-comment lines while removing duplicate URLs."""
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        url = raw_line.strip()
        if not url or url.startswith("#") or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def parse_army_info_url(url: str) -> tuple[str, str, int, bool]:
    parsed = urllib.parse.urlparse(url)
    segments = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    try:
        army_info_index = segments.index("army-info")
        game_system_slug = segments[army_info_index + 1]
        book_uid = segments[army_info_index + 2]
    except (ValueError, IndexError) as error:
        raise ValueError(f"URL Army Forge invalide : {url}") from error

    try:
        game_system_id = GAME_SYSTEM_IDS[game_system_slug]
    except KeyError as error:
        raise ValueError(f"Système de jeu non pris en charge : {game_system_slug}") from error

    is_beta = "army-forge-beta" in parsed.netloc.lower()
    return game_system_slug, book_uid, game_system_id, is_beta


def build_api_url(url: str) -> str:
    _, book_uid, game_system_id, is_beta = parse_army_info_url(url)
    host = "army-forge-beta.onepagerules.com" if is_beta else "army-forge.onepagerules.com"
    quoted_uid = urllib.parse.quote(book_uid, safe="")
    return (
        f"https://{host}/api/army-books/{quoted_uid}"
        f"?gameSystem={game_system_id}&simpleMode=false"
    )


def fetch_original_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    api_url = build_api_url(url)
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"La réponse de l'API n'est pas un objet JSON : {api_url}")
    return data


def fetch_with_retries(
    url: str,
    *,
    timeout: float,
    retries: int,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    for attempt in range(retries + 1):
        try:
            return fetch_original_json(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries:
                raise
            time.sleep(retry_delay * (2**attempt))
    raise AssertionError("unreachable")


def slugify(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def make_output_name(source_url: str, data: dict[str, Any]) -> str:
    system_slug, book_uid, _, _ = parse_army_info_url(source_url)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(source_url).query)
    army_name = data.get("name") or data.get("armyName") or query.get("armyName", [book_uid])[0]
    version = data.get("versionString") or data.get("version")

    parts = [slugify(system_slug), slugify(army_name)]
    if version:
        parts.append(slugify(version))
    if not parts[1]:
        parts[1] = slugify(book_uid) or "army-book"
    return "-".join(part for part in parts if part) + ".json"


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Télécharge les réponses JSON originales et complètes d'Army Forge "
            "pour toutes les URLs d'un fichier."
        )
    )
    parser.add_argument(
        "list_path",
        nargs="?",
        type=Path,
        default=DEFAULT_URL_LIST,
        help=f"Liste d'URLs (défaut : {DEFAULT_URL_LIST}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Dossier de sortie (défaut : {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Délai maximal d'une requête en secondes (défaut : 30).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Nombre de nouvelles tentatives après un échec réseau (défaut : 2).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout doit être supérieur à 0.")
    if args.retries < 0:
        raise SystemExit("--retries ne peut pas être négatif.")

    urls = read_url_list(args.list_path)
    if not urls:
        raise SystemExit(f"Aucune URL trouvée dans {args.list_path}.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []

    for index, url in enumerate(urls, start=1):
        try:
            data = fetch_with_retries(url, timeout=args.timeout, retries=args.retries)
            output_path = args.output_dir / make_output_name(url, data)
            write_json_atomic(output_path, data)
            print(f"[{index}/{len(urls)}] OK     {output_path.as_posix()}")
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            failures.append((url, message))
            print(f"[{index}/{len(urls)}] ÉCHEC  {url}\n             {message}")

    print(f"\nTerminé : {len(urls) - len(failures)}/{len(urls)} fichier(s) téléchargé(s).")
    if failures:
        print("Échecs :")
        for url, message in failures:
            print(f"- {url}\n  {message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
