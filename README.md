# 2-tiling-framing

Annotation-prep tiler for **structural framing (beam) drawings**. It slices large
A0 framing rasters into overlapping `1280×1280` tiles for hand-annotation in
Roboflow, then emits a per-drawing index so annotations / predictions can be
re-projected back to full-resolution A0 coordinates.

It exists to produce **real annotated framing data** to close the sim-to-real gap
in the `2-framing-train` YOLOv11 beam detector (which scores ~0.99 mAP on synthetic
tiles but fails on real plans).

## What it does

- **Detects each sheet's scale from its filename.** Trailing `-00` = overall plan
  at 1:400; `-01 … -04` = enlarged plans at 1:200. (The `200` in `TGCH-TD-S-200-…`
  is the drawing *series* number, not a scale.) `--scale` overrides / is the
  fallback for non-conforming names.
- **Normalizes every drawing to one canonical ground resolution** (1:400 @ 300 DPI
  ≈ 33.87 mm/px) before tiling, so a beam of a given physical size has the same
  pixel size in every tile — size-invariant for YOLO, shape preserved. Matches the
  synthetic ground resolution in `2-framing-train/generate_beam.py`.
- **Tiles at window 1280** (the `2-framing-train` TILE invariant) with overlap =
  one structural grid bay (`--overlap-mm 8400`), so a beam spanning a bay is never
  split at a seam.
- **Keeps every tile** including blanks (native YOLO negatives); white-pads edge
  tiles to a uniform square.

## Usage

```bash
pip install -r requirements.txt

# a whole folder; scale auto-detected per sheet from the filename
python3 scripts/tile_framing.py --input ~/Documents/PDF-TGCH-Floor-Plan-All --recursive

# one sheet whose name has no -NN index: give the scale explicitly
python3 scripts/tile_framing.py --input plan.png --scale 200
```

Tile images land flat in `output/` (upload this folder to Roboflow as-is); the
per-drawing `<id>.tile_index.json` files land in `tile_index/`. See
[`docs/tiling.md`](docs/tiling.md) for the annotator handoff guide and the index
schema.
