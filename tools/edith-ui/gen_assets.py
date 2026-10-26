#!/usr/bin/env python3
"""Generates the Edith recovery UI image assets.

Outputs, for every recovery density bucket (mdpi..xxxhdpi):
  edith_logo.png   the Edith mark (white bars + accent leaf)
  font_title.png   Google Sans Flex atlas for the Recovery/Fastboot tabs
  font_menu.png    Google Sans Flex atlas for menu items and headers
  font_small.png   Google Sans Flex atlas for the version/status block

The atlases use minui's 96-column x 2-row glyph layout (ASCII 0x20..0x7f,
top row regular, bottom row bold) and carry the per-glyph advance widths in
an "Advances" tEXt chunk so minui can render proportional text.

The logo is rasterised from the Settings Edith mark
(packages/apps/Settings/stub/ui/res/drawable/ic_edith_logo.xml), with the
leaf gradient built from the UI accent (#89CFF0).

Requires pycairo and ImageMagick for the grayscale PNG encode. Run from the
bootable/recovery tree:

  python3 tools/edith-ui/gen_assets.py
"""

import argparse
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib

LEAF_COLOR = "#A5C4FF"  # Material 3 primaryDim
BAR_WHITE = "#FFFFFF"
# The mark is blitted as an opaque surface, so its matte must match the UI
# background (Material 3 dark `surface`).
LOGO_BACKGROUND = "#000000"
FONT_FAMILY = "Google Sans Flex"

# Recovery resource buckets and their scale relative to mdpi.
BUCKETS = {
    "mdpi": 1.0,
    "hdpi": 1.5,
    "xhdpi": 2.0,
    "xxhdpi": 3.0,
    "xxxhdpi": 4.0,
}

# Font sizes in xxhdpi pixels, plus the cairo weight for the bold row.
FONTS = {
    "font_title": (66, 400, 600),
    "font_menu": (48, 400, 500),
    "font_small": (32, 400, 500),
}

CAIRO_WEIGHTS = {
    400: "FONT_WEIGHT_NORMAL",
    500: "FONT_WEIGHT_NORMAL",
    600: "FONT_WEIGHT_BOLD",
    700: "FONT_WEIGHT_BOLD",
}

# Edith mark: width in xxhdpi pixels, height follows the vector aspect ratio.
LOGO_WIDTH_XXHDPI = 155

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETTINGS_ICON = os.path.join(
    HERE, "../../../../packages/apps/Settings/stub/ui/res/drawable/ic_edith_logo.xml")
DEFAULT_FONT = os.path.join(HERE, "../../../../vendor/edithui/fonts/GoogleSansFlex-Regular.ttf")
DEFAULT_OUT = os.path.join(HERE, "../..")

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def add_text_chunk(path, key, value):
    """Inserts a tEXt chunk right after IHDR."""
    data = bytearray(open(path, "rb").read())
    if bytes(data[:8]) != PNG_SIG:
        raise RuntimeError(f"{path} is not a PNG")
    ihdr_end = 8 + 4 + 4 + 13 + 4
    payload = b"tEXt" + key.encode("latin-1") + b"\0" + value.encode("latin-1")
    chunk = struct.pack(">I", len(key) + 1 + len(value)) + payload
    chunk += struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    data[ihdr_end:ihdr_end] = chunk
    open(path, "wb").write(data)


def write_gray_png(raw, width, height, path):
    """Writes 8-bit grayscale pixels (single channel) through ImageMagick."""
    with tempfile.NamedTemporaryFile(suffix=".gray", delete=False) as f:
        f.write(raw)
        raw_path = f.name
    try:
        subprocess.run(
            ["convert", "-size", f"{width}x{height}", "-depth", "8",
             f"gray:{raw_path}", "-type", "Grayscale", "-colorspace", "Gray", path],
            check=True)
    finally:
        os.unlink(raw_path)


