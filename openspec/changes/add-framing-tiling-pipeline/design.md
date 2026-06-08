## Context

`2-tiling-framing` is greenfield (only `openspec/` and `.claude/`). The proven,
single-purpose `1-tilting-column/scripts/tile_floorplan.py` (Pillow-only;
`tile_grid`, `white_pad`, `collect_images`, `tile_image`) already solves the core
batch-tiling + per-drawing-index problem, and this tool adapts it for framing.

The downstream consumer is the `2-framing-train` YOLOv11 beam detector. It was
trained on synthetic data and scores ~0.99 mAP on synthetic tiles but fails on real
TGCH framing plans (documented sim-to-real gap). The fix needs real annotated beam
tiles. Two hard constraints shape the geometry:

- **Tile-size invariant.** `2-framing-train` tiles at `TILE = 1280` and trains/infers
  at that pixel scale, and its synthetic generator (`generate_beam.py`) renders A0
  canvases at **1:400 @ 300 DPI**. Tiles produced here must match both, or there is a
  train/inference geometry and object-size mismatch.
- **Two source scales.** The same building is drawn at 1:400 (overall, `…-00`) and
  1:200 (enlarged, `…-01..-04`). Untreated, an identical physical beam appears at 2×
  pixel size between the two, which the detector reads as two different objects.

The repos are separate and `2-framing-train` is not an importable package, so this
tool cannot import its helpers across the repo boundary.

## Goals / Non-Goals

**Goals:**
- A standalone, dependency-light CLI (`scripts/tile_framing.py`) that batch-tiles a
  folder of PNG/JPG framing plans with no interactive steps.
- Detect each drawing's scale from its filename and **normalize every drawing to one
  canonical ground resolution** so beams are size-invariant for YOLO (shape preserved).
- Tile geometry whose window (1280) + white pad match the tile-size invariant; overlap
  defaults to one structural grid bay (`--overlap-mm 8400`). All configurable.
- Keep every tile, including blanks, as native YOLO negatives (no filtering).
- A `tile_index.json` per drawing that is a faithful reprojection contract back to A0.

**Non-Goals:**
- Inference, detection, or reprojection *code* (only the index they will use).
- Any change to `2-framing-train` weights, training, or `tiled_inference.py`.
- Roboflow upload automation.
- PDF input / `pymupdf` rendering (inputs are already raster; deferred).
- Training-time data augmentation in the model trainer (this tool does deterministic
  scale normalization, not stochastic augmentation).

## Decisions

**1. Window 1280 + white pad pinned to the invariant.** `WINDOW_DEFAULT = 1280` and
`WHITE = 255` are defined locally with a comment pointing at `2-framing-train`'s
`TILE = 1280`. The window MUST equal the detector's `imgsz` so a beam's pixel size
matches training. *Alternative considered:* a smaller window — rejected (trains at a
geometry the 1280 pipeline never sees).

**2. Scale from the trailing sheet index, not a substring match.** Detect with a regex
on the filename stem's trailing `-NN` token: `-00` → 400 (overall), `-01..-04` → 200
(enlarged). The series number elsewhere (e.g. `-200-` in `TGCH-TD-S-200-…`) is
deliberately ignored. `--scale` overrides and is the fallback for non-conforming names;
if nothing yields a scale the CLI errors rather than guessing. *Alternative considered:*
a "contains 200/400" match — rejected because the series number `200` collides with the
1:200 scale token and would mis-scale every overall sheet.

