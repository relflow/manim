"""Validate completed MP4 packages and build a local, self-contained review gallery."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMESTAMP = r"\d{2,}:\d{2}:\d{2}\.\d{3}"
CUE = re.compile(rf"^({TIMESTAMP})\s+-->\s+({TIMESTAMP})(?:\s.*)?$")


class ReviewError(ValueError):
    """A rendered package does not match its recorded publication contract."""


def seconds(timestamp: str) -> float:
    hour, minute, second = timestamp.split(":")
    return int(hour) * 3600 + int(minute) * 60 + float(second)


def caption_bounds(path: Path, duration: float) -> dict:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("WEBVTT\n"):
        raise ReviewError(f"Invalid WebVTT header: {path}")
    intervals = []
    for line in content.splitlines():
        if "-->" not in line:
            continue
        matched = CUE.fullmatch(line)
        if matched is None:
            raise ReviewError(f"Invalid caption interval in {path}: {line}")
        start, end = map(seconds, matched.groups())
        if start < 0 or end <= start or (intervals and start < intervals[-1][1] - 0.001):
            raise ReviewError(f"Caption intervals overlap or run backwards: {path}")
        if end > duration + 0.01:
            raise ReviewError(f"Caption ends at {end:.3f}s after video end {duration:.3f}s: {path}")
        intervals.append((start, end))
    if not intervals:
        raise ReviewError(f"No caption cues: {path}")
    return {"count": len(intervals), "start": intervals[0][0], "end": intervals[-1][1]}


def inspect_video(path: Path, provenance: dict) -> dict:
    import av

    try:
        with av.open(str(path)) as container:
            if len(container.streams.video) != 1:
                raise ReviewError(f"Expected one video stream: {path}")
            stream = container.streams.video[0]
            codec = stream.codec_context.name
            width, height = stream.codec_context.width, stream.codec_context.height
            fps = float(stream.average_rate or 0)
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / av.time_base
            else:
                raise ReviewError(f"Video duration is unavailable: {path}")
            audio_codecs = [audio.codec_context.name for audio in container.streams.audio]
    except (OSError, av.FFmpegError) as error:
        raise ReviewError(f"Cannot inspect video {path}: {error}") from error
    if codec != "h264":
        raise ReviewError(f"Expected H.264 video, found {codec}: {path}")
    quality = provenance.get("quality")
    if quality not in {"preview", "production"}:
        raise ReviewError(f"Unknown rendering quality {quality!r}: {path}")
    expected_dimensions = (854, 480) if quality == "preview" else (1920, 1080)
    expected_fps = 15 if quality == "preview" else 30
    if (width, height) != expected_dimensions:
        raise ReviewError(f"Expected {expected_dimensions}, found {(width, height)}: {path}")
    if not math.isclose(fps, expected_fps, abs_tol=0.01):
        raise ReviewError(f"Expected {expected_fps} fps, found {fps:.3f}: {path}")
    expected_duration = provenance.get("duration")
    if (
        not isinstance(expected_duration, (int, float))
        or not math.isfinite(expected_duration)
        or expected_duration <= 0
    ):
        raise ReviewError(f"Invalid provenance duration: {path}")
    if not math.isfinite(duration) or abs(duration - expected_duration) > 0.3:
        raise ReviewError(f"Video duration {duration:.3f}s differs from provenance {expected_duration:.3f}s: {path}")
    voice = provenance.get("voice")
    if voice not in {"files", "system", "silent"}:
        raise ReviewError(f"Unknown narration mode {voice!r}: {path}")
    if voice != "silent" and not audio_codecs:
        raise ReviewError(f"Narrated video has no audio stream: {path}")
    if audio_codecs and audio_codecs != ["aac"]:
        raise ReviewError(f"Expected one AAC narration stream, found {audio_codecs}: {path}")
    return {
        "video_codec": codec,
        "audio_codecs": audio_codecs,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": duration,
        "expected_duration": expected_duration,
    }


def inspect_package(root: Path, segment: dict) -> dict:
    segment_id = segment.get("id")
    if not isinstance(segment_id, str) or re.fullmatch(r"[a-z][a-z0-9-]*", segment_id) is None:
        raise ReviewError(f"Unsafe segment id: {segment_id!r}")
    folder = root / "dist" / segment_id
    if not folder.resolve().is_relative_to((root / "dist").resolve()):
        raise ReviewError(f"Package leaves the review directory: {folder}")
    required = [
        f"{segment_id}.mp4",
        "captions.srt",
        "captions.vtt",
        "chapters.txt",
        "youtube.txt",
        "transcript.md",
        "provenance.json",
    ]
    for name in required:
        if not (folder / name).is_file():
            raise ReviewError(f"Incomplete video package; missing {folder / name}")
    provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    if provenance.get("segment") != segment_id:
        raise ReviewError(f"Provenance identifies a different segment: {folder}")
    metadata = inspect_video(folder / f"{segment_id}.mp4", provenance)
    return {
        "id": segment_id,
        "title": segment["title"],
        "page": segment["page"],
        "voice": provenance["voice"],
        "quality": provenance["quality"],
        "source_version": provenance.get("target", {}).get("version", "unknown"),
        "source_state": provenance.get("target", {}).get("state", "committed"),
        **metadata,
        "captions": caption_bounds(folder / "captions.vtt", metadata["duration"]),
        "thumbnail_at": min(metadata["duration"] - 0.1, provenance.get("beats", [{}])[0].get("start", 2) + 3),
    }


def gallery(clips: list[dict], docs_base: str) -> str:
    cards = []
    for clip in clips:
        segment_id = clip["id"]
        title = html.escape(clip["title"])
        voice_label = {"files": "Recorded narration", "system": "System speech · review", "silent": "Silent · review"}[
            clip["voice"]
        ]
        source = html.escape(f"RelFlow {clip['source_version']} · {clip['source_state']}")
        duration = f"{int(clip['duration']) // 60}:{int(clip['duration']) % 60:02d}"
        docs_url = html.escape(docs_base.rstrip("/") + "/" + clip["page"].removesuffix(".qmd") + ".html", quote=True)
        cards.append(
            f"""<article id="{segment_id}">
  <h2>{title}</h2>
  <p class="meta">{source}<br>{voice_label} · {clip["height"]}p · {clip["fps"]:g} fps · {duration}</p>
  <video controls preload="metadata" poster="{segment_id}/thumbnail.jpg">
    <source src="{segment_id}/{segment_id}.mp4" type="video/mp4">
    <track kind="captions" src="{segment_id}/captions.vtt" srclang="en" label="English" default>
    Your browser does not support video playback. Use the MP4 link below.
  </video>
  <nav aria-label="{title} resources">
    <a href="{docs_url}">Documentation</a>
    <a href="{segment_id}/transcript.md">Transcript</a>
    <a href="{segment_id}/{segment_id}.mp4" download>MP4</a>
    <a href="{segment_id}/captions.vtt" download>Captions</a>
    <a href="{segment_id}/provenance.json">Provenance</a>
  </nav>
