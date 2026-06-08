## Why

The `2-framing-train` YOLOv11 beam detector was trained on synthetic framing data
and scores ~0.99 mAP on synthetic tiles, but fails on real TGCH structural framing
plans — a documented sim-to-real gap. Closing it requires **real, hand-annotated
framing tiles**, and there is no automated way to produce them today. A0 framing
plans rendered at 300 DPI are 60–140 MP rasters that cannot be annotated whole
(beams are too small on screen to bbox; downscaling to a ~1k YOLO input collapses
beam detail). Worse, the same building is drawn at two scales — **1:400 overall
sheets and 1:200 enlarged sheets** — so an identical physical beam appears at two
different pixel sizes, which the detector sees as two different objects.

## What Changes

- **New CLI `scripts/tile_framing.py`** — accepts a single PNG/JPG framing plan or a
  folder of them, slices each into overlapping square tiles, and white-pads edge
  tiles to a uniform square. **Every grid tile is kept** — blank tiles (margins,
  title blocks, whitespace) are retained on purpose as native YOLO negatives, which
  is especially valuable given how few source drawings exist.
- **Filename-driven scale detection** — the trailing sheet index sets the drawing's
  scale: `…-00` → overall **1:400**, `…-01 … -04` → enlarged **1:200**. (The literal
  `200` in `TGCH-TD-S-200-…` is the drawing-**series** number, not the scale — detection
  uses the trailing index, not a "contains 200" match.) A `--scale` flag overrides /
  serves as fallback for non-conforming names.
- **Scale normalization (size-invariant, shape-preserving)** — each drawing is
  resampled by its detected scale to ONE canonical ground resolution
  (**1:400 @ 300 DPI = 33.87 mm/px**) before tiling. 1:400 sheets pass through
  (factor 1.0); 1:200 sheets are downsampled 2× (factor 0.5). Result: a beam of a
  given physical size lands at the **same pixel footprint** in every tile regardless
  of source sheet scale — shape preserved by interpolation, size made constant for
  YOLO. This canonical GSD matches how `2-framing-train/generate_beam.py` renders
  synthetic data, aligning real ↔ synthetic.
- **Default tiling geometry = 1280 window, overlap = one structural grid bay
  (`--overlap-mm 8400` ≈ 248 px @ canonical, white 255 pad)** — the 1280 window pins
  to the tile-size invariant of `2-framing-train` (TILE=1280 / YOLO imgsz); the full-bay
  overlap guarantees a beam spanning a bay is never lost at a seam. All configurable.
- **New per-drawing `tile_index.json`** — records detected scale, resample factor,
  canonical mm/px, original + canonical dimensions, and each tile's offsets in both
  canonical and original-A0 pixel space, so annotations / predictions reproject back
  to full-resolution A0 coordinates.
- **`requirements.txt`** — add `Pillow>=10.0`. (PDF rasterization is out of scope;
  inputs are already raster PNG/JPG.)
- **New `docs/tiling.md`** — annotator handoff guide.

## Capabilities

### New Capabilities
- `framing-tiling`: Batch-slice large structural framing rasters into overlapping,
  uniform square tiles — detecting per-sheet scale from the filename and normalizing
  every drawing to one canonical ground resolution so beams are size-invariant for
  YOLO — keeping every tile (blanks included) and emitting a per-drawing coordinate
  index for downstream reprojection.

### Modified Capabilities
<!-- None. openspec/specs/ is empty; no existing spec behavior changes. -->

## Impact

- **New files only**: `scripts/tile_framing.py`, per-drawing `tile_index/<drawing-id>.tile_index.json`
  + `output/` tiles, `requirements.txt`, `.gitignore`, `README.md`, `docs/tiling.md`.
- **Explicitly unchanged**: the `2-framing-train` trained weights and training code;
  its `tiled_inference.py` geometry (TILE=1280) which this tool is kept consistent with.
- **Dependencies**: adds `Pillow>=10.0`. No new services.
- **Downstream**: tiles are uploaded to Roboflow for human beam annotation; the
  exported YOLOv11 dataset is used to retrain the framing detector and close the
  sim-to-real gap.
