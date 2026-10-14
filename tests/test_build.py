from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
import pytest

from tools import build
from tools.build import cues, load, stamp


def test_caption_intervals_cover_the_utterance_without_overlap():
    beat = {"narration": "One payment has an amount and a merchant. The outcome arrives later."}
    result = cues(beat, start=2.0, duration=9.3)
    assert result[0][0] == 2.0
    assert math.isclose(result[-1][1], 11.3)
    assert all(a < b for a, b, _ in result)
    assert all(left[1] == right[0] for left, right in zip(result, result[1:]))
    assert " ".join(text for _, _, text in result) == beat["narration"]


def test_timestamp_rounding_carries_into_next_minute():
    assert stamp(59.9996) == "00:01:00,000"
    assert stamp(3600.002, ".") == "01:00:00.002"


def test_public_examples_parse_without_importing_relflow():
    series = load()
    assert series["segments"][0]["id"] == "first-model"
    assert series["segments"][1]["id"] == "transaction-history"
    assert all(
        segment["youtube_id"] is None or re.fullmatch(r"[A-Za-z0-9_-]{11}", segment["youtube_id"])
        for segment in series["segments"]
    )
    for segment in series["segments"]:
        for beat in segment["beats"]:
            if beat["visual"] == "code":
                ast.parse("\n".join(beat["lines"]))


def test_video_runtime_has_no_model_or_archived_experiment_dependency():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "scenes.py", root / "tools/build.py"):
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(item.name.split(".")[0] for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "").split(".")[0])
        assert not {"relflow", "torch", "lightning", "transformers", "explainer"}.intersection(imports)


@pytest.fixture
def render_fixture(tmp_path, monkeypatch):
    segment = {
        "id": "review-clip",
        "title": "A reviewable clip",
        "page": "guides/prediction-output.qmd",
        "scene": "ReviewClip",
        "level": "intro",
        "beats": [
            {
                "title": title,
                "narration": "Visible evidence supports a hidden prediction. Check the result with held-out observations.",
                "visual": "flow",
                "lines": ["Visible evidence", "Hidden outcome", "Evaluate the prediction"],
            }
            for title in ["Observation", "Schema", "Prediction", "Evaluation"]
        ],
    }
    series = {
        "schema": 1,
        "series": "RelFlow, Visualized",
        "target": {"version": "0.2.4", "state": "working-tree"},
        "docs_base": "https://relflow.github.io/docs/",
        "segments": [segment],
    }
    (tmp_path / "series.json").write_text(json.dumps(series))
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    monkeypatch.setattr(build, "ROOT", tmp_path)
    return tmp_path, series, segment


