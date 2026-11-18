#!/usr/bin/env python3
"""comp_png.py — zero-dependency PNG asset generator and .comp preview compositor.

Standard library only; runs on any Python 3. Two jobs:

1. Generate layer and mask assets for .comp projects without writing
   throwaway image scripts:

     python3 scripts/comp_png.py gradient --size 1920x1080 --dir v \
         --from "#10143A" --to "#7A3E8C" --out images/<id>.png
     python3 scripts/comp_png.py mask --size 300x300 --from 255 --to 60 \
         --dir h --out images/<id>.mask.png

   Commands: solid, gradient, ellipse, rect, dots (RGBA layer pixels)
   and mask (8-bit grayscale, white shows). Colors: #RGB, #RRGGBB,
   #RRGGBBAA or a few common names.

2. Composite a .comp project bottom-to-top into a preview PNG so visual
   verification is always possible, even without Pillow or the app open:

     python3 scripts/comp_png.py preview Project.comp --out preview.png

   The compositor applies transforms (origin, size, clockwise rotation,
   flips), visibility, opacity, every documented blend mode, raster masks
   (linked and unlinked), groups (folder opacity and masks pass down,
   blend modes stay pass-through) and clipping masks (maskSourceID).
   EXR layers, adjustment layers, layer effects and GIF animation are
   not rendered — each is reported on stderr so the preview never lies
   silently. Sampling is nearest-neighbour: preview-grade, not export-grade.
"""

import argparse
import json
import math
import os
import random
import struct
import sys
import zlib

SIG = b"\x89PNG\r\n\x1a\n"

# --------------------------------------------------------------------------
# PNG writing (flat RGBA or grayscale buffers)
# --------------------------------------------------------------------------

def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_rgba(path, w, h, flat):
    """flat: bytes/bytearray of length w*h*4, row-major RGBA."""
    raw = bytearray()
    step = w * 4
    for y in range(h):
        raw.append(0)  # filter: None
        raw += flat[y * step:(y + 1) * step]
    _write(path, w, h, 6, raw)


