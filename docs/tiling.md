# Framing tiling — annotator handoff guide

## What the tiles are

Each tile is a `1280×1280` PNG crop of a structural framing plan, ready to upload
to Roboflow for **beam** annotation. Tiles are written flat into `output/`, named
`<drawing-id>__r{row}_c{col}.png` (the `<drawing-id>` prefix keeps drawings from
colliding). Upload the whole `output/` folder as-is — it contains images only.

## Two things that are handled for you

1. **Scale is detected from the filename.** A sheet ending in `-00` is the overall
   plan (1:400); `-01 … -04` are enlarged partial plans (1:200).
2. **Every drawing is normalized to one canonical scale (1:400 @ 300 DPI).** So a
   beam looks the *same size* whether it came from an overall or an enlarged sheet.
   You annotate beams the same way on every tile — no need to think about scale.

## How to annotate

- Draw a tight bounding box around each beam visible in the tile.
- **Blank tiles are kept on purpose.** A tile that is all margin / title block /
  whitespace is a valid *negative* example — just leave it unlabelled and move on.
  Do not delete it.
- Tiles overlap by one structural grid bay, so a beam near a tile edge will appear
  whole in a neighbouring tile too — annotate it wherever you see it.

## The `tile_index.json` (engineers only — not used during annotation)

One `<drawing-id>.tile_index.json` per drawing is written into `tile_index/`. It is
the reprojection contract that maps a tile-local detection back to full-resolution
A0 coordinates. Annotators can ignore it.

```json
{
  "image": "TGCH-TD-S-200-B1-01.png",
  "scale": 200,                 // detected from filename
  "dpi": 300,
  "canonical_scale": 400,       // normalized to this
  "resample_factor": 0.5,       // orig_px * factor = canon_px
  "mm_per_px": 33.87,           // at canonical scale
  "orig_width": 9362, "orig_height": 6623,
  "canon_width": 4681, "canon_height": 3312,
  "window": 1280, "overlap": 248, "overlap_mm": 8400,
  "tiles": [
    {
      "filename": "TGCH-TD-S-200-B1-01__r0_c0.png",
      "x_offset": 0, "y_offset": 0,            // top-left in CANONICAL px
      "x_offset_orig": 0, "y_offset_orig": 0,  // = canonical / resample_factor (A0 px)
      "width": 1280, "height": 1280
    }
  ]
}
```

Reprojection: a box at tile-local `(tx, ty)` is at canonical
`(x_offset + tx, y_offset + ty)`, and at original-A0
`(x_offset_orig + tx / resample_factor, y_offset_orig + ty / resample_factor)`.