def setup_cairo(font_path):
    """Isolates fontconfig to the Google Sans Flex file and returns cairo."""
    font_dir = tempfile.mkdtemp(prefix="edith-fonts-")
    shutil.copy(font_path, os.path.join(font_dir, "GoogleSansFlex-Regular.ttf"))
    conf = os.path.join(font_dir, "fonts.conf")
    with open(conf, "w") as f:
        f.write(
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
            "<fontconfig>\n"
            f"  <dir>{font_dir}</dir>\n"
            f"  <cachedir>{font_dir}/cache</cachedir>\n"
            "</fontconfig>\n")
    os.environ["FONTCONFIG_FILE"] = conf

    import cairo
    return cairo


def cairo_weight(cairo, weight):
    return cairo.FONT_WEIGHT_BOLD if weight >= 600 else cairo.FONT_WEIGHT_NORMAL


def build_font_atlas(cairo, size_px, regular, bold, out_path):
    """Renders the 96x2 glyph atlas and stores the advances in a tEXt chunk."""
    chars = [chr(c) for c in range(0x20, 0x80)]

    probe = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
    cr = cairo.Context(probe)
    cr.select_font_face(FONT_FAMILY, cairo.FONT_SLANT_NORMAL, cairo_weight(cairo, regular))
    cr.set_font_size(size_px)
    ascent = int(math.ceil(cr.font_extents()[0]))
    descent = int(math.ceil(cr.font_extents()[1]))

    advances = [max(1, int(round(cr.text_extents(ch).x_advance))) for ch in chars]
    cell_w = max(advances) + 1
    cell_h = ascent + descent + 1

    width, height = cell_w * len(chars), cell_h * 2
    surface = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgba(1, 1, 1, 1)
    for row, weight in enumerate((regular, bold)):
        cr.select_font_face(FONT_FAMILY, cairo.FONT_SLANT_NORMAL, cairo_weight(cairo, weight))
        cr.set_font_size(size_px)
        for i, ch in enumerate(chars):
            cr.save()
            cr.rectangle(i * cell_w, row * cell_h, cell_w, cell_h)
            cr.clip()
            cr.move_to(i * cell_w, row * cell_h + ascent)
            cr.show_text(ch)
            cr.restore()
    surface.flush()

    stride = surface.get_stride()
    data = bytes(surface.get_data())
    raw = bytearray(width * height)
    for y in range(height):
        raw[y * width:(y + 1) * width] = data[y * stride:y * stride + width]

    write_gray_png(bytes(raw), width, height, out_path)
    add_text_chunk(out_path, "Advances", ",".join(str(a) for a in advances))


def parse_path(path_data):
    """Yields (command, args) for the subset used by the Edith mark."""
    import re
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", path_data)
    cmd = None
    args = []
    for token in tokens:
        if token.isalpha():
            if cmd is not None:
                yield cmd, args
            cmd, args = token, []
        else:
            args.append(float(token))
    if cmd is not None:
        yield cmd, args