**3. Canonical-GSD normalization is the size-invariance mechanism ("size augmentation
so shape is recorded, size unaffected").** Before tiling, resample the whole drawing to
a canonical ground resolution — default **1:400 @ 300 DPI ≈ 33.87 mm/px**
(`--canonical-scale 400`, `--dpi 300`). Resample factor = `detected_scale /
canonical_scale`: a 1:200 sheet → 0.5 (downsample 2×), a 1:400 sheet → 1.0 (pass
through). After this, every tile shares identical `mm/px`, identical physical coverage,
and a beam of fixed physical size has an identical pixel footprint everywhere — shape
preserved by interpolation, size made constant for YOLO. Canonical = 1:400 @ 300 DPI is
chosen to match `generate_beam.py`'s synthetic GSD, aligning real ↔ synthetic.
*Interpolation:* `LANCZOS` for downsampling (factor < 1) to retain thin beam edges;
no upsampling occurs at the default canonical scale. *Alternatives considered:*
(a) normalize to the finer 1:200 GSD — rejected (upsamples 1:400 sheets, inventing
detail and inflating tile counts ~4×, and diverges from synthetic GSD);
(b) skip normalization and rely on YOLO multi-scale augmentation — rejected (the
detector is calibrated to a fixed 1280 object scale; mixed scales reintroduce the exact
ambiguity this project exists to remove).

**4. Overlap = one structural grid bay via `--overlap-mm 8400`.** Converted to canonical
pixels with `px/mm = DPI/(25.4 · canonical_scale)` (≈ 248 px at the default). Because the
conversion uses the *canonical* scale, the pixel overlap is identical across overall and
enlarged sheets. A full-bay overlap guarantees a beam spanning a bay survives whole in a
neighbouring tile. `--overlap` (raw px) remains available and is mutually exclusive with
`--overlap-mm`; an overlap ≥ window errors rather than producing a non-positive step.

**5. Grid math mirrors `tile_grid`.** Step across `range(0, max(1, W - win), step)`,
append a final `max(0, W - win)` position if the last window misses the edge — same for
rows — operating on the *normalized* dimensions. Out-of-bounds regions are white-padded
via a `win × win` 255 canvas with the crop pasted at (0, 0) (avoids PIL's black crop pad;
guarantees uniform square output).

**6. Keep every tile — no blank-skip.** Emit all N×M grid tiles, never filter. Blanks are
native YOLO negatives and valuable given few source drawings; an annotator simply leaves
a blank tile unlabelled. *Alternative considered:* ink-ratio blank-skip — rejected (risks
discarding sparse-but-real beam tiles).

**7. Outputs split: images flat, index separate.** Tile images go flat into `<output>/`
as `<drawing-id>__r{row}_c{col}.png` (drawing-id prefix prevents cross-drawing
collisions); per-drawing `<drawing-id>.tile_index.json` go into a separate index dir
(default sibling `tile_index/`, `--index-dir` overridable) so `<output>/` stays
images-only and uploadable as-is. Per-drawing indexes accumulate safely across
incremental runs (no clobber); reprojection is per-drawing anyway.

**8. Extended index schema (reprojection across normalization).** Each index records
normalization metadata plus dual-space offsets so a tile-local box maps back to original
A0 pixels and to mm:
```json
{
  "image": "TGCH-TD-S-200-B1-01.png",
  "scale": 200, "dpi": 300,
  "canonical_scale": 400, "resample_factor": 0.5, "mm_per_px": 33.87,
  "orig_width": 9362, "orig_height": 6623,
  "canon_width": 4681, "canon_height": 3312,
  "window": 1280, "overlap": 248, "overlap_mm": 8400,
  "tiles": [
    { "filename": "TGCH-TD-S-200-B1-01__r0_c0.png",
      "x_offset": 0, "y_offset": 0,
      "x_offset_orig": 0, "y_offset_orig": 0,
      "width": 1280, "height": 1280 }
  ]
}
```
`x_offset_orig = round(x_offset / resample_factor)` (original-A0 pixels);
canonical offsets are top-left positions in the normalized image.

**9. CLI surface.**
`python3 scripts/tile_framing.py --input <file|dir> [--output output/]
[--index-dir tile_index/] [--window 1280] [--overlap-mm 8400 | --overlap PX]
[--dpi 300] [--canonical-scale 400] [--scale S] [--recursive]`. Print a per-image
`name: scale 1:S -> WxH (canon WxH) -> cols×rows = N tiles` line plus a total.
`Image.MAX_IMAGE_PIXELS = None` so large rasters open without the decompression-bomb
guard.

## Risks / Trade-offs

- **Filename without a recognizable trailing index** → CLI requires `--scale` and errors
  if absent; never silently assumes a scale.
- **Wrong scale → wrong object size for YOLO** → Detection rule is narrow (trailing
  `-NN` only) and recorded in the index for audit; `--scale` overrides per run.
- **Downsampling thins beam linework** → Use LANCZOS; canonical = 1:400 only downsamples
  the 1:200 sheets (factor 0.5), which still matches synthetic GSD; no upsampling.
- **Geometry drift from the invariant** → Window 1280 + white pad pinned and documented;
  overlap from the grid bay is documented; configurability is opt-in.
- **Edge-tile padding shifts content vs. a naive grid** → Offsets clamped and recorded
  exactly (both pixel spaces), so reprojection stays correct.
- **Large rasters → memory** → One drawing opened at a time; tiles cropped lazily.

## Migration Plan

Purely additive new files; nothing to roll back beyond deleting the new script and its
outputs. No data migration.

## Open Questions

- None blocking. If overall (`-00`) and enlarged (`-01..-04`) sheets ever adopt a
  different naming convention, the trailing-index regex (or `--scale`) absorbs it without
  changing the keep-all / normalization contracts.
