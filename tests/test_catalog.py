"""Static publication contracts; these fixtures never import or invoke Manim."""

import json
from pathlib import Path

import pytest

from tools.catalog import CatalogError, export_catalog, publication


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "manim"
    source.mkdir()
    docs = tmp_path / "docs-repo"
    site = docs / "docs"
    site.mkdir(parents=True)
    (site / "_quarto.yml").write_text("project:\n  type: website\n")
    (site / "getting-started.qmd").write_text("# Your First Model\n")
    (site / "mechanisms").mkdir()
    (site / "mechanisms/history.qmd").write_text("# Historical Mechanism\n")
    series = {
        "schema": 1,
        "target": {"version": "0.2.4", "repository": "https://github.com/relflow/relflow"},
        "docs_base": "https://relflow.github.io/docs/",
        "segments": [
            {
                "id": "first-model",
                "title": "Your First Model",
                "page": "getting-started.qmd",
                "scene": "FirstModel",
                "level": "intro",
                "youtube_id": None,
                "beats": [
                    {
                        "title": "Keep the answer hidden",
                        "narration": "The dispute label supplies an answer without becoming an input.",
                        "visual": "code",
                        "lines": ["disputed = rf.Boolean(mask=True)"],
                    },
                    {
                        "title": "Follow the evidence",
                        "narration": "Current payment fields support this prediction.",
                        "visual": "tree",
                        "lines": ["payment", "  amount + merchant", "  disputed: target"],
                    },
                ],
            }
        ],
    }
    (source / "series.json").write_text(json.dumps(series))
    return source, docs, series


def store_series(source: Path, series: dict) -> None:
    (source / "series.json").write_text(json.dumps(series))


def test_export_combines_current_and_historical_without_changing_archive_narration(workspace):
    source, docs, series = workspace
    archived_body = "# Historical mechanism\n\nOriginal narration, including  spacing.\n"
    archived = {
        "schema": 1,
        "segments": [
            {
                "id": "history-mechanism",
                "title": "Historical mechanism",
                "page": "mechanisms/history.qmd",
                "scene": "S04Ragged",
                "level": "advanced",
                "youtube_id": "aB012345_-Z",
                "state": "historical",
                "source_version": "0.2.3",
                "beats": [],
                "transcript_body": archived_body,
            }
        ],
    }
    (source / "archive-catalog.json").write_text(json.dumps(archived))
    changed = export_catalog(docs, source_root=source)
    assert len(changed) == 3
    catalog = json.loads((docs / "docs/assets/videos/catalog.json").read_text())
    assert catalog["target"] == series["target"]
    assert [entry["id"] for entry in catalog["segments"]] == ["first-model", "history-mechanism"]
    historical = catalog["segments"][1]
    assert historical["state"] == "historical"
    assert historical["source_version"] == "0.2.3"
    assert historical["youtube_id"] == "aB012345_-Z"
    assert (docs / "docs" / historical["transcript"]).read_text() == archived_body
    current = (docs / "docs" / catalog["segments"][0]["transcript"]).read_text()
    assert "```python\ndisputed = rf.Boolean(mask=True)\n```" in current
    assert "```text\npayment\n  amount + merchant\n  disputed: target\n```" in current
    assert series["segments"][0]["beats"][0]["narration"] in current
    assert "https://relflow.github.io/docs/getting-started.html" in current
    assert export_catalog(docs, source_root=source, check=True) == []


@pytest.mark.parametrize("bad_id", ["", "../../elsewhere", "Uppercase", "with spaces"])
def test_unsafe_ids_rejected_before_publication(workspace, bad_id):
    source, docs, series = workspace
    series["segments"][0]["id"] = bad_id
    store_series(source, series)
    with pytest.raises(CatalogError, match="Invalid video id"):
        export_catalog(docs, source_root=source)
    assert not (docs / "docs/assets").exists()


