#!/usr/bin/env python3
"""Tile structural FRAMING rasters into overlapping square tiles for annotation.

Accepts a single image file OR a directory of images (PNG/JPG) and slices each
into overlapping square tiles, white-padding edge tiles to a uniform square.

What makes this tool different from a plain tiler: framing sheets are drawn at
two scales -- overall plans at 1:400 (filename ``...-00``) and enlarged plans at
1:200 (filename ``...-01`` .. ``-04``). Left untreated, an identical physical
beam appears at 2x pixel size between the two, which the detector reads as two
different objects. So each drawing's scale is detected from its filename and the
drawing is **resampled to one canonical ground resolution** (1:400 @ 300 DPI,
~33.87 mm/px) before tiling. After normalization a beam of a given physical size
has the SAME pixel footprint in every tile -- size-invariant for YOLO, shape
preserved by interpolation. The canonical resolution matches the synthetic data
in ``2-framing-train/generate_beam.py``, aligning real <-> synthetic.

Geometry: the window (1280) and white (255) pad mirror the ``2-framing-train``
"tile-size invariant" -- the window MUST equal the model's ``imgsz=1280`` (TILE
in ``tiled_inference.py``). The overlap defaults to ONE structural grid bay
(``--overlap-mm 8400``), converted to canonical pixels so a beam spanning a full
bay is never split at a tile seam. Window and overlap stay configurable.

**Every grid tile is emitted -- nothing is ever dropped.** Blank tiles (margins,
title blocks, whitespace) are kept on purpose as native YOLO negatives, valuable
given how few source drawings exist. An annotator simply leaves them unlabelled.

All tiles are written flat into the output directory (the ``<drawing-id>__``
filename prefix prevents collisions). The per-drawing
``<drawing-id>.tile_index.json`` -- recording each tile's offsets in BOTH the
canonical and the original (A0) pixel space, plus the normalization metadata --
is written into a sibling ``tile_index/`` directory so the output folder stays
images-only and ready to upload. It is the reprojection contract: a downstream
detection at tile-local ``(tx, ty)`` maps to canonical ``(x_offset + tx,
y_offset + ty)`` and to original ``(x_offset_orig + tx/resample_factor, ...)``.
It is NOT used during annotation.

Usage:
    # a whole folder; scale auto-detected per sheet from the filename
    python3 scripts/tile_framing.py --input drawings/ --recursive
    # one sheet whose name has no -NN index: give the scale explicitly
    python3 scripts/tile_framing.py --input plan.png --scale 200
    # custom overlap in raw pixels instead of a grid bay
    python3 scripts/tile_framing.py --input plan.png --overlap 256
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

# Large A0 rasters (60-140 MP) exceed PIL's decompression-bomb guard; these are
# trusted local renders, so lift the cap so any size opens.
Image.MAX_IMAGE_PIXELS = None

# --- Geometry & scale (see module docstring) ---------------------------------
# WINDOW must equal the model's imgsz=1280 (the 2-framing-train TILE invariant).
# OVERLAP_MM defaults to one structural grid bay so a beam spanning a bay is
# never split at a seam. CANONICAL_SCALE is the 1:S all drawings are normalized
# to (matches generate_beam.py's 1:400 @ 300 DPI synthetic ground resolution).
WINDOW_DEFAULT = 1280
OVERLAP_MM_DEFAULT = 8400
CANONICAL_SCALE_DEFAULT = 400
DPI_DEFAULT = 300
WHITE = 255

# Filename trailing index -> drawing scale denominator. -00 is the overall plan
# (1:400); -01..-04 are enlarged partial plans (1:200). The series number
# elsewhere in the name (e.g. the 200 in TGCH-TD-S-200-...) is NOT a scale.
SCALE_BY_TRAILING_INDEX = {0: 400, 1: 200, 2: 200, 3: 200, 4: 200}
TRAILING_INDEX_RE = re.compile(r"-(\d{2})$")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def detect_scale(filename: str) -> int | None:
    """Scale denominator from the filename's trailing ``-NN`` index, else None.

    ``...-00`` -> 400 (overall), ``...-01`` .. ``-04`` -> 200 (enlarged). Any
    other / missing trailing index returns None so the caller can fall back to
    an explicit ``--scale`` rather than guessing.
    """
    m = TRAILING_INDEX_RE.search(Path(filename).stem)
    if not m:
        return None
    return SCALE_BY_TRAILING_INDEX.get(int(m.group(1)))


def resolve_scale(filename: str, override: float | None) -> float:
    """Effective scale for a drawing: ``--scale`` override wins, else detected.

    Raises ``ValueError`` when neither yields a scale, so the CLI errors instead
    of tiling at an assumed scale.
    """
    if override is not None:
        return override
    detected = detect_scale(filename)
    if detected is None:
        raise ValueError(
            f"cannot determine scale for '{filename}': no trailing -00/-01..-04 "
            f"index in the name; pass --scale (e.g. --scale 200)")
    return detected


def normalize(img: Image.Image, scale: float, canonical_scale: float
              ) -> tuple[Image.Image, float]:
    """Resample ``img`` to the canonical ground resolution; return (img, factor).

    ``resample_factor = scale / canonical_scale``: a 1:200 drawing downsamples by
    0.5 to reach 1:400; a 1:400 drawing passes through unchanged at factor 1.0.
    Shape (aspect ratio) is preserved; LANCZOS keeps thin beam edges crisp.
    """
    factor = scale / canonical_scale
    if factor == 1.0:
        return img, 1.0
    w, h = img.size
    return img.resize((round(w * factor), round(h * factor)), Image.LANCZOS), factor


def tile_grid(extent_w: int, extent_h: int, window: int, step: int
              ) -> tuple[list[int], list[int]]:
    """Row-major top-left tile origins, mirroring 2-framing-train tiling.

    Steps across the canvas at ``step``, then appends a final clamped origin at
    ``max(0, extent - window)`` so the right/bottom edge is always covered. For
    canvases smaller than ``window`` the single origin is 0 (the tile is later
    white-padded out to ``window``). Works for any extent >= 1.
    """
    xs = list(range(0, max(1, extent_w - window), step))
    if not xs or xs[-1] + window < extent_w:
        xs.append(max(0, extent_w - window))
    ys = list(range(0, max(1, extent_h - window), step))
    if not ys or ys[-1] + window < extent_h:
        ys.append(max(0, extent_h - window))
    return xs, ys


def white_pad(region: Image.Image, window: int) -> Image.Image:
    """Paste ``region`` top-left onto a white ``window``x``window`` RGB canvas.

    A no-op for full interior tiles; only edge tiles (and whole tiles from images
    smaller than the window) get padded. White (255) matches the paper
    background the detector is trained on -- PIL's default crop pad is black,
    which is out-of-distribution. Pads right/bottom only, so tile-local offsets
    still map straight onto the recorded ``(x_offset, y_offset)``.
    """
    if region.size == (window, window):
        return region
    w, h = region.size
    return ImageOps.expand(region, border=(0, 0, window - w, window - h),
                           fill=(WHITE, WHITE, WHITE))


def collect_images(input_path: Path, recursive: bool = False) -> list[Path]:
    """Resolve ``--input`` (a single image file OR a directory) to a sorted list."""
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in IMAGE_SUFFIXES else []
    walker = input_path.rglob("*") if recursive else input_path.iterdir()
    return sorted(q for q in walker
                  if q.is_file() and q.suffix.lower() in IMAGE_SUFFIXES)


def tile_image(image_path: Path, out_dir: Path, index_dir: Path, window: int,
               overlap: int, canonical_scale: float, dpi: int,
               overlap_mm: float | None, scale_override: float | None
               ) -> tuple[int, int, int, float, int, int]:
    """Tile one drawing flat into ``out_dir``. Returns (n, cols, rows, scale, W, H).

    Resolves the drawing's scale (filename or override), normalizes it to the
    canonical ground resolution, tiles the normalized image, and writes the
    extended per-drawing index. Every grid tile is written -- blanks kept.
    """
    drawing_id = image_path.stem
    scale = resolve_scale(image_path.name, scale_override)
    img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = img.size
    img, resample_factor = normalize(img, scale, canonical_scale)
    canon_w, canon_h = img.size

    step = window - overlap
    xs, ys = tile_grid(canon_w, canon_h, window, step)
    mm_per_px = round(25.4 * canonical_scale / dpi, 2)

    tiles_meta: list[dict] = []
    for row, y0 in enumerate(ys):
        for col, x0 in enumerate(xs):
            x1 = min(x0 + window, canon_w)
            y1 = min(y0 + window, canon_h)
            region = img.crop((x0, y0, x1, y1))
            filename = f"{drawing_id}__r{row}_c{col}.png"
            white_pad(region, window).save(out_dir / filename)
            tiles_meta.append({
                "filename": filename,
                "x_offset": x0,
                "y_offset": y0,
                "x_offset_orig": round(x0 / resample_factor),
                "y_offset_orig": round(y0 / resample_factor),
                "width": x1 - x0,
                "height": y1 - y0,
            })

    index = {
        "image": image_path.name,
        "scale": scale,
        "dpi": dpi,
        "canonical_scale": canonical_scale,
        "resample_factor": resample_factor,
        "mm_per_px": mm_per_px,
        "orig_width": orig_w,
        "orig_height": orig_h,
        "canon_width": canon_w,
        "canon_height": canon_h,
        "window": window,
        "overlap": overlap,
        "overlap_mm": overlap_mm,
        "tiles": tiles_meta,
    }
    (index_dir / f"{drawing_id}.tile_index.json").write_text(json.dumps(index, indent=2))
    return len(tiles_meta), len(xs), len(ys), scale, canon_w, canon_h


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, type=Path,
                   help="Image file OR directory of PNG/JPG framing plans (any size).")
    p.add_argument("--output", type=Path, default=Path("output"),
                   help="Directory for the tile images, ready to upload (default: output/).")
    p.add_argument("--index-dir", type=Path, default=None,
                   help="Directory for the <id>.tile_index.json files "
                        "(default: a 'tile_index/' folder beside --output).")
    p.add_argument("--window", type=int, default=WINDOW_DEFAULT,
                   help=f"Square tile size in px (default {WINDOW_DEFAULT}).")
    overlap_grp = p.add_mutually_exclusive_group()
    overlap_grp.add_argument("--overlap-mm", type=float, default=OVERLAP_MM_DEFAULT,
                   help=f"Overlap in millimetres -- one structural grid bay "
                        f"(default {OVERLAP_MM_DEFAULT}); converted at --canonical-scale.")
    overlap_grp.add_argument("--overlap", type=int, default=None,
                   help="Overlap between adjacent tiles in raw px, instead of --overlap-mm.")
    p.add_argument("--dpi", type=int, default=DPI_DEFAULT,
                   help=f"Render DPI of the input images (default {DPI_DEFAULT}).")
    p.add_argument("--canonical-scale", type=float, default=CANONICAL_SCALE_DEFAULT,
                   help=f"Scale denominator all drawings are normalized to "
                        f"(default {CANONICAL_SCALE_DEFAULT}, i.e. 1:400).")
    p.add_argument("--scale", type=float, default=None,
                   help="Override/fallback scale denominator S (1:S) when the "
                        "filename has no -00/-01..-04 trailing index.")
    p.add_argument("--recursive", action="store_true",
                   help="When --input is a directory, also search subfolders.")
    args = p.parse_args(argv)

    if args.window <= 0:
        p.error("--window must be positive")
    if args.canonical_scale <= 0:
        p.error("--canonical-scale must be > 0")
    if not args.input.exists():
        p.error(f"--input does not exist: {args.input}")

    # Resolve the overlap in canonical pixels. --overlap-mm (a grid bay) is
    # converted at the CANONICAL scale via px/mm = DPI / (25.4 * canonical_scale)
    # so the pixel overlap is identical across overall and enlarged sheets.
    if args.overlap is not None:
        overlap = args.overlap
        overlap_mm = None
        overlap_desc = f"{overlap}px"
    else:
        overlap = round(args.overlap_mm * args.dpi / (25.4 * args.canonical_scale))
        overlap_mm = args.overlap_mm
        overlap_desc = (f"{overlap}px (={args.overlap_mm:g}mm @ {args.dpi}dpi, "
                        f"1:{args.canonical_scale:g})")
    if not (0 <= overlap < args.window):
        p.error(f"resolved overlap must be >=0 and < --window ({args.window}); "
                f"got {overlap}px — lower --overlap-mm/--overlap")

    images = collect_images(args.input, args.recursive)
    if not images:
        print(f"No PNG/JPG images found at {args.input}", file=sys.stderr)
        return 1

    step = args.window - overlap
    index_dir = args.index_dir or (args.output.parent / "tile_index")
    args.output.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    print(f"Tiling {len(images)} image(s) -> tiles in {args.output}, "
          f"index in {index_dir} "
          f"(window={args.window} overlap={overlap_desc} step={step}; "
          f"normalized to 1:{args.canonical_scale:g}; keeping every tile)")

    total = 0
    try:
        for image_path in images:
            n, cols, rows, scale, cw, ch = tile_image(
                image_path, args.output, index_dir, args.window, overlap,
                args.canonical_scale, args.dpi, overlap_mm, args.scale)
            print(f"  {image_path.name}: 1:{scale:g} -> {cw}x{ch} canon "
                  f"-> {cols}x{rows} grid = {n} tiles")
            total += n
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Done: {total} tiles written across {len(images)} image(s) "
          f"(no tiles dropped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
