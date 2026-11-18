#!/usr/bin/env python3
"""Basic, non-destructive validator for a Compositor .comp project.

Usage:
  python3 validate_comp.py /path/to/Project.comp

Runs on the Python 3 standard library alone — any Python 3 version, no
third-party packages required. If Pillow happens to be installed, it is
used for deeper corruption checks, but it is entirely optional.

Checks: JSON syntax, basic manifest keys, canvas dimensions, duplicate
layer ids, image and mask asset existence, PNG signature and header
sanity, and the upstream naming rules (image files are named after their
layer id; masks are 8-bit grayscale). It does not validate all
Compositor-specific schema rules or render the document.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

# Pillow is optional; the standard-library checks below already cover the
# common failure modes (missing files, non-PNG data, broken headers).
try:
    from PIL import Image
except ImportError:
    Image = None

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# PNG color types: 0 grayscale, 2 RGB, 3 indexed, 4 grayscale+alpha, 6 RGBA
PNG_COLOR_NAMES = {0: "grayscale", 2: "RGB", 3: "indexed", 4: "grayscale+alpha", 6: "RGBA"}


def parse_png_header(data):
    """Return (width, height, bit_depth, color_type), or None if not a PNG.

    Reads only the mandatory leading IHDR chunk, so truncated files are
    still recognized as PNGs; deeper corruption is Pillow's job, if present.
    """
    if len(data) < 26 or not data.startswith(PNG_MAGIC):
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, bit_depth, color_type


def check_asset(project, filename, label, kind, errors, warnings):
    """Validate one image or mask asset referenced from the manifest."""
    asset = project / "images" / filename
    if not asset.is_file():
        errors.append("{}: missing {} asset {}".format(label, kind, asset))
        return

    try:
        blob = asset.read_bytes()
    except OSError as exc:
        errors.append("{}: unreadable {} file {}: {}".format(label, kind, asset.name, exc))
        return

    header = parse_png_header(blob)
    if header is None:
        errors.append("{}: {} asset is not a valid PNG: {}".format(label, kind, asset.name))
        return
    width, height, bit_depth, color_type = header
    if width <= 0 or height <= 0:
        errors.append("{}: {} asset has invalid dimensions {}x{}: {}".format(
            label, kind, width, height, asset.name))

    color = PNG_COLOR_NAMES.get(color_type, "unknown type {}".format(color_type))
    if kind == "mask":
        # Upstream: masks are 8-bit grayscale (white shows, black hides).
        if color_type != 0 or bit_depth != 8:
            warnings.append("{}: mask is {}-bit {}; upstream expects 8-bit grayscale: {}".format(
                label, bit_depth, color, asset.name))
    else:
        # Upstream: layer images are RGBA. Anything without an alpha channel
        # deserves a look, though Compositor may still load it.
        if color_type not in (4, 6):
            warnings.append("{}: image is {}-bit {} with no alpha channel: {}".format(
                label, bit_depth, color, asset.name))

    # Optional deeper check (truncated or corrupt pixel data) when Pillow
    # is available; skipped silently otherwise.
    if Image is not None:
        try:
            with Image.open(asset) as im:
                im.verify()
        except Exception as exc:
            errors.append("{}: corrupt {} PNG {}: {}".format(label, kind, asset.name, exc))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_comp.py /path/to/Project.comp", file=sys.stderr)
        return 2

    project = Path(sys.argv[1]).expanduser().resolve()
    manifest_path = project / "manifest.json"
    if not project.is_dir() or not manifest_path.is_file():
        print("ERROR: not a .comp project directory: {}".format(project))
        return 1

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("ERROR: cannot parse manifest.json: {}".format(exc))
        return 1

    errors = []
    warnings = []
    for key in ("format", "version", "documentID", "width", "height", "layers"):
        if key not in data:
            errors.append("Missing manifest key: {}".format(key))

    for name in ("width", "height"):
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            errors.append("Canvas {} must be a positive number, got {!r}".format(name, value))

    # Adaptivity check: warn when the project declares a format version
    # newer than the cached upstream documentation covers.
    version = data.get("version")
    meta_path = Path(__file__).resolve().parent.parent / "references" / "upstream" / "metadata.json"
    known = None
    try:
        known = json.loads(meta_path.read_text(encoding="utf-8")).get("max_version")
    except Exception:
        pass
    if (isinstance(version, int) and not isinstance(version, bool)
            and isinstance(known, int) and version > known):
        warnings.append("Project declares format version {}, newer than the cached upstream docs ({}); "
                        "run scripts/fetch_format_docs.py --auto to refresh".format(version, known))

    layers = data.get("layers", [])
    if not isinstance(layers, list):
        errors.append("Manifest 'layers' must be a list")
        layers = []

    seen = set()
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            errors.append("Layer {}: not a JSON object".format(index))
            continue
        lid = layer.get("id")
        label = "Layer {}".format(lid if lid else index)
        if not lid:
            errors.append("Layer {}: missing id".format(index))
        elif lid in seen:
            errors.append("Duplicate layer id: {}".format(lid))
        else:
            seen.add(lid)

        # Upstream hard rule: a layer's image file is named after its id,
        # and its mask after "<id>.mask.png", with the id spelled exactly
        # as in the manifest. Compositor silently refuses mismatches.
        image_file = layer.get("imageFile")
        if image_file:
            check_asset(project, image_file, label, "image", errors, warnings)
            if lid and image_file != "{}.png".format(lid):
                errors.append("{}: imageFile is {!r} but upstream names image files '<id>.png' ({})".format(
                    label, image_file, "{}.png".format(lid)))

        mask_file = layer.get("maskFile")
        if mask_file:
            check_asset(project, mask_file, label, "mask", errors, warnings)
            if lid and mask_file != "{}.mask.png".format(lid):
                errors.append("{}: maskFile is {!r} but upstream names mask files '<id>.mask.png' ({})".format(
                    label, mask_file, "{}.mask.png".format(lid)))

    for warning in warnings:
        print("WARNING: {}".format(warning))
    for error in errors:
        print("ERROR: {}".format(error))

    if errors:
        print("FAILED: {} error(s), {} warning(s)".format(len(errors), len(warnings)))
        return 1
    print("OK: {} layer(s), {} warning(s)".format(len(layers), len(warnings)))
    if Image is None:
        print("Note: running on the standard library alone; Pillow (optional) adds deeper corruption checks.")
    if known is None:
        print("Note: no cached upstream docs metadata; run scripts/fetch_format_docs.py --auto to create it.")
    print("Note: this is a basic structural check, not full Compositor schema validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
