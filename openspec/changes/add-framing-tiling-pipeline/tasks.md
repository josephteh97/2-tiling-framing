## 1. Project setup

- [x] 1.1 Create `requirements.txt` with `Pillow>=10.0`.
- [x] 1.2 Create `.gitignore` (`output/`, `tile_index/`, `__pycache__/`, `.DS_Store`).
- [x] 1.3 Scaffold `scripts/tile_framing.py` with module docstring (reference the
      `2-framing-train` `TILE = 1280` tile-size invariant and 1:400 @ 300 DPI synthetic
      GSD) and `Image.MAX_IMAGE_PIXELS = None`.
- [x] 1.4 Define local constants `WINDOW_DEFAULT = 1280`, `OVERLAP_MM_DEFAULT = 8400`
      (one grid bay), `CANONICAL_SCALE_DEFAULT = 400`, `DPI_DEFAULT = 300`, `WHITE = 255`.

## 2. CLI surface

- [x] 2.1 Add argparse: `--input` (file or dir), `--output` (default `output/`),
      `--index-dir` (default sibling `tile_index/`), `--window`, `--overlap` (px) and
      `--overlap-mm` (mutually exclusive), `--dpi`, `--canonical-scale`, `--scale`
      (override/fallback), `--recursive`.
- [x] 2.2 Validate the resolved overlap is `0 ≤ overlap < window`; error otherwise.

## 3. Scale detection & normalization

- [x] 3.1 Implement `detect_scale(filename)` — regex on the trailing `-NN` index:
      `-00` → 400, `-01..-04` → 200; ignore the series number; return None if no match.
- [x] 3.2 Resolve effective scale: `detect_scale` result, else `--scale`; error if
      neither yields a scale.
- [x] 3.3 Implement `normalize(image, scale, canonical_scale)` — compute
      `resample_factor = scale / canonical_scale`, resize (LANCZOS) to canonical pixels,
      return normalized image + factor; factor 1.0 passes through unchanged.

## 4. Tiling geometry

- [x] 4.1 Implement `tile_grid(W, H, window, step)` (row-major positions, append clamped
      `max(0, W-window)` edge position), operating on normalized dimensions.
- [x] 4.2 Implement white-pad crop: paste the (possibly smaller) crop onto a
      `window×window` 255-filled canvas so every tile is exactly window square.
- [x] 4.3 Convert `--overlap-mm` to canonical px via `px/mm = DPI/(25.4·canonical_scale)`.

## 5. Keep every tile (native negatives)

- [x] 5.1 Emit every grid tile; never drop or filter — blank tiles are kept as native
      YOLO negative examples.

## 6. Outputs

- [x] 6.1 Write tile images flat as `<output>/<drawing-id>__r{row}_c{col}.png`
      (no per-drawing subfolder; the prefix prevents collisions).
- [x] 6.2 Build and write `<index-dir>/<drawing-id>.tile_index.json` per drawing with the
      extended schema: source/normalization metadata (`image`, `scale`, `dpi`,
      `canonical_scale`, `resample_factor`, `mm_per_px`, `orig_width`/`orig_height`,
      `canon_width`/`canon_height`, `window`, `overlap`, `overlap_mm`) and per-tile
      `filename`, `x_offset`/`y_offset` (canonical), `x_offset_orig`/`y_offset_orig`
      (= canonical / resample_factor), `width`, `height`.

## 7. Batch driver

- [x] 7.1 Resolve `--input` as a single image file or a directory (optionally
      `--recursive`), tile every PNG/JPG, derive `<drawing-id>` from the filename stem,
      skipping non-image files.
- [x] 7.2 Print per-drawing summary (`name: scale 1:S -> WxH (canon WxH) -> cols×rows = N
      tiles`) and a total; report zero tiles dropped.

## 8. Docs & verification

- [x] 8.1 Write `README.md` and `docs/tiling.md` annotator handoff guide (what tiles are,
      filename→scale rule, that drawings are normalized to a canonical scale so beams are
      size-consistent, how to upload to Roboflow, that blank tiles are kept as negatives,
      that `tile_index.json` is not used during annotation).
- [x] 8.2 Run on `~/Documents/PDF-TGCH-Floor-Plan-All`; confirm tiles + per-drawing
      `tile_index.json` are produced with no prompts and zero tiles dropped.
- [x] 8.3 Verify scale detection: a `-00` sheet → `scale:400, resample_factor:1.0`; a
      `-01` sheet → `scale:200, resample_factor:0.5`; both report `mm_per_px ≈ 33.87` and
      `overlap ≈ 248`.
- [x] 8.4 Size-invariance spot check: confirm the same physical beam spans ~the same
      pixel count in a `-00` tile and a `-01` tile.
- [x] 8.5 Re-composite check: paste tiles back at recorded canonical offsets onto a blank
      canvas of canonical dimensions and confirm offsets reconstruct the normalized drawing.
