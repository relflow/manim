# RelFlow, Visualized

Independent Manim videos for the [RelFlow documentation](https://relflow.github.io/docs/).
The repository keeps animation sources, narration, captions, and publication
metadata together. A video build does not train a model, import RelFlow, or
download model weights. The docs render from their own checkout and consume only
exported static metadata and transcripts.

## The series

`series.json` owns nine new clips, each with four narrated beats:

| Clip | Documentation home |
| --- | --- |
| Your First Model | `getting-started.qmd` |
| Add Transaction History | `tutorials/transaction-history.qmd` |
| Binding Data | `core-concepts/binding-data.qmd` |
| Training And Checkpoints | `guides/lightning.qmd` |
| Prediction Output | `guides/prediction-output.qmd` |
| Model Tree | `core-concepts/model-tree.qmd` |
| Masking And Reconstruction | `core-concepts/dynamic-masking.qmd` |
| Learning Modes And Embeddings | `core-concepts/embeddings.qmd` |
| Pretraining And Fine-Tuning | `guides/pretraining.qmd` |

Start with one payment and a hidden dispute target, add earlier transaction
history, then prepare data, train, and predict. The later clips explain structure,
masking, embeddings, and optional pretraining. All records and visual outputs are
illustrations; they are not measured model performance.

The new scenes use native Manim and local assets. They are independent of the
external animation framework used by the historical film. `series.json` records
the RelFlow version, current source checkout commit, working-tree source hashes,
and the separate documentation contract commit. The working-tree marker matters:
the docs currently describe API changes beyond their pinned upstream contract.

## Set up and check

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). Install the platform libraries
listed in the [Manim installation guide](https://docs.manim.community/en/stable/installation.html),
then install the pinned Python environment:

```sh
uv sync --locked
make check
```

Static checks validate narration, manifests, source provenance, and export
behavior. They do not execute the archived experiments or import RelFlow. The
committed font and logo assets carry their original license notices. Bundled
Noto Sans and Noto Sans Mono keep body text and code consistent across platforms;
the RelFlow wordmark uses the bundled Libertinus font.

## Render and review

The default production path uses recorded narration. Supply four PCM WAV files
for each segment, in narration-beat order:

```text
audio/first-model/01.wav
audio/first-model/02.wav
audio/first-model/03.wav
audio/first-model/04.wav
```

Check the narration text in `series.json`, record those beats, and render:

```sh
uv run python -m tools.build first-model --quality production --voice files
uv run python -m tools.build all --quality production --voice files --audio-dir /path/to/audio
```

On macOS, system speech provides narration for review. Silent rendering supports
CI and visual timing checks:

```sh
uv run python -m tools.build first-model --quality preview --voice system
uv run python -m tools.build all --quality preview --voice silent
uv run python -m tools.build all --check
```

Use `--voice files` for the final recorded narration. Preview speech is useful
for checking wording and scene timing before recording. Each completed segment
has a self-contained output directory:

```text
dist/<id>/
  <id>.mp4
  captions.srt
  captions.vtt
  chapters.txt
  youtube.txt
  transcript.md
  provenance.json
```

Chapters follow the actual beat timing. Captions use proportional word timing
within each measured recording; they are not forced word alignment. Review text readability,
narration pronunciation, caption synchronization, and the complete beginning
and end before publication. `provenance.json` identifies the scene inputs and
voice mode so a review render remains distinguishable from a production recording.

Inspect the completed packages and generate an offline review gallery:

```sh
uv run python -m tools.review
uv run python -m tools.review --check
uv run python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:8000/` to review every completed clip with its captions,
transcript, and source labels. The gallery and media are local; documentation
links open the published guides. The review command checks H.264 video, AAC
narration, dimensions, frame rate, duration, and caption bounds, and records its
findings in `dist/review.json`. It also writes a thumbnail for each clip.

## Publish the docs catalog

The exporter combines the nine new clips with `archive-catalog.json`, preserving
the original historical narration. It writes a compact JSON catalog and static
Markdown transcripts into the standalone docs checkout:

```sh
uv run python -m tools.catalog --docs /path/to/docs
uv run python -m tools.catalog --docs /path/to/docs --check
```

The destination argument is the repository containing `docs/_quarto.yml`.
The `--check` form compares expected files without writing. The exporter updates
managed entries, rejects unsafe paths and invalid YouTube IDs, and preserves
unrelated files. It does not remove old transcripts automatically.

YouTube upload is a later publication step. Upload the reviewed MP4, apply the
prepared description and captions, then put its actual eleven-character video ID
in `series.json` or `archive-catalog.json`. Export again and run the docs checks.
The docs embed published IDs; entries with `youtube_id: null` retain readable
transcripts without displaying a fabricated player.

## Preserve the original film

`archive/relflow-0.2.3/` preserves the original 21 episode sources, recorded data,
script, assets, and licenses from the `feature/explainer-video` branch. Their
recorded results remain historical evidence for RelFlow 0.2.3. `archive-catalog.json`
maps their existing segment boundaries to documentation homes; these are separate
from the nine new primers.

The historical renderer requires a separate animation framework at commit
`6c22be4`. That framework is not bundled here, so reproducing the original film
requires restoring that exact dependency first. See [PROVENANCE.md](PROVENANCE.md)
for source commits, checksums, and reproduction limits. Never execute archived
`compute.py` while rendering or validating documentation; retain its recorded
results and provenance.

```sh
uv run python -m tools.archive --check
```

New animation work belongs in the native scenes and `series.json`. Keep the
archived originals unchanged.
