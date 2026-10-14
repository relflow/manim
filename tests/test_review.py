"""Exercise real container inspection and an offline gallery with a tiny fixture."""

import json
import subprocess

import imageio_ffmpeg
import pytest

from tools.review import ReviewError, review


def test_real_video_package_validation_and_offline_gallery(tmp_path):
    segment = {"id": "review-clip", "title": "Payment & prediction", "page": "getting-started.qmd"}
    (tmp_path / "series.json").write_text(
        json.dumps({"schema": 1, "docs_base": "https://relflow.github.io/docs/", "segments": [segment]})
    )
    folder = tmp_path / "dist/review-clip"
    folder.mkdir(parents=True)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=854x480:r=15:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            "2",
            str(folder / "review-clip.mp4"),
        ],
        check=True,
    )
    provenance = {
        "segment": "review-clip",
        "quality": "preview",
        "voice": "files",
        "duration": 2.0,
        "target": {"version": "0.2.4", "state": "working-tree"},
        "beats": [{"start": 0}],
    }
    (folder / "provenance.json").write_text(json.dumps(provenance))
    (folder / "captions.vtt").write_text("WEBVTT\n\n00:00:00.200 --> 00:00:01.800\nOne visible payment.\n")
    for name in ["captions.srt", "chapters.txt", "youtube.txt", "transcript.md"]:
        (folder / name).write_text("Fixture publication metadata.\n")
    report = review(tmp_path, create=False)
    clip = report["clips"][0]
    assert clip["video_codec"] == "h264"
    assert clip["audio_codecs"] == ["aac"]
    assert (clip["width"], clip["height"], clip["fps"]) == (854, 480, 15)
    assert clip["duration"] == 2
    assert clip["captions"] == {"count": 1, "start": 0.2, "end": 1.8}
    assert not (tmp_path / "dist/index.html").exists()
    review(tmp_path)
    gallery = (tmp_path / "dist/index.html").read_text()
    assert "Payment &amp; prediction" in gallery
    assert 'preload="metadata"' in gallery
    assert 'src="review-clip/captions.vtt"' in gallery
    assert "https://relflow.github.io/docs/getting-started.html" in gallery
    assert "Recorded narration" in gallery
    assert (folder / "thumbnail.jpg").read_bytes().startswith(b"\xff\xd8")
    assert json.loads((tmp_path / "dist/review.json").read_text()) == report
    provenance["duration"] = 4
    (folder / "provenance.json").write_text(json.dumps(provenance))
    with pytest.raises(ReviewError, match="differs from provenance"):
        review(tmp_path, create=False)
    provenance["duration"] = 2
    (folder / "provenance.json").write_text(json.dumps(provenance))
    (folder / "captions.vtt").write_text("WEBVTT\n\n00:00:00.200 --> 00:00:02.100\nToo late.\n")
    with pytest.raises(ReviewError, match="after video end"):
        review(tmp_path, create=False)
