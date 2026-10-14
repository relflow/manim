"""Export static video metadata and accessible transcripts to the docs checkout.

This module uses only the standard library. Rendering and RelFlow runtime imports
are intentionally outside the documentation publication boundary.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
GENERATED = "<!-- Generated from series.json by relflow/manim tools.catalog. -->"


class CatalogError(ValueError):
    """An invalid source or unsafe publication destination."""


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CatalogError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise CatalogError(f"Expected a schema 1 object in {path}")
    return value


def safe_id(value: object) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise CatalogError(f"Invalid video id: {value!r}; use lowercase letters, digits, and hyphens")
    return value


def safe_page(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CatalogError(f"Invalid documentation page: {value!r}")
    page = PurePosixPath(value)
    if (
        page.is_absolute()
        or page.suffix != ".qmd"
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or re.fullmatch(r"[A-Za-z0-9_./-]+", value) is None
    ):
        raise CatalogError(f"Documentation page must be a safe relative .qmd path: {value!r}")
    return value


def text_value(segment: dict, key: str) -> str:
    value = segment.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"Video {segment.get('id')!r} needs a nonempty {key}")
    return value


def validate_segment(segment: object) -> dict:
    if not isinstance(segment, dict):
        raise CatalogError("Every segment must be an object")
    safe_id(segment.get("id"))
    safe_page(segment.get("page"))
    text_value(segment, "title")
    text_value(segment, "scene")
    if segment.get("level") not in {"intro", "advanced"}:
        raise CatalogError(f"Invalid level for video {segment['id']!r}")
    youtube_id = segment.get("youtube_id")
    if youtube_id is not None and (not isinstance(youtube_id, str) or YOUTUBE_ID.fullmatch(youtube_id) is None):
        raise CatalogError(f"Video {segment['id']!r} needs an 11-character YouTube id or null")
    return segment


def transcript(segment: dict, docs_base: str) -> str:
    """Preserve archived narration verbatim; describe every new visual in text."""
    if "transcript_body" in segment:
        body = segment["transcript_body"]
        if not isinstance(body, str) or not body.strip():
            raise CatalogError(f"Empty archived transcript for {segment['id']!r}")
        return body
    beats = segment.get("beats")
    if not isinstance(beats, list) or not beats:
        raise CatalogError(f"Video {segment['id']!r} needs narration beats or an archived transcript")
    sections = [f"# {segment['title']}", GENERATED]
    for beat in beats:
        if not isinstance(beat, dict):
            raise CatalogError(f"Invalid beat in {segment['id']!r}")
        for key in ("title", "narration", "visual"):
            if not isinstance(beat.get(key), str) or not beat[key].strip():
                raise CatalogError(f"Video {segment['id']!r} has a beat without {key}")
        lines = beat.get("lines")
        if not isinstance(lines, list) or not lines or not all(isinstance(line, str) for line in lines):
            raise CatalogError(f"Video {segment['id']!r} has a visual without text lines")
        language = "python" if beat["visual"] == "code" else "text"
        sections.extend([f"## {beat['title']}", beat["narration"], f"```{language}\n" + "\n".join(lines) + "\n```"])
    page_url = docs_base.rstrip("/") + "/" + str(PurePosixPath(segment["page"]).with_suffix(".html"))
    sections.append(f"Read the documentation: [{segment['title']}]({page_url}).")
    return "\n\n".join(sections) + "\n"


def publication(source_root: Path = ROOT) -> tuple[dict, dict[str, str]]:
    series = read_json(source_root / "series.json")
    target = series.get("target")
    if not isinstance(target, dict) or not target.get("version") or not target.get("repository"):
        raise CatalogError("series.json needs target version and repository provenance")
    docs_base = series.get("docs_base")
    if not isinstance(docs_base, str) or not docs_base.startswith("https://"):
        raise CatalogError("series.json needs an https docs_base")
    sources = [series]
    archive_path = source_root / "archive-catalog.json"
    if archive_path.is_file():
        sources.append(read_json(archive_path))
    entries: list[dict] = []
    transcripts: dict[str, str] = {}
    for source in sources:
        segments = source.get("segments")
        if not isinstance(segments, list):
            raise CatalogError("A source catalog needs a segments list")
        for value in segments:
            segment = validate_segment(value)
            segment_id = segment["id"]
            if segment_id in transcripts:
                raise CatalogError(f"Duplicate video id: {segment_id}")
            entry = {key: segment[key] for key in ("id", "title", "page", "scene", "level")}
            entry["youtube_id"] = segment.get("youtube_id")
            entry["transcript"] = f"assets/videos/transcripts/{segment_id}.md"
            for key in ("state", "source_version"):
                if key in segment:
                    entry[key] = text_value(segment, key)
            entries.append(entry)
            transcripts[segment_id] = transcript(segment, docs_base)
    if not entries:
        raise CatalogError("The video series is empty")
    return {"schema": 1, "target": target, "segments": entries}, transcripts


def inside_site(path: Path, site: Path) -> None:
    if not path.resolve().is_relative_to(site.resolve()):
        raise CatalogError(f"Publication path leaves the docs site: {path}")
    if path.is_symlink():
        raise CatalogError(f"Refusing to overwrite a symbolic link: {path}")


def previous_transcripts(catalog_path: Path) -> set[str]:
    """Only an existing well-formed catalog establishes transcript ownership."""
    if not catalog_path.exists():
        return set()
    previous = read_json(catalog_path)
    segments = previous.get("segments")
    if not isinstance(segments, list):
        raise CatalogError(f"Refusing to overwrite an unrelated catalog: {catalog_path}")
    owned: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            raise CatalogError(f"Invalid existing catalog: {catalog_path}")
        segment_id = safe_id(segment.get("id"))
        expected = f"assets/videos/transcripts/{segment_id}.md"
        if segment.get("transcript") != expected:
            raise CatalogError(f"Invalid existing transcript ownership for {segment_id!r}")
        owned.add(segment_id)
    return owned


def export_catalog(docs_root: Path, *, source_root: Path = ROOT, check: bool = False) -> list[Path]:
    """Publish expected files only; never remove stale or unrelated output."""
    catalog, transcripts = publication(source_root)
    site = docs_root.resolve() / "docs"
    if not (site / "_quarto.yml").is_file():
        raise CatalogError(f"Expected a documentation checkout with docs/_quarto.yml: {docs_root}")
    for entry in catalog["segments"]:
        page_path = site / entry["page"]
        inside_site(page_path, site)
        if not page_path.is_file():
            raise CatalogError(f"Documentation page does not exist: {entry['page']}")
    catalog_path = site / "assets/videos/catalog.json"
    plan = {site / f"assets/videos/transcripts/{key}.md": value for key, value in transcripts.items()}
    plan[catalog_path] = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    changed: list[Path] = []
    for path, body in plan.items():
        inside_site(path, site)
        if not path.exists() or path.read_text(encoding="utf-8") != body:
            changed.append(path)
    if check:
        if changed:
            names = ", ".join(str(path.relative_to(site)) for path in changed)
            raise CatalogError(f"Video publication is out of date: {names}")
        return []
    owned = previous_transcripts(catalog_path)
    for path in changed:
        if path == catalog_path or not path.exists():
            continue
        if path.stem not in owned:
            raise CatalogError(f"Refusing to overwrite an unowned transcript: {path}")
    for path in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan[path], encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", required=True, type=Path, help="RelFlow documentation repository checkout")
    parser.add_argument("--check", action="store_true", help="Compare expected publication without writing files")
    args = parser.parse_args(argv)
    try:
        changed = export_catalog(args.docs, check=args.check)
    except CatalogError as error:
        parser.exit(1, f"{error}\n")
    print("Video catalog and transcripts are current." if args.check else f"Published {len(changed)} changed files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