def write_gray(path, w, h, flat):
    """flat: bytes/bytearray of length w*h, row-major 8-bit grayscale."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += flat[y * w:(y + 1) * w]
    _write(path, w, h, 0, raw)


def _write(path, w, h, color_type, raw):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(SIG)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(_chunk(b"IEND", b""))
    os.replace(tmp, path)

# --------------------------------------------------------------------------
# PNG reading (8/16-bit gray, gray+alpha, RGB, RGBA, palette -> RGBA 8-bit)
# --------------------------------------------------------------------------

def read_png(path):
    """Return (width, height, rgba_bytearray, fully_opaque).

    Normalizes every supported PNG to 8-bit RGBA. 16-bit samples are
    reduced to 8-bit (preview-grade). Raises ValueError with a clear
    message on anything unsupported.
    """
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != SIG:
        raise ValueError(f"{path}: not a PNG")
    pos, idat = 8, bytearray()
    width = height = depth = ctype = interlace = None
    plte, trns = [], None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = [body[i:i + 3] for i in range(0, len(body), 3)]
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
    if width is None:
        raise ValueError(f"{path}: missing IHDR")
    if interlace:
        raise ValueError(f"{path}: interlaced PNG not supported (convert with sips)")
    if not idat:
        raise ValueError(f"{path}: no image data")
    if ctype == 3 and depth != 8:
        raise ValueError(f"{path}: palette PNG at bit depth {depth} not supported")
    if ctype != 3 and depth not in (8, 16):
        raise ValueError(f"{path}: bit depth {depth} not supported")

    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype] * depth // 8
    stride = width * bpp
    raw = zlib.decompress(bytes(idat))
    if len(raw) < (stride + 1) * height:
        raise ValueError(f"{path}: truncated image data")
    lines, prev, p = [], bytearray(stride), 0
    for _ in range(height):
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            raise ValueError(f"{path}: unsupported filter {ftype}")
        prev = line
        lines.append(bytes(line))

    buf = bytearray(width * height * 4)
    o = 0
    if ctype == 6 and depth == 8:
        for line in lines:
            buf[o:o + stride] = line
            o += stride
        opaque = buf[3::4].count(255) == width * height
        return width, height, buf, opaque

    opaque = True
    if ctype == 0:  # grayscale (+tRNS single level)
        tlevel = struct.unpack(">H", trns[:2])[0] if trns else None
        for line in lines:
            for i in range(width):
                g = line[i] if depth == 8 else (line[2 * i] << 8 | line[2 * i + 1]) >> 8
                a = 0 if (tlevel is not None and (line[i] if depth == 8 else
                        (line[2 * i] << 8 | line[2 * i + 1])) == tlevel) else 255
                buf[o] = buf[o + 1] = buf[o + 2] = g
                buf[o + 3] = a
                opaque = opaque and a == 255
                o += 4
    elif ctype == 2:  # RGB (+tRNS single color)
        tc = struct.unpack(">HHH", trns[:6]) if trns else None
        for line in lines:
            for i in range(width):
                if depth == 8:
                    rgb = line[3 * i:3 * i + 3]
                    raw16 = tuple(v for v in rgb)
                else:
                    rgb16 = struct.unpack(">HHH", line[6 * i:6 * i + 6])
                    raw16 = rgb16
                    rgb = bytes((rgb16[0] >> 8, rgb16[1] >> 8, rgb16[2] >> 8))
                a = 0 if (tc is not None and raw16 == tuple(v & 0xFF for v in tc)) else 255
                buf[o:o + 3] = rgb
                buf[o + 3] = a
                opaque = opaque and a == 255
                o += 4
    elif ctype == 4:  # gray + alpha
        for line in lines:
            for i in range(width):
                if depth == 8:
                    g, a = line[2 * i], line[2 * i + 1]
                else:
                    g = (line[4 * i] << 8 | line[4 * i + 1]) >> 8
                    a = (line[4 * i + 2] << 8 | line[4 * i + 3]) >> 8
                buf[o] = buf[o + 1] = buf[o + 2] = g
                buf[o + 3] = a
                opaque = opaque and a == 255
                o += 4
    elif ctype == 3:  # palette
        for line in lines:
            for i in range(width):
                idx = line[i]
                if idx >= len(plte):
                    raise ValueError(f"{path}: palette index out of range")
                buf[o:o + 3] = plte[idx]
                a = trns[idx] if (trns is not None and idx < len(trns)) else 255
                buf[o + 3] = a
                opaque = opaque and a == 255
                o += 4
    else:
        raise ValueError(f"{path}: unsupported color type {ctype}")
    return width, height, buf, opaque

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

NAMED_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "00FF00",
    "blue": "0000FF", "yellow": "FFF200", "cyan": "00E5FF", "magenta": "FF00D4",
    "orange": "FF9500", "transparent": "00000000",
}


def parse_color(text):
    t = text.strip().lstrip("#")
    t = NAMED_COLORS.get(t.lower(), t)
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError(f"bad color {text!r} (use #RGB, #RRGGBB or #RRGGBBAA)")
    r, g, b = (int(t[i:i + 2], 16) for i in (0, 2, 4))
    a = int(t[6:8], 16) if len(t) == 8 else 255
    return r, g, b, a


def parse_size(text):
    try:
        w, h = (int(v) for v in text.lower().split("x"))
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError(f"bad size {text!r} (use WxH, e.g. 1920x1080)")


def smooth(edge0, edge1, x):
    """Hermite smoothstep that also works with edge0 > edge1 (inverted)."""
    if edge1 == edge0:
        return 1.0 if x >= edge0 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)

# --------------------------------------------------------------------------
# Asset generators
# --------------------------------------------------------------------------

def gen_solid(w, h, color):
    return bytes(color) * (w * h)


def gen_gradient(w, h, c1, c2, direction, radius=None):
    buf = bytearray(w * h * 4)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    if direction == "r":
        maxr = radius or math.hypot(max(cx, w - 1 - cx), max(cy, h - 1 - cy))
    o = 0
    for y in range(h):
        for x in range(w):
            if direction == "h":
                t = x / max(1, w - 1)
            elif direction == "v":
                t = y / max(1, h - 1)
            else:
                t = min(1.0, math.hypot(x - cx, y - cy) / maxr) if maxr else 0.0
            for k in range(4):
                buf[o + k] = int(c1[k] + (c2[k] - c1[k]) * t + 0.5)
            o += 4
    return bytes(buf)


def gen_ellipse(w, h, color, ring=0):
    cx, cy = (w - 1) / 2, (h - 1) / 2
    rx, ry = w / 2, h / 2
    rmin = min(rx, ry)
    buf = bytearray(w * h * 4)
    o = 0
    for y in range(h):
        for x in range(w):
            n = math.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
            dpx = (n - 1.0) * rmin
            if ring:
                cover = smooth(ring / 2 + 0.75, ring / 2 - 0.75, abs(dpx))
            else:
                cover = smooth(1.5, -1.5, dpx)
            buf[o:o + 3] = color[:3]
            buf[o + 3] = int(color[3] * cover + 0.5)
            o += 4
    return bytes(buf)


def gen_rect(w, h, color, radius=0):
    cx, cy = (w - 1) / 2, (h - 1) / 2
    hw, hh = w / 2, h / 2
    r = max(0, min(radius, hw, hh))
    buf = bytearray(w * h * 4)
    o = 0
    for y in range(h):
        for x in range(w):
            qx = abs(x - cx) - (hw - r)
            qy = abs(y - cy) - (hh - r)
            dx, dy = max(qx, 0.0), max(qy, 0.0)
            d = math.hypot(dx, dy) + min(max(qx, qy), 0.0) - r
            cover = smooth(0.75, -0.75, d)
            buf[o:o + 3] = color[:3]
            buf[o + 3] = int(color[3] * cover + 0.5)
            o += 4
    return bytes(buf)


def gen_dots(w, h, count, color, seed, amin, amax, region=None, cross=0.12):
    rng = random.Random(seed)
    rx, ry, rw, rh = region or (0, 0, w, h)
    rows = [bytearray(w * 4) for _ in range(h)]
    buf = bytearray(w * h * 4)

    def put(x, y, a):
        if rx <= x < rx + rw and ry <= y < ry + rh and 0 <= x < w and 0 <= y < h:
            o = (y * w + x) * 4
            buf[o:o + 3] = color[:3]
            buf[o + 3] = a

    for _ in range(count):
        x = rng.randrange(rx, rx + rw)
        y = rng.randrange(ry, ry + rh)
        a = int(255 * rng.uniform(amin / 255, amax / 255))
        if rng.random() < cross:  # small 3px cross
            put(x, y, a)
            put(x + 1, y, int(a * 0.6))
            put(x - 1, y, int(a * 0.6))
            put(x, y + 1, int(a * 0.6))
            put(x, y - 1, int(a * 0.6))
        else:
            put(x, y, a)
    return bytes(buf)


def gen_mask(w, h, v_from, v_to, direction, radius=None):
    cx, cy = (w - 1) / 2, (h - 1) / 2
    if direction == "r":
        maxr = radius or math.hypot(max(cx, w - 1 - cx), max(cy, h - 1 - cy))
    buf = bytearray(w * h)
    o = 0
    for y in range(h):
        for x in range(w):
            if direction == "h":
                t = x / max(1, w - 1)
            elif direction == "v":
                t = y / max(1, h - 1)
            else:
                t = min(1.0, math.hypot(x - cx, y - cy) / maxr) if maxr else 0.0
            buf[o] = int(v_from + (v_to - v_from) * t + 0.5)
            o += 1
    return bytes(buf)

# --------------------------------------------------------------------------
# Blend modes (PDF/W3C formulas)
# --------------------------------------------------------------------------

def _div_guard(d, zero):
    return zero if d == 0 else d


def _sep_darken(b, s): return min(b, s)
def _sep_multiply(b, s): return b * s
def _sep_color_burn(b, s):
    if b <= 0: return 0.0
    if s >= 1: return 1.0
    return min(1.0, 1.0 - (1.0 - b) / s)
def _sep_linear_burn(b, s): return max(0.0, b + s - 1.0)
def _sep_lighten(b, s): return max(b, s)
def _sep_screen(b, s): return b + s - b * s
def _sep_color_dodge(b, s):
    if b >= 1: return 1.0
    if s <= 0: return 0.0
    return min(1.0, b / (1.0 - s))
def _sep_add(b, s): return min(1.0, b + s)
def _sep_hard_light(b, s):
    return 2 * b * s if s <= 0.5 else 1.0 - 2 * (1.0 - b) * (1.0 - s)
def _sep_overlay(b, s): return _sep_hard_light(s, b)
def _sep_soft_light(b, s):
    if s <= 0.5:
        return b - (1 - 2 * s) * b * (1 - b)
    d = math.sqrt(b) if b > 0.25 else ((16 * b - 12) * b + 4) * b
    return b + (2 * s - 1) * (d - b)
def _sep_vivid_light(b, s):
    return _sep_color_burn(b, s * 2) if s <= 0.5 else _sep_color_dodge(b, s * 2 - 1)
def _sep_linear_light(b, s): return min(1.0, max(0.0, b + 2 * s - 1))
def _sep_pin_light(b, s):
    return min(b, 2 * s) if s <= 0.5 else max(b, 2 * s - 1)
def _sep_hard_mix(b, s): return 1.0 if _sep_vivid_light(b, s) >= 0.5 else 0.0
def _sep_difference(b, s): return abs(b - s)
def _sep_exclusion(b, s): return b + s - 2 * b * s
def _sep_subtract(b, s): return max(0.0, b - s)
def _sep_divide(b, s): return 1.0 if s <= 0 else min(1.0, b / s)


def _lum(c): return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
def _clip3(c): return tuple(min(1.0, max(0.0, v)) for v in c)
def _sat(c): return max(c) - min(c)


def _set_lum(c, l):
    d = l - _lum(c)
    return _clip3((c[0] + d, c[1] + d, c[2] + d))


def _set_sat(c, s):
    mn, mx = min(c), max(c)
    if mn == mx:
        return (0.0, 0.0, 0.0)
    out = []
    for v in c:
        if v == mx:
            out.append(s)
        elif v == mn:
            out.append(0.0)
        else:
            out.append((v - mn) * s / (mx - mn))
    return tuple(out)


SEPARABLE = {
    "Darken": _sep_darken, "Multiply": _sep_multiply,
    "Color Burn": _sep_color_burn, "Linear Burn": _sep_linear_burn,
    "Lighten": _sep_lighten, "Screen": _sep_screen,
    "Color Dodge": _sep_color_dodge, "Linear Dodge (Add)": _sep_add,
    "Overlay": _sep_overlay, "Soft Light": _sep_soft_light,
    "Hard Light": _sep_hard_light, "Vivid Light": _sep_vivid_light,
    "Linear Light": _sep_linear_light, "Pin Light": _sep_pin_light,
    "Hard Mix": _sep_hard_mix, "Difference": _sep_difference,
    "Exclusion": _sep_exclusion, "Subtract": _sep_subtract,
    "Divide": _sep_divide,
}

NON_SEPARABLE = {
    "Hue": lambda cb, cs: _set_lum(_set_sat(cs, _sat(cb)), _lum(cb)),
    "Saturation": lambda cb, cs: _set_lum(_set_sat(cb, _sat(cs)), _lum(cb)),
    "Color": lambda cb, cs: _set_lum(cs, _lum(cb)),
    "Luminosity": lambda cb, cs: _set_lum(cb, _lum(cs)),
}

BLEND_MODES = ["Normal"] + list(SEPARABLE) + list(NON_SEPARABLE)

# --------------------------------------------------------------------------
# Preview compositor
# --------------------------------------------------------------------------

def _ancestors(lay, by_id):
    out, seen = [], set()
    cur = lay
    while True:
        pid = cur.get("parentID")
        if not pid or pid in seen or pid not in by_id:
            return out
        seen.add(pid)
        cur = by_id[pid]
        out.append(cur)


def _mask_sampler(proj, lay):
    """Build sampler(u, v, lx, ly) -> 0..255 coverage for a layer/folder
    mask, honoring linked (layer-local) and unlinked (maskPlacement) modes."""
    path = os.path.join(proj, "images", lay["maskFile"])
    mw, mh, mbuf, _ = read_png(path)
    linked = lay.get("maskLinked", True)
    place = None
    if not linked:
        mp = lay.get("maskPlacement") or {}
        if "origin" not in mp or "size" not in mp:
            return None, f"unlinked mask without maskPlacement on {lay.get('name')}"
        place = (mp["origin"][0], mp["origin"][1], mp["size"][0], mp["size"][1])
    t = lay.get("transform") or {}
    lw = t.get("size", [mw, mh])[0] or mw

    def sample(u, v, lx, ly):
        if place is None:
            mx = int(lx * mw / lw)
            my = int(ly * mh / (t.get("size", [mw, mh])[1] or mh))
        else:
            ox, oy, pw, ph = place
            if not (ox <= u < ox + pw and oy <= v < oy + ph):
                return 0
            mx = int((u - ox) / pw * mw)
            my = int((v - oy) / ph * mh)
        if 0 <= mx < mw and 0 <= my < mh:
            return mbuf[(my * mw + mx) * 4]  # gray reads back replicated in R
        return 0
    return sample, None

class PreviewRenderer:
    def __init__(self, proj):
        self.proj = proj
        with open(os.path.join(proj, "manifest.json"), encoding="utf-8") as f:
            self.man = json.load(f)
        self.W = self.man["width"]
        self.H = self.man["height"]
        self.layers = self.man.get("layers", [])
        self.by_id = {l["id"]: l for l in self.layers}
        self.canvas = bytearray(self.W * self.H * 4)
        self.warned = set()
        self.cov_cache = {}
        self.rendered = []

    def warn(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            print(f"warning: {msg}", file=sys.stderr)

    def _chain_factors(self, lay):
        """(visible, opacity, mask_samplers) including ancestors."""
        visible = lay.get("isVisible", True)
        opacity = 1.0
        samplers = []
        for node in [lay] + _ancestors(lay, self.by_id):
            if not node.get("isVisible", True):
                visible = False
            opacity *= float(node.get("opacity", 1.0))
            if node.get("maskFile") and node.get("maskEnabled", True):
                if node is not lay and node.get("isGroup"):
                    # folder mask covers the folder's transform rectangle
                    t = node.get("transform") or {}
                    if "origin" not in t or "size" not in t:
                        node = dict(node, transform={"origin": [0, 0],
                                                     "size": [self.W, self.H]})
                s, err = _mask_sampler(self.proj, node)
                if err:
                    self.warn(("mask", node["id"]), err)
                elif s:
                    samplers.append(s)
        return visible, min(1.0, max(0.0, opacity)), samplers

    def coverage(self, lid, depth=0):
        """Document-space alpha coverage of a clipping-mask source layer."""
        if lid in self.cov_cache:
            return self.cov_cache[lid]
        if depth > 255:
            return None
        lay = self.by_id.get(lid)
        if lay is None or lay.get("isGroup") or not lay.get("imageFile"):
            self.warn("cov", f"maskSourceID {lid} is not a usable layer")
            self.cov_cache[lid] = None
            return None
        cov = self._render_alpha(lay, depth)
        self.cov_cache[lid] = cov
        return cov

    def _render_alpha(self, lay, depth=0):
        img = lay.get("imageFile")
        if not img or img.lower().endswith(".exr"):
            return None
        try:
            sw, sh, src, _ = read_png(os.path.join(self.proj, "images", img))
        except (OSError, ValueError) as e:
            self.warn(("read", lay["id"]), str(e))
            return None
        _, opacity, samplers = self._chain_factors(lay)
        upstream = None
        if lay.get("maskSourceID"):
            upstream = self.coverage(lay["maskSourceID"], depth + 1)
        buf = bytearray(self.W * self.H)
        for (lx, ly, u, v) in self._pixels(lay, sw, sh):
            i = (int(ly) * sw + int(lx)) * 4
            a = src[i + 3] * opacity
            for s in samplers:
                a *= s(u, v, lx, ly) / 255.0
            if upstream is not None:
                a *= upstream[int(v) * self.W + int(u)] / 255.0
            buf[int(v) * self.W + int(u)] = int(min(1.0, a) * 255 + 0.5)
        return buf

    def _pixels(self, lay, sw, sh):
        """Yield (lx, ly, u, v) for every document pixel covered by the layer,
        with (lx, ly) the layer-local coords and (u, v) the doc pixel center."""
        t = lay.get("transform") or {}
        ox, oy = t.get("origin", [0, 0])
        lw, lh = t.get("size", [sw, sh])
        rot = math.radians(float(t.get("rotation", 0)))
        c, s = math.cos(rot), math.sin(rot)
        cx, cy = lw / 2, lh / 2
        fx, fy = t.get("flipX", False), t.get("flipY", False)
        sx_sc, sy_sc = sw / lw if lw else 1.0, sh / lh if lh else 1.0
        # doc-space bounding box of the rotated layer box
        half_diag = math.hypot(lw, lh) / 2
        x0 = max(0, int(ox + cx - half_diag))
        x1 = min(self.W, math.ceil(ox + cx + half_diag))
        y0 = max(0, int(oy + cy - half_diag))
        y1 = min(self.H, math.ceil(oy + cy + half_diag))
        for y in range(y0, y1):
            v = y + 0.5
            for x in range(x0, x1):
                u = x + 0.5
                rx, ry = u - ox - cx, v - oy - cy
                # inverse of clockwise rotation
                lx = rx * c + ry * s + cx
                ly = -rx * s + ry * c + cy
                if fx:
                    lx = lw - lx
                if fy:
                    ly = lh - ly
                if 0 <= lx < lw and 0 <= ly < lh:
                    yield min(lx * sx_sc, sw - 1e-6), min(ly * sy_sc, sh - 1e-6), u, v

    def _composite(self, lay):
        img = lay.get("imageFile")
        blend = lay.get("blendMode", "Normal")
        if blend not in BLEND_MODES:
            self.warn(("blend", lay["id"]),
                       f"unknown blend mode {blend!r} on {lay.get('name')} — rendered as Normal")
            blend = "Normal"
        try:
            sw, sh, src, opaque = read_png(os.path.join(self.proj, "images", img))
        except (OSError, ValueError) as e:
            self.warn(("read", lay["id"]), str(e))
            return
        visible, opacity, samplers = self._chain_factors(lay)
        if not visible:
            return
        cov = self.coverage(lay["maskSourceID"]) if lay.get("maskSourceID") else None
        t = lay.get("transform") or {}
        fast = (blend == "Normal" and opacity >= 1.0 and not samplers
                and cov is None and not float(t.get("rotation", 0))
                and not t.get("flipX", False) and not t.get("flipY", False)
                and t.get("origin", [0, 0]) == [0, 0]
                and t.get("size", [sw, sh]) == [self.W, self.H]
                and (sw, sh) == (self.W, self.H) and opaque)
        W, H, canvas = self.W, self.H, self.canvas
        if fast:
            step = W * 4
            for y in range(H):
                canvas[y * step:(y + 1) * step] = src[y * step:(y + 1) * step]
            self.rendered.append(f"{lay.get('name')} (Normal, fast)")
            return
        sep = SEPARABLE.get(blend)
        nonsep = NON_SEPARABLE.get(blend)
        for (lx, ly, u, v) in self._pixels(lay, sw, sh):
            si = (int(ly) * sw + int(lx)) * 4
            sa = src[si + 3]
            if sa == 0:
                continue
            ea = sa / 255.0 * opacity
            for s in samplers:
                m = s(u, v, lx, ly)
                if m == 0:
                    ea = 0.0
                    break
                ea *= m / 255.0
            if ea <= 0:
                continue
            if cov is not None:
                cv = cov[int(v) * W + int(u)]
                if cv == 0:
                    continue
                ea *= cv / 255.0
            i = (int(v) * W + int(u)) * 4
            ab = canvas[i + 3] / 255.0
            ao = ea + ab * (1 - ea)
            if ao <= 0:
                continue
            cs = (src[si] / 255.0, src[si + 1] / 255.0, src[si + 2] / 255.0)
            if blend == "Normal":
                blended = cs
            elif sep:
                cb = (canvas[i] / 255.0, canvas[i + 1] / 255.0, canvas[i + 2] / 255.0)
                blended = tuple(sep(cb[k], cs[k]) for k in range(3))
            else:
                cb = (canvas[i] / 255.0, canvas[i + 1] / 255.0, canvas[i + 2] / 255.0)
                blended = nonsep(cb, cs)
            for k in range(3):
                cbk = canvas[i + k] / 255.0
                co = (ea * blended[k] + (1 - ea) * ab * cbk) / ao
                canvas[i + k] = int(co * 255 + 0.5)
            canvas[i + 3] = int(ao * 255 + 0.5)
        self.rendered.append(f"{lay.get('name')} ({blend}, opacity {opacity:.2f})")

    def run(self, out):
        W, H = self.W, self.H
        for lay in self.layers:  # bottom to top
            name = lay.get("name", lay["id"][:8])
            if lay.get("adjustment") is not None:
                self.warn(("adj", lay["id"]),
                          f"adjustment layer {name!r} ({lay['adjustment'].get('kind')}) "
                          "not rendered in preview")
                continue
            if lay.get("isGroup"):
                if float(lay.get("opacity", 1.0)) != 1.0 or lay.get("maskFile"):
                    pass  # handled through descendant factors
                continue
            if lay.get("imageFile", "").lower().endswith(".exr"):
                self.warn(("exr", lay["id"]),
                          f"HDR layer {name!r} (.exr) not rendered in preview")
                continue
            if lay.get("gif"):
                self.warn(("gif", lay["id"]),
                          f"animated GIF layer {name!r}: preview shows the selected frame only")
            if lay.get("effects"):
                enabled = [k for k, v in (lay["effects"] or {}).items()
                           if isinstance(v, dict) and v.get("enabled", True)]
                if enabled:
                    self.warn(("fx", lay["id"]),
                              f"layer effects on {name!r} ({', '.join(enabled)}) not rendered")
            if not lay.get("imageFile"):
                self.warn(("noimg", lay["id"]), f"layer {name!r} has no image asset; skipped")
                continue
            self._composite(lay)
        for line in self.rendered:
            print(f"rendered: {line}")
        write_rgba(out, W, H, self.canvas)
        print(f"wrote {out} ({W}x{H}, {len(self.rendered)} layer(s) composited)")

# --------------------------------------------------------------------------
# info command
# --------------------------------------------------------------------------

CTYPE_NAMES = {0: "grayscale", 2: "RGB", 3: "palette", 4: "gray+alpha", 6: "RGBA"}


def cmd_info(paths):
    for path in paths:
        with open(path, "rb") as f:
            head = f.read(33)
        if head[:8] != SIG:
            print(f"{path}: not a PNG")
            continue
        w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
        alpha = ctype in (4, 6) or "tRNS"  # tRNS unknown at header level
        print(f"{path}: {w}x{h}, {depth}-bit {CTYPE_NAMES.get(ctype, ctype)}, "
              f"{os.path.getsize(path)} bytes"
              + (", alpha" if ctype in (4, 6) else ""))

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _add_size_out(p):
    p.add_argument("--size", required=True, help="WxH, e.g. 1920x1080")
    p.add_argument("--out", required=True, help="output PNG path")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="comp_png.py",
        description="Zero-dependency PNG asset generator and .comp preview compositor.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("solid", help="solid color layer")
    _add_size_out(p)
    p.add_argument("--color", required=True)

    p = sub.add_parser("gradient", help="linear or radial gradient layer")
    _add_size_out(p)
    p.add_argument("--from", dest="c1", required=True)
    p.add_argument("--to", dest="c2", required=True)
    p.add_argument("--dir", choices=["h", "v", "r"], default="v",
                   help="h: left→right, v: top→bottom, r: radial from center")
    p.add_argument("--radius", type=float, default=None, help="radial radius in px")

    p = sub.add_parser("ellipse", help="filled ellipse (or ring) on transparent")
    _add_size_out(p)
    p.add_argument("--fill", required=True)
    p.add_argument("--ring", type=float, default=0,
                   help="stroke width in px: draws a hollow ring instead")

    p = sub.add_parser("rect", help="filled rectangle, optional rounded corners")
    _add_size_out(p)
    p.add_argument("--fill", required=True)
    p.add_argument("--radius", type=float, default=0, help="corner radius in px")

    p = sub.add_parser("dots", help="scattered dots (stars, noise specks)")
    _add_size_out(p)
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--color", default="white")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--min-alpha", type=int, default=120)
    p.add_argument("--max-alpha", type=int, default=255)
    p.add_argument("--region", default=None, help="x,y,w,h sub-region")
    p.add_argument("--cross", type=float, default=0.12, help="fraction drawn as 3px crosses")

    p = sub.add_parser("mask", help="8-bit grayscale mask (white shows)")
    _add_size_out(p)
    p.add_argument("--from", dest="v1", type=int, required=True, help="0-255")
    p.add_argument("--to", dest="v2", type=int, required=True, help="0-255")
    p.add_argument("--dir", choices=["h", "v", "r"], default="h")
    p.add_argument("--radius", type=float, default=None)

    p = sub.add_parser("info", help="inspect PNG headers")
    p.add_argument("pngs", nargs="+")

    p = sub.add_parser("preview", help="composite a .comp project to a PNG")
    p.add_argument("project", help="path to the .comp package")
    p.add_argument("--out", required=True, help="output preview PNG path")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "solid":
            w, h = parse_size(args.size)
            write_rgba(args.out, w, h, gen_solid(w, h, parse_color(args.color)))
        elif args.cmd == "gradient":
            w, h = parse_size(args.size)
            write_rgba(args.out, w, h,
                       gen_gradient(w, h, parse_color(args.c1), parse_color(args.c2),
                                    args.dir, args.radius))
        elif args.cmd == "ellipse":
            w, h = parse_size(args.size)
            write_rgba(args.out, w, h,
                       gen_ellipse(w, h, parse_color(args.fill), args.ring))
        elif args.cmd == "rect":
            w, h = parse_size(args.size)
            write_rgba(args.out, w, h,
                       gen_rect(w, h, parse_color(args.fill), args.radius))
        elif args.cmd == "dots":
            w, h = parse_size(args.size)
            region = tuple(int(v) for v in args.region.split(",")) if args.region else None
            write_rgba(args.out, w, h,
                       gen_dots(w, h, args.count, parse_color(args.color), args.seed,
                                args.min_alpha, args.max_alpha, region, args.cross))
        elif args.cmd == "mask":
            w, h = parse_size(args.size)
            for v in (args.v1, args.v2):
                if not 0 <= v <= 255:
                    raise ValueError("mask values must be 0-255")
            write_gray(args.out, w, h,
                       gen_mask(w, h, args.v1, args.v2, args.dir, args.radius))
        elif args.cmd == "info":
            cmd_info(args.pngs)
        elif args.cmd == "preview":
            PreviewRenderer(args.project).run(args.out)
    except (ValueError, OSError, KeyError, struct.error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
