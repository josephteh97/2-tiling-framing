# framing-tiling Specification

## Purpose

Defines the framing tiling CLI that slices large structural framing (beam)
drawings into overlapping square tiles ready for upload and human annotation in
Roboflow. It detects each sheet's scale from its filename and normalizes every
drawing to one canonical ground resolution so a beam of a given physical size is
the same pixel size in every tile (size-invariant for YOLO, shape preserved),
emitting an images-only output folder plus a per-drawing tile index that lets
downstream inference re-project tile-local detections back to original-image (A0)
coordinates.

## Requirements

### Requirement: Batch input tiling (file or directory)

The CLI SHALL accept either a single image file or a directory as `--input` and
tile every PNG/JPG it resolves, writing all tile **images** flat into `<output>/`
and one `<drawing-id>.tile_index.json` per drawing into a separate index directory
(by default a sibling `tile_index/` directory next to `<output>/`; overridable with
`--index-dir`) so the output folder stays images-only and ready to upload. No index
file is written into `<output>/`. When `--input` is a directory the CLI SHALL tile
every image in it, optionally recursing into subfolders when `--recursive` is given.
The `<drawing-id>` SHALL be the source image filename stem, and every tile filename
SHALL be prefixed with it so drawings do not collide in the shared output folder.

#### Scenario: Tiling a single image file

- **WHEN** the user runs `tile_framing.py --input <plan>.png`
- **THEN** that one drawing is tiled into `output/` (the default) and its
  `<drawing-id>.tile_index.json` is written into the sibling `tile_index/`
  directory, and the process completes with no prompts

#### Scenario: Tiling a folder of drawings

- **WHEN** the user runs `tile_framing.py --input <dir> --output <out>` and `<dir>`
  contains one or more PNG/JPG files
- **THEN** all tile images are written directly into `<out>/` (no per-drawing
  subfolder), each prefixed with its `<drawing-id>`, while one
  `<drawing-id>.tile_index.json` per image is written into the separate index
  directory, and the process completes with no interactive prompts

#### Scenario: Output folder is images-only

- **WHEN** tiling completes
- **THEN** `<output>/` contains only tile image files (no `.json`), so it can be
  uploaded to Roboflow as-is

#### Scenario: Non-image files ignored

- **WHEN** the input directory also contains non-image files (e.g. `.txt`, `.json`)
- **THEN** those files are skipped and only PNG/JPG images are tiled

### Requirement: Filename-driven scale detection

The CLI SHALL determine each drawing's drawing scale from its filename so the
overlap-in-millimetres conversion and the canonical normalization use the correct
scale. The trailing sheet index of the filename stem SHALL select the scale: a
trailing `-00` index denotes an overall plan at **1:400**, and a trailing `-01`
through `-04` index denotes an enlarged plan at **1:200**. The literal series number
elsewhere in the name (e.g. the `200` in `TGCH-TD-S-200-…`) SHALL NOT be treated as
a scale. A `--scale` flag SHALL override detection and SHALL serve as the fallback
when a filename has no recognizable trailing index; if neither detection nor
`--scale` yields a scale the CLI SHALL error rather than guess.

#### Scenario: Overall sheet detected as 1:400

- **WHEN** a drawing named `TGCH-TD-S-200-B1-00.png` is tiled
- **THEN** its scale is detected as 400 and recorded as `scale: 400` in its index

#### Scenario: Enlarged sheet detected as 1:200

- **WHEN** a drawing named `TGCH-TD-S-200-B1-03.png` is tiled
- **THEN** its scale is detected as 200 and recorded as `scale: 200` in its index

#### Scenario: Series number is not mistaken for scale

- **WHEN** a drawing whose name contains `-200-` but ends in `-00` is tiled
- **THEN** the scale is detected as 400 (from the trailing `-00`), not 200

#### Scenario: Explicit override and fallback

- **WHEN** the user passes `--scale 200` for a drawing, or the filename has no
  recognizable trailing index
- **THEN** the supplied `--scale` is used; and when no scale can be determined at
  all the CLI errors instead of tiling at an assumed scale

### Requirement: Canonical ground-resolution normalization

The CLI SHALL resample each drawing from its detected scale to one canonical ground
resolution before tiling, so that a structural element of a given physical size
occupies the same number of pixels in every emitted tile regardless of the source
sheet's scale. The canonical resolution SHALL default to 1:400 at the configured DPI
(`--canonical-scale 400`, `--dpi 300`, i.e. ≈ 33.87 mm/px) and SHALL be configurable.
The resample factor SHALL be `detected_scale / canonical_scale`, applied to the pixel
dimensions (a 1:200 drawing is downsampled by 0.5 to reach 1:400; a 1:400 drawing
passes through at factor 1.0). Resampling SHALL preserve shape
(aspect ratio and geometry) using high-quality interpolation. All tiling geometry and
recorded offsets SHALL operate in this canonical pixel space, while the index SHALL
also record the mapping back to original pixels.

#### Scenario: Enlarged sheet downsampled to canonical

- **WHEN** a 1:200 drawing is tiled with the default canonical scale 400
- **THEN** the drawing is resampled by a factor of 0.5 before tiling, its index
  records `resample_factor: 0.5` and `canonical_scale: 400`, and its `mm_per_px`
  matches that of a 1:400 drawing

#### Scenario: Overall sheet passes through

