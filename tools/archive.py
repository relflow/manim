"""Extract the historical series without importing its scenes or running experiments."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path("archive/relflow-0.2.3")
SOURCE_COMMIT = "4679d69d9bf15cad1467803c68c3d7f5ecae3cec"
MECHANISM_PAGES = {
    "inside-a-branch": "guides/mechanisms/field-interactions.qmd",
    "softmax-cant-count": "guides/mechanisms/branch-reduction.qmd",
    "climbing-the-tree": "guides/mechanisms/tree-routing.qmd",
}


def episode_definitions(root: Path = ROOT) -> list[tuple]:
    """Read the manifest's literal episode list, executing no Python source."""
    manifest = root / ARCHIVE / "manifest.py"
    module = ast.parse(manifest.read_text())
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_EPISODES" for target in statement.targets
        ):
            episodes = ast.literal_eval(statement.value)
            if not isinstance(episodes, list) or len(episodes) != 21:
                raise ValueError("expected the original 21 manifest episodes")
            return episodes
    raise ValueError("original manifest contains no literal _EPISODES")


def narration(root: Path = ROOT) -> dict[str, tuple[str, str]]:
    """Index the committed narration by its scene marker, preserving its words."""
    script = (root / ARCHIVE / "SCRIPT.md").read_text()
    scenes = {}
    for section in re.split(r"(?m)^## ", script)[1:]:
        title, body = section.split("\n", 1)
        marker = re.match(r"\s*_Scene `([^`]+)`_\s*\n", body)
        if marker is None:
            raise ValueError(f"missing scene marker for {title}")
        key = marker.group(1)
        if key in scenes:
            raise ValueError(f"duplicate narration scene {key}")
        scenes[key] = (title, body[marker.end() :].strip())
    if len(scenes) != 21:
        raise ValueError("expected 21 sections in the original narration")
    return scenes


def derive_catalog(root: Path = ROOT) -> dict:
    """Derive publication metadata from unmodified sources and saved YouTube IDs."""
    saved = root / "archive-catalog.json"
    published = {}
    if saved.is_file():
        published = {entry["id"]: entry.get("youtube_id") for entry in json.loads(saved.read_text())["segments"]}
    transcripts = narration(root)
    episodes_text = (root / ARCHIVE / "EPISODES.md").read_text()
    durations = {
        int(number): duration for number, duration in re.findall(r"(?m)^\| (\d+) \| .*? \| ([\d:]+) \|", episodes_text)
    }
    upload_text = {}
    for section in re.split(r"(?m)^## ", episodes_text)[1:]:
        heading, body = section.split("\n", 1)
        number = int(heading.split(".", 1)[0])
        title_line = re.match(r"\s*\*\*YouTube title:\*\* ([^\n]+)\s*\n", body)
        if title_line is None:
            raise ValueError(f"missing original YouTube title for {heading}")
        upload_text[number] = (title_line.group(1), body[title_line.end() :].strip())
    segments = []
    for number, (slug, module, scene, title, original_pages) in enumerate(episode_definitions(root), 1):
        key = f"{module}.py::{scene}"
        script_title, body = transcripts[key]
        if script_title != title:
            raise ValueError(f"narration title differs from manifest: {key}")
        identifier = "legacy-pretraining" if slug == "pretraining" else slug
        page = MECHANISM_PAGES.get(slug, original_pages[0])
        pages = [page, *[item for item in original_pages if item != page]]
        segments.append(
            {
                "id": identifier,
                "original_slug": slug,
                "number": number,
                "title": title,
                "page": page,
                "pages": pages,
                "original_pages": original_pages,
                "scene": scene,
                "module": module,
                "source": (ARCHIVE / f"{module}.py").as_posix(),
                "level": "advanced",
                "state": "historical",
                "source_version": "0.2.3",
                "source_commit": "5077716",
                "duration": durations.get(number),
                "youtube_title": upload_text[number][0],
                "description": upload_text[number][1],
                "youtube_id": published.get(identifier),
                "beats": [],
                "transcript_body": f"# {title}\n\n{body}\n",
            }
        )
    return {
        "schema": 1,
        "series": "relflow, Visualized",
        "target": {
            "version": "0.2.3",
            "commit": "5077716",
            "repository": "https://github.com/relflow/relflow",
            "state": "historical",
        },
        "source_archive": {
            "repository": "https://github.com/relflow/relflow",
            "branch": "feature/explainer-video",
            "commit": SOURCE_COMMIT,
            "path": "explainer-video/",
            "local_path": ARCHIVE.as_posix(),
        },
        "docs_base": "https://relflow.github.io/docs/",
        "segments": segments,
    }


def archived_segments(root: Path = ROOT) -> list[dict]:
    """Return the checked-in historical metadata for the static docs exporter."""
    return json.loads((root / "archive-catalog.json").read_text())["segments"]


def checksums(root: Path = ROOT) -> str:
    """Fingerprint original files and the separately retained licenses/assets."""
    files = sorted((root / ARCHIVE).rglob("*"))
    files += [root / "LICENSE", root / "NOTICE"]
    files += sorted((root / "assets").rglob("*"))
    return "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n"
        for path in files
        if path.is_file()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify catalog derivation and original fingerprints")
    options = parser.parse_args()
    metadata = json.dumps(derive_catalog(), indent=2, ensure_ascii=False) + "\n"
    fingerprint = checksums()
    outputs = {ROOT / "archive-catalog.json": metadata, ROOT / "archive/checksums.sha256": fingerprint}
    if options.check:
        different = [path.relative_to(ROOT).as_posix() for path, value in outputs.items() if path.read_text() != value]
        if different:
            raise SystemExit("archive verification failed: " + ", ".join(different))
        print("Original 21-episode metadata, transcripts, and source fingerprints verified")
    else:
        for path, value in outputs.items():
            path.write_text(value)
        print("Wrote historical 21-episode catalog and source fingerprints")


if __name__ == "__main__":
    main()
