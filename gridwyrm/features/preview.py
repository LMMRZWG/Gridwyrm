"""Painting the actual-size preview strip."""

import os

import tkinter as tk

from tkinter import filedialog

from ..core import theme
from ..core.artwork import (
    MAP_CARPET, MAP_DARK, MAP_GRASS, MAP_GRASS_DARK, MAP_MID,
    MAP_PATH, MAP_PATH_DARK, MAP_TILE, MAP_TREE, MAP_TREE_LIT,
    MAP_WALL, MAP_WOOD, MAP_WOOD_DARK, deterministic_noise)
from ..core.geometry import hex_polys, square_lines
from ..core.images import HAVE_PIL, Image, ImageTk
from ..core.theme import blend

class Preview:
    """Painting the actual-size preview strip.
    A true 1:1 crop of the grid, drawn over a sample map or over a
    real one the user has pointed it at. The map is static, so it is
    kept on its own canvas tag and only rebuilt when the strip is
    resized rather than on every slider movement.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app
        self.photo = None
        self.photo_key = None
        self.map_size = None

    def choose_preview_image(self):
        """Point the preview at a real map - ideally tonight's map."""
        formats = [("Images", "*.png *.gif *.jpg *.jpeg" if HAVE_PIL
                    else "*.png *.gif"), ("All files", "*.*")]
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Choose a map image for the preview",
            filetypes=formats,
        )
        if not path:
            return
        self.app.preview_image_path = path
        self.app._photo_key = None
        self.app._map_size = None                    # force the backdrop to rebuild
        self._update_backdrop_label()
        self.app.schedule_draw()

    def clear_preview_image(self):
        self.app.preview_image_path = ""
        self.app.preview_photo = None
        self.app._photo_key = None
        self.app._map_size = None
        self._update_backdrop_label()
        self.app.schedule_draw()

    def _update_backdrop_label(self):
        if self.app.preview_image_path:
            name = os.path.basename(self.app.preview_image_path)
            self.app.backdrop_label.set(name if len(name) <= 34
                                    else name[:31] + "\u2026")
        else:
            self.app.backdrop_label.set("Built-in sample map")

    def _scaled_photo(self, path, target_h):
        """Scale an image down to about `target_h` pixels tall."""
        if HAVE_PIL:
            image = Image.open(path).convert("RGB")
            scale = target_h / float(max(1, image.height))
            size = (max(1, int(image.width * scale)),
                    max(1, int(image.height * scale)))
            return ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))
        # Tk handles PNG and GIF unaided, but only whole-number downscaling.
        photo = tk.PhotoImage(file=path)
        factor = max(1, int(round(photo.height() / float(max(1, target_h)))))
        if factor > 1:
            photo = photo.subsample(factor, factor)
        return photo

    def _ensure_preview_photo(self, height):
        """Load and cache the backdrop, rescaling only when the size changes."""
        if not self.app.preview_image_path:
            self.app.preview_photo = None
            return
        key = (self.app.preview_image_path, height)
        if self.app._photo_key == key and self.app.preview_photo is not None:
            return
        try:
            self.app.preview_photo = self._scaled_photo(self.app.preview_image_path,
                                                    height)
            self.app._photo_key = key
        except Exception:
            self.app.preview_photo = None
            self.app._photo_key = None
            self.app.preview_image_path = ""
            self._update_backdrop_label()
            self.app.status.set(
                "Could not read that image \u2014 PNG or GIF works"
                if not HAVE_PIL else "Could not read that image"
            )

    def _paint_sample_map(self, c, w, h):
        """A small stylised battle map: grass, trees, a path and a building.

        Used when no real map has been chosen. Tiled from a fixed-width scene
        so any panel width looks deliberate, and tagged so it is only rebuilt
        when the canvas is resized rather than on every slider movement.
        """
        self._ensure_preview_photo(int(h))
        if self.app.preview_photo is not None:
            # Tile the real map to cover, so a portrait map still fills a wide
            # strip instead of leaving the rest of the preview blank.
            image_w = max(1, self.app.preview_photo.width())
            image_h = max(1, self.app.preview_photo.height())
            for x in range(0, int(w) + image_w, image_w):
                for y in range(0, int(h) + image_h, image_h):
                    c.create_image(x, y, anchor="nw", image=self.app.preview_photo,
                                   tags="map")
            return

        c.create_rectangle(0, 0, w, h, fill=MAP_GRASS, outline="", tags="map")

        # Grass mottling, coarse enough to stay cheap.
        step = self.app.ui.px(9)
        columns = int(w / step) + 1
        for index in range(columns * (int(h / step) + 1)):
            if deterministic_noise(index * 7 + 3) > 0.62:
                x = (index % columns) * step
                y = (index // columns) * step
                c.create_rectangle(x, y, x + step, y + step,
                                   fill=MAP_GRASS_DARK, outline="", tags="map")

        scene = max(self.app.ui.px(150), self.app.ui.px(210))
        for start in range(0, int(w) + scene, scene):
            self._paint_scene(c, start, scene, h)

    def _paint_scene(self, c, x0, width, height):
        px = self.app.ui.px

        # Trees on the left of the scene.
        for i in range(3):
            radius = px(7) + px(4) * deterministic_noise(x0 + i * 31)
            cx = x0 + width * (0.04 + 0.09 * i) + px(3)
            cy = height * (0.22 + 0.5 * deterministic_noise(x0 + i * 57))
            c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                          fill=MAP_TREE, outline="", tags="map")
            c.create_oval(cx - radius * 0.55, cy - radius * 0.75,
                          cx + radius * 0.25, cy - radius * 0.05,
                          fill=MAP_TREE_LIT, outline="", tags="map")

        # A stone path running the full height.
        path_x = x0 + width * 0.36
        path_w = max(px(16), width * 0.11)
        c.create_rectangle(path_x, 0, path_x + path_w, height,
                           fill=MAP_PATH, outline="", tags="map")
        cobble = px(6)
        rows = int(height / cobble) + 1
        for row in range(rows):
            for col in range(int(path_w / cobble) + 1):
                if deterministic_noise(x0 + row * 13 + col * 101) > 0.55:
                    x = path_x + col * cobble
                    y = row * cobble
                    c.create_rectangle(x, y, x + cobble, y + cobble,
                                       fill=MAP_PATH_DARK, outline="",
                                       tags="map")

        # A building: stone wall, timber floor, a tiled room and a carpet.
        left = x0 + width * 0.56
        right = x0 + width * 0.95
        top = height * 0.14
        bottom = height * 0.88
        if right - left < px(30) or bottom - top < px(18):
            return
        c.create_rectangle(left, top, right, bottom, fill=MAP_WALL,
                           outline=MAP_DARK, tags="map")
        wall = max(px(3), (bottom - top) * 0.08)
        c.create_rectangle(left + wall, top + wall, right - wall, bottom - wall,
                           fill=MAP_WOOD, outline="", tags="map")
        # Floorboards.
        board = px(5)
        y = top + wall
        while y < bottom - wall:
            c.create_line(left + wall, y, right - wall, y,
                          fill=MAP_WOOD_DARK, tags="map")
            y += board
        # Tiled room in the left third.
        split = left + (right - left) * 0.38
        c.create_rectangle(left + wall, top + wall, split, bottom - wall,
                           fill=MAP_TILE, outline=MAP_DARK, tags="map")
        # Carpet in the right part.
        carpet_x = split + (right - split) * 0.25
        carpet_y = top + (bottom - top) * 0.35
        c.create_rectangle(carpet_x, carpet_y,
                           carpet_x + (right - split) * 0.42,
                           carpet_y + (bottom - top) * 0.32,
                           fill=MAP_CARPET, outline="", tags="map")

    def _paint_colour_chip(self, c, w, colour, opacity):
        """State the colour outright, so the preview cannot be misread."""
        px = self.app.ui.px
        label = "%s   %d%%" % (colour.upper(), opacity)
        probe = c.create_text(0, -50, text=label, anchor="nw",
                              font=self.app.ui.f_hint, tags="chip")
        bounds = c.bbox(probe)
        c.delete(probe)
        text_w = (bounds[2] - bounds[0]) if bounds else px(60)
        text_h = (bounds[3] - bounds[1]) if bounds else px(11)

        pad = px(5)
        chip = px(9)
        plate_w = pad + chip + px(5) + text_w + pad
        plate_h = max(chip, text_h) + pad
        x0 = w - plate_w - px(6)
        y0 = px(6)
        c.create_rectangle(x0, y0, x0 + plate_w, y0 + plate_h,
                           fill=theme.INK, outline=theme.LINE, tags="chip")
        middle = y0 + plate_h / 2
        c.create_rectangle(x0 + pad, middle - chip / 2,
                           x0 + pad + chip, middle + chip / 2,
                           fill=colour, outline=theme.LINE, tags="chip")
        c.create_text(x0 + pad + chip + px(5), middle, text=label, anchor="w",
                      fill=theme.TEXT, font=self.app.ui.f_hint, tags="chip")

    def _paint_preview(self, kind, size, off_x, off_y, colour, weight, opacity):
        c = self.app.preview
        w, h = self.app.preview.winfo_width(), self.app.preview.winfo_height()
        if w <= 1 or h <= 1:
            return

        # The map is static, so rebuild it only when the canvas changes size.
        if getattr(self, "_map_size", None) != (w, h):
            c.delete("map")
            self._paint_sample_map(c, w, h)
            self.app._map_size = (w, h)

        c.delete("grid")
        c.delete("chip")
        # A canvas has no alpha, so fade the line toward a mid map tone by the
        # same fraction the real overlay would be transparent by.
        shown = blend(colour, MAP_MID, max(0.10, opacity / 100.0))
        if kind == "Square":
            for x1, y1, x2, y2 in square_lines(w, h, size, off_x, off_y):
                c.create_line(x1, y1, x2, y2, fill=shown, width=weight,
                              tags="grid")
        else:
            for pts in hex_polys(w, h, size, off_x, off_y,
                                 pointy=(kind == "Hex (pointy top)")):
                c.create_polygon(pts, outline=shown, fill="", width=weight,
                                 tags="grid")
        c.tag_raise("grid")
        self._paint_colour_chip(c, w, colour, opacity)