</article>"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RelFlow, Visualized — Video Review</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; background: #0e1117; color: #dce5ce; }}
    body {{ max-width: 1480px; margin: 0 auto; padding: 32px 24px 56px; }}
    header {{ max-width: 76ch; margin-bottom: 32px; }}
    h1 {{ font-size: clamp(2rem, 5vw, 3.2rem); letter-spacing: -.04em; margin-bottom: 12px; }}
    h2 {{ margin: 0; font-size: 1.3rem; }}
    p {{ line-height: 1.6; }}
    a {{ color: #7abbb1; text-underline-offset: 3px; }}
    .eyebrow, .meta {{ color: #a4b2aa; }}
    .eyebrow {{ text-transform: uppercase; font-size: .8rem; letter-spacing: .14em; }}
    main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap: 24px; }}
    article {{ min-width: 0; border: 1px solid #34443d; border-radius: 12px; padding: 22px; background: #182127; }}
    .meta {{ font-size: .9rem; margin: 10px 0 18px; }}
    video {{ width: 100%; display: block; aspect-ratio: 16/9; background: #0e1117; border-radius: 7px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 12px 20px; margin-top: 18px; font-size: .9rem; }}
    footer {{ color: #a4b2aa; margin-top: 36px; font-size: .9rem; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <header>
    <p class="eyebrow">relflow · local review</p>
    <h1>RelFlow, Visualized</h1>
    <p>{len(clips)} completed clips. Check narration, code readability, and caption synchronization before uploading.
    Captions follow proportional word timing within each recording and require review.</p>
    <p>Diagrams and example values are schematic. Source and voice labels identify each render.</p>
  </header>
  <main>{"".join(cards)}</main>
  <footer>
    <p>All media and gallery assets are local. Documentation links open the published guides.</p>
    <p>For caption playback, serve this folder locally:
    <code>python -m http.server 8000 --bind 127.0.0.1 --directory dist</code></p>
    <p><a href="review.json">Technical validation report</a></p>
  </footer>
</body>
</html>
"""


def review(root: Path = ROOT, *, create: bool = True) -> dict:
    series = json.loads((root / "series.json").read_text(encoding="utf-8"))
    clips = [inspect_package(root, segment) for segment in series["segments"]]
    report = {"schema": 1, "clips": clips, "duration_tolerance_seconds": 0.3, "caption_timing": "requires human review"}
    if create:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for clip in clips:
            folder = root / "dist" / clip["id"]
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(max(0, clip["thumbnail_at"])),
                    "-i",
                    str(folder / f"{clip['id']}.mp4"),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=640:-2",
                    "-q:v",
                    "3",
                    str(folder / "thumbnail.jpg"),
                ],
                check=True,
            )
        (root / "dist/review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (root / "dist/index.html").write_text(gallery(clips, series["docs_base"]), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Inspect packages without generating gallery or thumbnails"
    )
    args = parser.parse_args(argv)
    try:
        report = review(create=not args.check)
    except (ReviewError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Video review failed: {error}\n")
    for clip in report["clips"]:
        audio = "+AAC" if clip["audio_codecs"] else ""
        print(
            f"{clip['id']}: H264{audio}, {clip['width']}x{clip['height']}@{clip['fps']:g}, "
            f"{clip['duration']:.2f}s, {clip['captions']['count']} captions, {clip['voice']}"
        )
    if not args.check:
        print(f"Local gallery: {ROOT / 'dist/index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
