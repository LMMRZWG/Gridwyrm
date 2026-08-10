#!/usr/bin/env python3
"""
Tests for Gridwyrm.

Run them with:

    python -m unittest -v

These cover the parts that are pure logic and easy to break by accident: the
grid geometry, colour conversion, theme resolution, the settings file, and the
hotkey defaults. There is no test for the interface itself, which needs a real
screen.

Only the standard library is used, so there is nothing to install.
"""

import os
import shutil
import tempfile
import unittest

try:
    import gridwyrm
except ImportError as error:                     # pragma: no cover
    raise unittest.SkipTest("cannot import gridwyrm: %s" % error)


class SquareGrid(unittest.TestCase):

    def test_covers_the_whole_screen(self):
        width, height, cell = 1920, 1080, 64
        lines = gridwyrm.square_lines(width, height, cell, 0, 0)
        vertical = [line for line in lines if line[0] == line[2]]
        horizontal = [line for line in lines if line[1] == line[3]]

        # At least enough lines to span the screen, in both directions.
        self.assertGreaterEqual(len(vertical), width // cell)
        self.assertGreaterEqual(len(horizontal), height // cell)
        # And the span reaches past both edges, so there is no bare strip.
        self.assertLessEqual(min(line[0] for line in vertical), 0)
        self.assertGreaterEqual(max(line[0] for line in vertical), width)

    def test_offset_wraps_within_one_cell(self):
        """A large offset must not push the grid off the screen."""
        cell = 64
        for offset in (0, 10, 63.5, 200, -200, 5000):
            lines = gridwyrm.square_lines(800, 600, cell, offset, 0)
            first = min(line[0] for line in lines if line[0] == line[2])
            self.assertGreater(first, -2 * cell)
            self.assertLessEqual(first, 0)

    def test_refuses_a_degenerate_cell(self):
        self.assertEqual(gridwyrm.square_lines(800, 600, 1, 0, 0), [])
        self.assertEqual(gridwyrm.square_lines(800, 600, 0, 0, 0), [])

    def test_fractional_cell_size(self):
        """Map grids are rarely round numbers, so halves must work."""
        lines = gridwyrm.square_lines(800, 600, 63.5, 0, 0)
        self.assertTrue(lines)


class HexGrid(unittest.TestCase):

    def hex_extent(self, points):
        xs, ys = points[0::2], points[1::2]
        return max(xs) - min(xs), max(ys) - min(ys)

    def test_pointy_top_proportions(self):
        size = 40
        polys = gridwyrm.hex_polys(600, 400, size, 0, 0, pointy=True)
        self.assertTrue(polys)
        width, height = self.hex_extent(polys[0])
        self.assertAlmostEqual(width, 3 ** 0.5 * size, places=4)
        self.assertAlmostEqual(height, 2 * size, places=4)

    def test_flat_top_is_the_transpose(self):
        size = 40
        polys = gridwyrm.hex_polys(600, 400, size, 0, 0, pointy=False)
        width, height = self.hex_extent(polys[0])
        self.assertAlmostEqual(width, 2 * size, places=4)
        self.assertAlmostEqual(height, 3 ** 0.5 * size, places=4)

    def test_every_hex_has_six_corners(self):
        for poly in gridwyrm.hex_polys(400, 300, 30, 5, 7):
            self.assertEqual(len(poly), 12)      # six x/y pairs

    def test_refuses_a_degenerate_cell(self):
        self.assertEqual(gridwyrm.hex_polys(400, 300, 1, 0, 0), [])


class Geometry(unittest.TestCase):

    def test_accepts_valid_regions(self):
        self.assertEqual(gridwyrm.parse_geometry("1920x1080+1920+0"),
                         (1920, 0, 1920, 1080))
        self.assertEqual(gridwyrm.parse_geometry("2560x1440-2560+120"),
                         (-2560, 120, 2560, 1440))
        self.assertEqual(gridwyrm.parse_geometry(" 800 x 600 +0 +0 "),
                         (0, 0, 800, 600))
        # The multiplication sign, since the hint text in the panel uses it.
        self.assertEqual(gridwyrm.parse_geometry("640\u00d7480+0+0"),
                         (0, 0, 640, 480))

    def test_rejects_nonsense(self):
        for text in ("", "junk", "1920x1080", "1920x1080+0", "x+0+0", None):
            with self.subTest(text=text):
                if text is None:
                    continue
                self.assertIsNone(gridwyrm.parse_geometry(text))


class Colour(unittest.TestCase):

    def test_hex_round_trip_is_exact(self):
        for value in ("#FFFFFF", "#000000", "#E2483D", "#4A90E2", "#1E222B"):
            back = gridwyrm.rgb_to_hex(*gridwyrm.hex_to_rgb(value))
            self.assertEqual(back.upper(), value.upper())

    def test_blend_endpoints(self):
        self.assertEqual(gridwyrm.blend("#FFFFFF", "#000000", 1.0).upper(),
                         "#FFFFFF")
        self.assertEqual(gridwyrm.blend("#FFFFFF", "#000000", 0.0).upper(),
                         "#000000")

    def test_blend_survives_bad_input(self):
        """Theme colours can be system names, which are not hex."""
        self.assertEqual(gridwyrm.blend("SystemButtonFace", "#000000", 0.5),
                         "SystemButtonFace")

    def test_luminance_ordering(self):
        self.assertLess(gridwyrm.luminance("#000000"),
                        gridwyrm.luminance("#808080"))
        self.assertLess(gridwyrm.luminance("#808080"),
                        gridwyrm.luminance("#FFFFFF"))


class Themes(unittest.TestCase):

    def test_every_builtin_defines_every_role(self):
        for name in ("Dark", "Light", "Classic", "Colour-blind safe"):
            theme = gridwyrm.THEMES[name]
            for role in gridwyrm.ROLE_KEYS:
                with self.subTest(theme=name, role=role):
                    self.assertIn(role, theme)
                    self.assertRegex(theme[role], r"^#[0-9A-Fa-f]{6}$")

    def test_custom_merges_over_dark_and_ignores_junk(self):
        custom = {"panel": "#123456", "text": "not a colour", "bogus": "#FFFFFF"}
        theme = gridwyrm.resolve_theme("Custom", custom)
        self.assertEqual(theme["panel"], "#123456")
        self.assertEqual(theme["text"], gridwyrm.THEMES["Dark"]["text"])
        self.assertNotIn("bogus", gridwyrm.ROLE_KEYS)

    def test_custom_is_never_native(self):
        """Only Classic hands widget drawing back to the operating system."""
        self.assertFalse(gridwyrm.resolve_theme("Custom", {}).get("native"))
        self.assertTrue(gridwyrm.THEMES["Classic"].get("native"))

    def test_unknown_theme_falls_back(self):
        self.assertEqual(gridwyrm.resolve_theme("Nonsense", {}),
                         dict(gridwyrm.THEMES["Dark"]))

    def test_text_on_highlight_stays_readable(self):
        for name in gridwyrm.THEME_ORDER:
            gridwyrm.apply_palette(gridwyrm.resolve_theme(name, {}))
            with self.subTest(theme=name):
                gap = abs(gridwyrm.luminance(gridwyrm.ONHILITE)
                          - gridwyrm.luminance(gridwyrm.HILITE))
                self.assertGreater(gap, 0.35)
        gridwyrm.apply_palette(gridwyrm.THEMES["Dark"])


class Hotkeys(unittest.TestCase):

    def test_every_action_has_a_default(self):
        for action, _label, _repeat in gridwyrm.ACTIONS:
            self.assertIn(action, gridwyrm.DEFAULT_HOTKEYS)

    def test_defaults_use_several_modifiers(self):
        """A single modifier is too likely to be claimed by another program."""
        for action, pair in gridwyrm.DEFAULT_HOTKEYS.items():
            with self.subTest(action=action):
                self.assertGreaterEqual(pair[0].count("+"), 1)
                self.assertIn(pair[0], gridwyrm.MODIFIER_CHOICES)
                self.assertIn(pair[1], gridwyrm.VK_MAP)

    def test_every_offered_key_resolves(self):
        for key in gridwyrm.KEY_ORDER:
            self.assertIn(key, gridwyrm.VK_MAP)

    def test_empty_settings_give_defaults(self):
        result = gridwyrm.normalise_hotkeys({}, 0)
        self.assertEqual(result["toggle"],
                         list(gridwyrm.DEFAULT_HOTKEYS["toggle"]))

    def test_superseded_defaults_are_upgraded(self):
        """An old default was never a choice, so it may be replaced."""
        stale = {"toggle": ["Ctrl + Alt", "G"]}
        result = gridwyrm.normalise_hotkeys(stale, 0)
        self.assertEqual(result["toggle"],
                         list(gridwyrm.DEFAULT_HOTKEYS["toggle"]))

    def test_a_real_choice_is_kept(self):
        chosen = {"toggle": ["Ctrl + Win", "F9"]}
        result = gridwyrm.normalise_hotkeys(chosen, 0)
        self.assertEqual(result["toggle"], ["Ctrl + Win", "F9"])

    def test_switched_off_stays_off(self):
        result = gridwyrm.normalise_hotkeys(
            {"cycle_shape": [gridwyrm.HOTKEY_OFF, ""]}, 0)
        self.assertEqual(result["cycle_shape"][0], gridwyrm.HOTKEY_OFF)

    def test_current_file_is_left_alone(self):
        result = gridwyrm.normalise_hotkeys(
            gridwyrm.DEFAULT_HOTKEYS, gridwyrm.HOTKEY_DEFAULTS_VERSION)
        self.assertEqual(result,
                         {k: list(v)
                          for k, v in gridwyrm.DEFAULT_HOTKEYS.items()})

    def test_junk_is_survivable(self):
        for bad in ({"toggle": "Ctrl+Alt+G"}, {"toggle": ["only one"]},
                    {"toggle": ["Hyper", "G"]}, {"toggle": ["Ctrl + Alt", "??"]},
                    "not a dict", None):
            with self.subTest(bad=bad):
                result = gridwyrm.normalise_hotkeys(bad, 0)
                self.assertEqual(len(result), len(gridwyrm.ACTIONS))


class Settings(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.saved = {key: os.environ.get(key)
                      for key in ("APPDATA", "XDG_CONFIG_HOME")}
        os.environ["APPDATA"] = self.folder
        os.environ["XDG_CONFIG_HOME"] = self.folder

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_round_trip(self):
        data = {"cell": 63.5, "colour": "#E2483D", "off_x": 12.0,
                "theme": "Custom", "start_minimised": True}
        gridwyrm.save_settings(data)
        self.assertEqual(gridwyrm.load_settings(), data)

    def test_missing_file_is_not_an_error(self):
        os.environ["APPDATA"] = os.path.join(self.folder, "nothing-here")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.folder, "nothing-here")
        self.assertEqual(gridwyrm.load_settings(), {})

    def test_damaged_file_is_not_an_error(self):
        path = gridwyrm.settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{this is not json")
        self.assertEqual(gridwyrm.load_settings(), {})

    def test_logs_sit_beside_the_settings(self):
        self.assertEqual(os.path.dirname(gridwyrm.log_path("session.log")),
                         os.path.dirname(gridwyrm.settings_path()))


class SampleMap(unittest.TestCase):

    def test_texture_is_repeatable(self):
        """A shimmering preview while dragging a slider would be worse than none."""
        first = [gridwyrm.deterministic_noise(i) for i in range(32)]
        second = [gridwyrm.deterministic_noise(i) for i in range(32)]
        self.assertEqual(first, second)

    def test_noise_stays_in_range(self):
        for i in range(0, 5000, 7):
            value = gridwyrm.deterministic_noise(i)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


class TwoNames(unittest.TestCase):
    """gridwyrm.py and gridwyrm.pyw are the same program under two names.

    Windows chooses the interpreter from the extension: .pyw gets pythonw.exe
    and no console window, .py gets python.exe and keeps one. An earlier attempt
    used a small .pyw launcher that imported the .py, which was fragile, because
    Windows also treats .pyw as an importable source extension and the launcher
    could import itself. Holding the same code under both names is duller and it
    works. This test is what stops the two drifting apart unnoticed.
    """

    def test_the_two_files_are_identical(self):
        here = os.path.dirname(os.path.abspath(__file__))
        plain = os.path.join(here, "gridwyrm.py")
        windowless = os.path.join(here, "gridwyrm.pyw")
        if not (os.path.exists(plain) and os.path.exists(windowless)):
            self.skipTest("both gridwyrm.py and gridwyrm.pyw must be present")
        with open(plain, "rb") as first, open(windowless, "rb") as second:
            self.assertEqual(
                first.read(), second.read(),
                "gridwyrm.py and gridwyrm.pyw have drifted apart. "
                "Copy whichever one you changed over the other.")


if __name__ == "__main__":
    unittest.main(verbosity=2)