- **WHEN** a 1:400 drawing is tiled with the default canonical scale 400
- **THEN** the resample factor is 1.0 and the drawing is tiled at its native pixels

#### Scenario: Size invariance across scales

- **WHEN** the same physical beam appears on a 1:400 overall sheet and on a 1:200
  enlarged sheet of the same building
- **THEN** after normalization that beam spans approximately the same number of
  pixels in the tiles produced from each sheet

### Requirement: Overlapping square tiling geometry

The CLI SHALL slice each normalized image into square tiles using a configurable
window size (default 1280 px) and an overlap that defaults to one structural grid bay
expressed in millimetres (`--overlap-mm 8400`). The window default matches the
detector's `imgsz=1280` tile-size invariant used by `2-framing-train`. The overlap in
millimetres SHALL be converted to canonical pixels via `px/mm = DPI/(25.4 ·
canonical_scale)` so that a beam spanning a full grid bay is never split across a tile
seam; `--overlap` (raw pixels) MAY be used instead and is mutually exclusive with
`--overlap-mm`. Tiles SHALL be generated on a deterministic row-major grid. Window
positions at the right and bottom edge SHALL be clamped so the window stays within the
image, and any region of a tile extending beyond the image SHALL be padded with white
(value 255) so every emitted tile is exactly window × window pixels.

#### Scenario: Default geometry from grid bay

- **WHEN** the user runs the CLI without `--window`, `--overlap`, or `--overlap-mm`
- **THEN** tiles are 1280×1280 with an overlap of 8400 mm converted at the canonical
  scale (≈ 248 px at 1:400 @ 300 DPI)

#### Scenario: Overlap in millimetres uses canonical scale

- **WHEN** drawings of different source scales are tiled with `--overlap-mm 8400`
- **THEN** every drawing's overlap is computed at the canonical scale, so the overlap
  in pixels is identical across overall and enlarged sheets

#### Scenario: Edge tiles are white-padded to full size

- **WHEN** the (normalized) image dimensions are not an exact multiple of the grid step
- **THEN** edge tiles are still exactly window × window pixels, with the out-of-bounds
  region filled white (255) rather than black or cropped

#### Scenario: Adapts to any normalized size

- **WHEN** the normalized image is smaller than, equal to, or larger than the window
- **THEN** a larger image yields an overlapping grid and an image equal to or smaller
  than the window yields a single white-padded window × window tile, with no error

### Requirement: Complete tile coverage (no dropping)

The CLI SHALL emit every tile of the grid for each drawing and SHALL NOT drop or
filter any tile. Blank tiles (margins, title blocks, whitespace) SHALL be retained,
because they are native negative examples for YOLO training and the source-drawing
count is small; discarding them would reduce dataset size and remove valuable
negatives. The run SHALL report the number of tiles written.

#### Scenario: Blank tiles are kept as negatives

- **WHEN** a tile lies in a drawing margin or title-block whitespace and contains
  little or no linework
- **THEN** that tile is still written to disk and recorded in `tile_index.json` so it
  is available as a negative training example

#### Scenario: Tile count equals the grid

- **WHEN** a drawing produces an N×M tile grid
- **THEN** exactly N×M tiles are written and recorded in `tile_index.json`, with no
  tile omitted on account of being blank

### Requirement: Per-drawing tile index

The CLI SHALL write one `<drawing-id>.tile_index.json` per drawing (flat in the
separate index directory, apart from the images) recording the source metadata
(`image`, `scale`, `dpi`, `canonical_scale`, `resample_factor`, `mm_per_px`, original
`orig_width`/`orig_height`, canonical `canon_width`/`canon_height`, `window`,
`overlap`, `overlap_mm`) and, for every emitted tile, its `filename`, canonical
`x_offset`/`y_offset`, original-pixel `x_offset_orig`/`y_offset_orig`, `width`, and
`height`. The tile `filename` SHALL be the tile's basename within `<output>/`.
Canonical offsets SHALL be the top-left position of the tile window in the normalized
image; original offsets SHALL be the canonical offsets divided by the resample factor.
This file is the contract for re-projecting downstream tile-local detections back to
full-resolution A0 coordinates.

#### Scenario: Index records both pixel spaces

- **WHEN** tiling completes for a drawing
- **THEN** `tile_index.json` exists and lists every written tile with integer
  canonical offsets, the original-pixel offsets, and the source/normalization
  metadata needed to map a tile box back to original A0 coordinates

#### Scenario: Offsets verifiable by re-compositing

- **WHEN** each tile is pasted onto a blank canvas of the canonical dimensions at its
  recorded canonical `(x_offset, y_offset)`
- **THEN** the recorded offsets place tiles consistently within the normalized image
  bounds, covering the inked regions of the drawing

### Requirement: Downstream annotation target (intent)

Tiles produced by this pipeline SHALL be intended for upload to Roboflow for human
annotation of structural framing (beams), and the resulting exported dataset
(YOLOv11 format) is training input used to retrain the `2-framing-train` beam detector
and close its sim-to-real gap. This requirement documents intent and SHALL NOT be
enforced by the CLI itself; `tile_index.json` is not used during annotation and is
reserved for the inference runner to re-project predicted boxes back to A0 coordinates.

#### Scenario: Tiles are annotation-ready

- **WHEN** the engineer opens the produced tiles in Roboflow
- **THEN** an annotator with no engineering background can draw accurate bounding
  boxes on beams without assistance, because each tile shows linework at a consistent,
  full-resolution canonical scale
