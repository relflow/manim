"""Render individual docs segments and prepare reviewable YouTube upload folders."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from tools.catalog import transcript

ROOT = Path(__file__).resolve().parents[1]
INTRO = 2.0
OUTRO = 3.0


def load() -> dict:
    series = json.loads((ROOT / "series.json").read_text())
    identifiers = set()
    scenes = set()
    for segment in series["segments"]:
        identifier = segment["id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]*", identifier) or identifier in identifiers:
            raise ValueError(f"Invalid or repeated segment id: {identifier}")
        if segment["scene"] in scenes:
            raise ValueError(f"Repeated Manim scene: {segment['scene']}")
        identifiers.add(identifier)
        scenes.add(segment["scene"])
        if len(segment["beats"]) != 4:
            raise ValueError(f"{identifier} must contain four narration beats")
        for beat in segment["beats"]:
            if beat["visual"] not in {"record", "code", "flow", "history", "tree", "prediction", "mask", "embedding"}:
                raise ValueError(f"{identifier}: unknown visual {beat['visual']}")
            if not beat["narration"].strip() or not beat["lines"]:
                raise ValueError(f"{identifier}: empty narration or visual")
            if beat["visual"] == "code":
                ast.parse("\n".join(beat["lines"]))
    return series


def stamp(seconds: float, separator: str = ",") -> str:
    millis = round(seconds * 1000)
    whole, ms = divmod(millis, 1000)
    minutes, second = divmod(whole, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02d}:{minute:02d}:{second:02d}{separator}{ms:03d}"


def cues(beat: dict, start: float, duration: float) -> list[tuple[float, float, str]]:
    # Sentence captions use the real utterance duration; this is not word alignment.
    sentences = re.split(r"(?<=[.!?])\s+", beat["narration"])
    chunks = []
    for sentence in sentences:
        words = sentence.split()
        chunks.extend(" ".join(words[i : i + 13]) for i in range(0, len(words), 13))
    total = sum(len(chunk.split()) for chunk in chunks)
    elapsed = start
    result = []
    for chunk in chunks:
        end = elapsed + duration * len(chunk.split()) / total
        result.append((elapsed, end, chunk))
        elapsed = end
    return result


def audio(
    segment: dict, index: int, voice: str, folder: Path, audio_dir: Path, ffmpeg: str
) -> tuple[str | None, float]:
    beat = segment["beats"][index]
    if voice == "silent":
        return None, max(8.0, len(beat["narration"].split()) / 2.6)
    wav = folder / f"{index + 1:02d}.wav"
    if voice == "files":
        source = audio_dir / segment["id"] / f"{index + 1:02d}.wav"
        if not source.is_file():
            raise FileNotFoundError(f"Missing narration: {source}; record it or use --voice system/silent")
    else:
        if sys.platform != "darwin":
            raise ValueError("--voice system requires macOS; supply --voice files or --voice silent")
        source = folder / f"{index + 1:02d}.aiff"
        subprocess.run(["say", "-r", "165", "-o", str(source), "--", beat["narration"]], check=True)
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "48000", str(wav)],
        check=True,
    )
    with wave.open(str(wav)) as recording:
        duration = recording.getnframes() / recording.getframerate()
    if duration <= 0:
        raise ValueError(f"Empty narration: {source}")
    return str(wav), duration


def prepare(segment: dict, voice: str, quality: str, audio_dir: Path, ffmpeg: str) -> dict:
    folder = ROOT / "build" / segment["id"]
    folder.mkdir(parents=True, exist_ok=True)
    fps = 15 if quality == "preview" else 30
    beats = []
    start = INTRO
    for index, beat in enumerate(segment["beats"]):
        recording, spoken = audio(segment, index, voice, folder, audio_dir, ffmpeg)
        # Round every duration to a frame so scene timing, captions, and audio agree.
        duration = (int(max(6.0, spoken + 0.8) * fps + 0.9999)) / fps
        beats.append({"start": start, "duration": duration, "spoken": spoken, "audio": recording})
        start += duration
    timing = {"intro": INTRO, "outro": OUTRO, "beats": beats, "duration": start + OUTRO, "voice": voice}
    (folder / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    return timing


def package(series: dict, segment: dict, timing: dict, quality: str) -> Path:
    folder = ROOT / "dist" / segment["id"]
    folder.mkdir(parents=True, exist_ok=True)
    subtitles = []
    chapters = [f"00:00 {segment['beats'][0]['title']}"]
    for beat, schedule in zip(segment["beats"], timing["beats"], strict=True):
        subtitles.extend(cues(beat, schedule["start"], schedule["spoken"]))
        if schedule is not timing["beats"][0]:
            minutes, seconds = divmod(int(schedule["start"]), 60)
            chapters.append(f"{minutes:02d}:{seconds:02d} {beat['title']}")
    (folder / "captions.srt").write_text(
        "\n\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{t}" for i, (a, b, t) in enumerate(subtitles, 1)) + "\n"
    )
    (folder / "captions.vtt").write_text(
        "WEBVTT\n\n" + "\n\n".join(f"{stamp(a, '.')} --> {stamp(b, '.')}\n{t}" for a, b, t in subtitles) + "\n"
    )
    (folder / "chapters.txt").write_text("\n".join(chapters) + "\n")
    (folder / "transcript.md").write_text(transcript(segment, series["docs_base"]))
    page = series["docs_base"] + segment["page"].removesuffix(".qmd") + ".html"
    description = f"{segment['title']} | {series['series']}\n\n"
    description += segment["beats"][0]["narration"] + f"\n\nRead the guide: {page}\n"
    description += "Sources: https://github.com/relflow/manim\n\n" + "\n".join(chapters)
    description += "\n\nDiagrams are schematic. Illustrative values are not measured model results.\n"
    if timing["voice"] == "silent":
        description += "REVIEW ONLY: this render has no narration.\n"
    (folder / "youtube.txt").write_text(description)
    provenance = {
        "segment": segment["id"],
        "target": series["target"],
        "quality": quality,
        "voice": timing["voice"],
        "duration": timing["duration"],
        "caption_alignment": "proportional by word count within each measured utterance; review before upload",
        "inputs": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("series.json", "scenes.py", "tools/build.py", "uv.lock")
            if (ROOT / name).is_file()
        },
        "assets": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "assets").iterdir())
            if path.is_file()
        },
        "audio": {
            f"{i:02d}.wav": hashlib.sha256(Path(beat["audio"]).read_bytes()).hexdigest()
            for i, beat in enumerate(timing["beats"], 1)
            if beat["audio"]
        },
        "timing": {key: value for key, value in timing.items() if key != "beats"},
        "beats": [{key: value for key, value in beat.items() if key != "audio"} for beat in timing["beats"]],
    }
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segment", nargs="?", default="all")
    parser.add_argument("--quality", choices=["preview", "production"], default="preview")
    parser.add_argument("--voice", choices=["files", "system", "silent"], default="files")
    parser.add_argument("--audio-dir", type=Path, default=ROOT / "audio")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    series = load()
    if args.check:
        print(f"Validated {len(series['segments'])} independent segments; no model code executed")
        return
    selected = [item for item in series["segments"] if args.segment in {"all", item["id"]}]
    if not selected:
        parser.error(f"Unknown segment: {args.segment}")
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    bindir = ROOT / "build" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir / "ffmpeg"
    if not link.exists():
        link.symlink_to(ffmpeg)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    for segment in selected:
        timing = prepare(segment, args.voice, args.quality, args.audio_dir, ffmpeg)
        print(f"Rendering {segment['id']}: {timing['duration']:.1f}s, {args.voice}", flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "manim",
                "-ql" if args.quality == "preview" else "-qh",
                "--fps",
                "15" if args.quality == "preview" else "30",
                "--disable_caching",
                "--format=mp4",
                "-o",
                segment["id"],
                str(ROOT / "scenes.py"),
                segment["scene"],
            ],
            cwd=ROOT,
            env={**env, "RELFLOW_MANIM_SEGMENT": segment["id"]},
            check=True,
        )
        output = ROOT / "media" / "videos" / "scenes" / ("480p15" if args.quality == "preview" else "1080p30")
        source = output / f"{segment['id']}.mp4"
        if not source.is_file():
            raise FileNotFoundError(f"Manim did not produce the expected video: {source}")
        folder = package(series, segment, timing, args.quality)
        shutil.copy2(source, folder / source.name)
        print(f"Prepared {folder}", flush=True)


if __name__ == "__main__":
    main()