def draw_path(cr, path_data):
    cr.new_path()
    prev = (0.0, 0.0)
    start = (0.0, 0.0)
    for cmd, args in parse_path(path_data):
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = args[0], args[1]
            if rel:
                x, y = prev[0] + x, prev[1] + y
            cr.move_to(x, y)
            prev = start = (x, y)
        elif c == "L":
            for i in range(0, len(args), 2):
                x, y = args[i], args[i + 1]
                if rel:
                    x, y = prev[0] + x, prev[1] + y
                cr.line_to(x, y)
                prev = (x, y)
        elif c == "H":
            for v in args:
                x = prev[0] + v if rel else v
                cr.line_to(x, prev[1])
                prev = (x, prev[1])
        elif c == "V":
            for v in args:
                y = prev[1] + v if rel else v
                cr.line_to(prev[0], y)
                prev = (prev[0], y)
        elif c == "C":
            for i in range(0, len(args), 6):
                pts = args[i:i + 6]
                if rel:
                    pts = [pts[j] + prev[j % 2] for j in range(6)]
                cr.curve_to(*pts)
                prev = (pts[4], pts[5])
        elif c == "Z":
            cr.close_path()
            prev = start
    return cr


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def build_logo(cairo, icon_path, width_px, out_path):
    root = ET.parse(icon_path).getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    viewport_w = float(root.get(ns + "viewportWidth", 76))
    viewport_h = float(root.get(ns + "viewportHeight", 61))
    scale = width_px / viewport_w
    height_px = int(round(viewport_h * scale))

    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width_px, height_px)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*_rgb(LOGO_BACKGROUND))
    cr.paint()
    cr.scale(scale, scale)

    for index, path in enumerate(root.findall("path")):
        if index == 0:
            # The leaf is a single flat colour.
            cr.set_source_rgb(*_rgb(LEAF_COLOR))
        else:
            cr.set_source_rgb(*_rgb(BAR_WHITE))
        draw_path(cr, path.get(ns + "pathData"))
        cr.fill()
    surface.flush()
    surface.write_to_png(out_path)


def _write_alpha(cairo, surface, size_px, out_path):
    surface.flush()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    raw = bytearray(size_px * size_px)
    for y in range(size_px):
        raw[y * size_px:(y + 1) * size_px] = data[y * stride:y * stride + size_px]
    write_gray_png(bytes(raw), size_px, size_px, out_path)


def build_back_icons(cairo, size_px, images_dir):
    unit = size_px / 120.0

    # Arrow (inactive state and the glyph inside the active circle).
    surface = cairo.ImageSurface(cairo.FORMAT_A8, size_px, size_px)
    cr = cairo.Context(surface)
    cr.set_source_rgba(1, 1, 1, 1)
    cr.set_line_width(10 * unit)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.move_to(92 * unit, 60 * unit)
    cr.line_to(32 * unit, 60 * unit)
    cr.move_to(62 * unit, 32 * unit)
    cr.line_to(32 * unit, 60 * unit)
    cr.line_to(62 * unit, 88 * unit)
    cr.stroke()
    _write_alpha(cairo, surface, size_px, os.path.join(images_dir, "ic_back.png"))

    # Filled circle behind the arrow when the back item is selected.
    surface = cairo.ImageSurface(cairo.FORMAT_A8, size_px, size_px)
    cr = cairo.Context(surface)
    cr.set_source_rgba(1, 1, 1, 1)
    cr.arc(60 * unit, 60 * unit, 56 * unit, 0, 2 * 3.141592653589793)
    cr.fill()
    _write_alpha(cairo, surface, size_px, os.path.join(images_dir, "ic_back_sel.png"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings-icon", default=DEFAULT_SETTINGS_ICON)
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    args = parser.parse_args()

    cairo = setup_cairo(os.path.abspath(args.font))
    icon = os.path.abspath(args.settings_icon)
    out_dir = os.path.abspath(args.out_dir)

    for bucket, scale in BUCKETS.items():
        images = os.path.join(out_dir, f"res-{bucket}", "images")
        os.makedirs(images, exist_ok=True)

        for name, (size_xxhdpi, regular, bold) in FONTS.items():
            size = max(8, int(round(size_xxhdpi * scale / 3.0)))
            build_font_atlas(cairo, size, regular, bold,
                             os.path.join(images, f"{name}.png"))
            print(f"{bucket}: {name} ({size}px)")

        build_logo(cairo, icon, max(8, int(round(LOGO_WIDTH_XXHDPI * scale / 3.0))),
                   os.path.join(images, "edith_logo.png"))
        build_back_icons(cairo, max(8, int(round(120 * scale / 3.0))), images)
        print(f"{bucket}: edith_logo, ic_back, ic_back_sel")


if __name__ == "__main__":
    sys.exit(main())