def write_recording(path, *, frames, channels=2, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(channels)
        recording.setsampwidth(2)
        recording.setframerate(rate)
        recording.writeframes(b"\x10\x00" * channels * frames)


def test_recorded_voice_is_normalized_and_timing_comes_from_audio(render_fixture):
    root, _, segment = render_fixture
    audio_root = root / "audio"
    source = audio_root / segment["id"] / "01.wav"
    write_recording(source, frames=14400)
    folder = root / "build" / segment["id"]
    folder.mkdir(parents=True)
    output, spoken = build.audio(segment, 0, "files", folder, audio_root, imageio_ffmpeg.get_ffmpeg_exe())
    assert math.isclose(spoken, 0.9, abs_tol=1 / 48000)
    with wave.open(output) as normalized:
        assert normalized.getnchannels() == 1
        assert normalized.getframerate() == 48000
        assert normalized.getsampwidth() == 2
    with wave.open(str(source)) as original:
        assert original.getnchannels() == 2
        assert original.getframerate() == 16000


def test_missing_and_empty_recordings_fail_explicitly(render_fixture):
    root, _, segment = render_fixture
    folder = root / "build" / segment["id"]
    folder.mkdir(parents=True)
    audio_root = root / "audio"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with pytest.raises(FileNotFoundError, match="Missing narration"):
        build.audio(segment, 0, "files", folder, audio_root, ffmpeg)
    write_recording(audio_root / segment["id"] / "01.wav", frames=0)
    with pytest.raises(ValueError, match="Empty narration"):
        build.audio(segment, 0, "files", folder, audio_root, ffmpeg)


def test_system_voice_reports_platform_requirement(render_fixture, monkeypatch):
    root, _, segment = render_fixture
    monkeypatch.setattr(build.sys, "platform", "linux")
    with pytest.raises(ValueError, match="requires macOS"):
        build.audio(segment, 0, "system", root, root / "audio", "unused-ffmpeg")


@pytest.mark.parametrize("quality,fps", [("preview", 15), ("production", 30)])
def test_schedule_fits_each_recording_and_rounds_to_video_frames(render_fixture, monkeypatch, quality, fps):
    root, _, segment = render_fixture
    durations = [0.1, 6.15, 13.111, 20.0]
    monkeypatch.setattr(build, "audio", lambda _, index, *args: (None, durations[index]))
    timing = build.prepare(segment, "silent", quality, root / "audio", "unused-ffmpeg")
    assert timing["beats"][0]["start"] == build.INTRO
    for schedule, spoken in zip(timing["beats"], durations, strict=True):
        assert schedule["duration"] >= spoken + 0.8
        assert schedule["duration"] >= 6.0
        assert math.isclose(schedule["duration"] * fps, round(schedule["duration"] * fps))
    for left, right in zip(timing["beats"], timing["beats"][1:]):
        assert math.isclose(left["start"] + left["duration"], right["start"])
    final = timing["beats"][-1]
    assert math.isclose(timing["duration"], final["start"] + final["duration"] + build.OUTRO)
    assert json.loads((root / "build/review-clip/timing.json").read_text()) == timing


def test_package_captions_match_recording_schedule_and_chapters_start_at_zero(render_fixture, monkeypatch):
    root, series, segment = render_fixture
    monkeypatch.setattr(build, "audio", lambda *args: (None, 10.0))
    timing = build.prepare(segment, "silent", "production", root / "audio", "unused-ffmpeg")
    output = build.package(series, segment, timing, "production")
    srt = (output / "captions.srt").read_text()
    vtt = (output / "captions.vtt").read_text()
    assert vtt.startswith("WEBVTT\n\n")
    for schedule in timing["beats"]:
        assert stamp(schedule["start"]) in srt
        assert stamp(schedule["start"] + schedule["spoken"]) in srt
        assert stamp(schedule["start"], ".") in vtt
        assert stamp(schedule["start"] + schedule["spoken"], ".") in vtt
    chapters = (output / "chapters.txt").read_text().splitlines()
    assert chapters[0] == "00:00 Observation"
    assert len(chapters) == len(segment["beats"])
    assert [line.split(" ", 1)[1] for line in chapters] == [beat["title"] for beat in segment["beats"]]
    assert "REVIEW ONLY" in (output / "youtube.txt").read_text()
    assert "https://relflow.github.io/docs/guides/prediction-output.html" in (output / "youtube.txt").read_text()
    assert all(beat["narration"] in (output / "transcript.md").read_text() for beat in segment["beats"])
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["voice"] == "silent"
    assert provenance["duration"] == timing["duration"]
    assert "review before upload" in provenance["caption_alignment"]


def test_provenance_identifies_recorded_audio_visual_assets_and_timing(render_fixture):
    root, series, segment = render_fixture
    audio_root = root / "audio"
    for index in range(4):
        write_recording(audio_root / segment["id"] / f"{index + 1:02d}.wav", frames=14400 + index * 1600)
    timing = build.prepare(segment, "files", "production", audio_root, imageio_ffmpeg.get_ffmpeg_exe())
    folder = build.package(series, segment, timing, "production")
    provenance = json.loads((folder / "provenance.json").read_text())
    assert provenance["voice"] == "files"
    assert provenance["assets"] == {
        "assets/logo.svg": hashlib.sha256((root / "assets/logo.svg").read_bytes()).hexdigest()
    }
    assert len(provenance["audio"]) == 4
    for index, schedule in enumerate(timing["beats"], 1):
        assert (
            provenance["audio"][f"{index:02d}.wav"] == hashlib.sha256(Path(schedule["audio"]).read_bytes()).hexdigest()
        )
        recorded = provenance["beats"][index - 1]
        assert recorded["start"] == schedule["start"]
        assert recorded["duration"] == schedule["duration"]
        assert recorded["spoken"] == schedule["spoken"]
    assert all(line in (folder / "transcript.md").read_text() for line in segment["beats"][0]["lines"])


def test_failed_render_preserves_the_previous_publication(render_fixture, monkeypatch):
    root, series, segment = render_fixture
    output = root / "dist" / segment["id"]
    output.mkdir(parents=True)
    previous = {"review-clip.mp4": b"previous video", "captions.srt": b"previous matching captions"}
    for name, value in previous.items():
        (output / name).write_bytes(value)
    timing = {
        "intro": 2,
        "outro": 3,
        "beats": [{"start": 2 + index * 12, "duration": 12, "spoken": 10, "audio": None} for index in range(4)],
        "duration": 53,
        "voice": "silent",
    }
    monkeypatch.setattr(build, "load", lambda: series)
    monkeypatch.setattr(build, "prepare", lambda *args: timing)
    monkeypatch.setattr(sys, "argv", ["build", segment["id"], "--voice", "silent"])

    def fail_renderer(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(build.subprocess, "run", fail_renderer)
    with pytest.raises(subprocess.CalledProcessError):
        build.main()
    assert {path.name: path.read_bytes() for path in output.iterdir()} == previous


def test_check_command_does_not_import_render_or_model_dependencies():
    root = Path(__file__).resolve().parents[1]
    script = """
import builtins
import sys
original_import = builtins.__import__
forbidden = {'manim', 'imageio_ffmpeg', 'relflow', 'torch', 'lightning', 'transformers'}
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in forbidden:
        raise AssertionError('Unexpected dependency in static check: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
sys.argv = ['build', '--check']
from tools.build import main
main()
"""
    completed = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "no model code executed" in completed.stdout
