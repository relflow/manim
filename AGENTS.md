# RelFlow animation guide

This repository owns the animation sources, narration, captions, and video
catalog for the standalone RelFlow docs. The docs build never invokes Manim or
imports this checkout. Export checked-in metadata and transcripts with
`python -m tools.catalog --docs /path/to/docs` after reviewing changes.

`series.json` owns the new docs sequence and each narration beat. Keep the
payment example and teaching order consistent with the docs. Field colors
retain their roles across scenes. Treat every diagram as a schematic; do not
invent measured model results.

The unmodified original 21 episodes and recorded data live under
`archive/relflow-0.2.3/`. They are historical evidence, not current benchmarks.
Preserve their source hashes and licenses. Never run `compute.py` as part of a
render or check. The archived renderer references a separate upstream framework;
read PROVENANCE.md before reproducing those historical scenes.

Use `make check`, `make preview`, and the build CLI for selected segments.
Production accepts per-beat WAV recordings; macOS system speech is available
for narrated review. No model weights are downloaded by a video build.

Record real YouTube IDs in series.json or archive-catalog.json only after
upload. Never fabricate publication IDs. Review uploads and playlist order
before making them public.
