# Source and recording provenance

The primary animation archive is the original **21-episode** `relflow,
Visualized` series. Its sources, narration, production notes, episode metadata,
font, logo, and recorded JSON results are preserved unchanged under
[`archive/relflow-0.2.3/`](archive/relflow-0.2.3/).

The archive was extracted from
[`relflow/relflow`, branch `feature/explainer-video`, commit
`4679d69d9bf15cad1467803c68c3d7f5ecae3cec`](https://github.com/relflow/relflow/tree/4679d69d9bf15cad1467803c68c3d7f5ecae3cec/explainer-video).
The upstream folder is `explainer-video/`. The original recording notes identify
the experiment baseline as **RelFlow 0.2.3, commit `5077716`, Apple M1**. These
are the original authors' recorded provenance, not a new execution or a claim
about present-day performance. No experiment was rerun during this migration.

[`archive/checksums.sha256`](archive/checksums.sha256) fingerprints every original
archived file and separately retained root `LICENSE`, `NOTICE`, and `assets/`
files. Verify those fingerprints and the derived metadata with:

```bash
python -m tools.archive --check
```

`tools.archive` parses the manifest's literal episode definitions and committed
`SCRIPT.md`; it does not import scenes, import RelFlow, or execute `compute.py`.
`archive-catalog.json` is the publication catalog derived from those sources.
It retains all 21 scene boundaries and transcripts, marks them `historical`,
and starts with no YouTube publication IDs. The original `pretraining` slug is
retained as `original_slug`; its publication ID is `legacy-pretraining` to
distinguish it from the new primer.

## Reproducing the historical render

The archived scenes are not a standalone Manim application. They import
`explainer` and `videos.relflow`, and their production notes require the separate
[`Sir-Teo/explainer-videos`](https://github.com/Sir-Teo/explainer-videos)
framework at commit `6c22be4`. That framework supplied styles, `VoiceoverScene`,
Kokoro narration, music, and the build/publishing tools.

That referenced commit could not be resolved in the available upstream refs
during this migration. No framework license was available in the inspected
checkout. Its code has therefore not been copied here, and this repository does
not claim to independently reproduce the archived render. The archived commands
remain an unmodified historical record. Obtain the original rendered episodes,
or locate the exact framework revision and its license, before promising a
re-render of those scenes. The original experiment results remain intact in
either case.

The separate nine-part primer in `series.json` uses native Manim scenes in
`scenes.py`. Its build is independent of the historical framework and does not
run the archived experiments. All new diagrams are schematics, with no invented
measurements.

## Licenses

The extracted RelFlow repository's Apache 2.0 `LICENSE` and `NOTICE` are retained
at the repository root. The Libertinus font retains its SIL Open Font License
in both the unmodified archive and the root assets. This attribution does not
establish a license for the unavailable external framework.

## Documentation version boundary

The docs contract records RelFlow 0.2.4 at commit
`8d9d6cfd8ce22a7819c2b5392c710d4f2cbe1a7c`. Read-only inspection of that exact
source found a mismatch with newer documentation requirements: that commit has
fixed branch lengths with default `1`, retains configured fit optimizers, and
performs whole-input direct prediction. The current docs describe automatic
branch widths, a fresh optimizer per fit, and optional direct prediction
batching. The contract has not been silently advanced during the migration.
`series.json` records the separate working-tree target for the primer; it is
not a released or clean-checkout compatibility certification.

The historical videos remain labeled 0.2.3. New mechanism pages explain locally
verified, stable interactions with pinned source links, while keeping archived
measurements attached to their original version.

## Later revisions

- Resolve the docs contract against the intended released source before
  certifying the new primer's API examples for that release.
- Review training, branch geometry, normalization, and direct prediction in any
  revised original narration; preserve the historical recordings and data.
- Recover the original episode files or the exact licensed rendering framework.
- Review title cards, captions, and transcript accuracy against the actual video
  files before upload. Store real YouTube IDs only after upload.
- Measure new experiments explicitly when updated evidence is needed, retaining
  the source version, inputs, original results, and execution provenance.