@pytest.mark.parametrize(
    "page",
    ["../outside.qmd", "/absolute.qmd", "guides/../../outside.qmd", "guide.md", "a\\b.qmd", "a//b.qmd"],
)
def test_unsafe_pages_rejected(workspace, page):
    source, _, series = workspace
    series["segments"][0]["page"] = page
    store_series(source, series)
    with pytest.raises(CatalogError, match="page"):
        publication(source)


@pytest.mark.parametrize("youtube_id", ["", "too-short", "0123456789/", "https://youtu.be/aB012345_-Z", 12345678901])
def test_youtube_ids_are_real_id_shapes_only(workspace, youtube_id):
    source, _, series = workspace
    series["segments"][0]["youtube_id"] = youtube_id
    store_series(source, series)
    with pytest.raises(CatalogError, match="11-character YouTube id or null"):
        publication(source)


def test_duplicate_ids_across_series_and_archive_rejected(workspace):
    source, _, series = workspace
    (source / "archive-catalog.json").write_text(json.dumps({"schema": 1, "segments": series["segments"]}))
    with pytest.raises(CatalogError, match="Duplicate video id"):
        publication(source)


def test_dry_check_never_writes_and_detects_changed_narration(workspace):
    source, docs, series = workspace
    with pytest.raises(CatalogError, match="out of date"):
        export_catalog(docs, source_root=source, check=True)
    assert not (docs / "docs/assets").exists()
    export_catalog(docs, source_root=source)
    path = docs / "docs/assets/videos/transcripts/first-model.md"
    before = path.read_bytes()
    series["segments"][0]["beats"][0]["narration"] = "A corrected explanation."
    store_series(source, series)
    with pytest.raises(CatalogError, match="out of date"):
        export_catalog(docs, source_root=source, check=True)
    assert path.read_bytes() == before
    export_catalog(docs, source_root=source)
    assert "A corrected explanation." in path.read_text()


def test_unrelated_files_are_preserved_and_target_collisions_are_refused(workspace):
    source, docs, _ = workspace
    directory = docs / "docs/assets/videos/transcripts"
    directory.mkdir(parents=True)
    unrelated = directory / "personal-notes.md"
    unrelated.write_text("Keep this document.\n")
    collision = directory / "first-model.md"
    collision.write_text("A hand-authored transcript.\n")
    with pytest.raises(CatalogError, match="unowned transcript"):
        export_catalog(docs, source_root=source)
    assert collision.read_text() == "A hand-authored transcript.\n"
    assert not (directory.parent / "catalog.json").exists()
    collision.unlink()
    export_catalog(docs, source_root=source)
    assert unrelated.read_text() == "Keep this document.\n"


def test_export_does_not_delete_previously_owned_transcripts(workspace):
    source, docs, series = workspace
    old = {**series["segments"][0], "id": "old-clip"}
    series["segments"].append(old)
    store_series(source, series)
    export_catalog(docs, source_root=source)
    old_path = docs / "docs/assets/videos/transcripts/old-clip.md"
    old_content = old_path.read_bytes()
    series["segments"].pop()
    store_series(source, series)
    export_catalog(docs, source_root=source)
    assert old_path.read_bytes() == old_content


def test_symlink_escape_is_refused_before_any_write(workspace, tmp_path):
    source, docs, _ = workspace
    outside = tmp_path / "external-assets"
    outside.mkdir()
    (docs / "docs/assets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CatalogError, match="leaves the docs site"):
        export_catalog(docs, source_root=source)
    assert list(outside.iterdir()) == []


def test_missing_doc_page_does_not_publish_a_dangling_link(workspace):
    source, docs, series = workspace
    series["segments"][0]["page"] = "not-yet-authored.qmd"
    store_series(source, series)
    with pytest.raises(CatalogError, match="page does not exist"):
        export_catalog(docs, source_root=source)
    assert not (docs / "docs/assets").exists()
