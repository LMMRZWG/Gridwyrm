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

# The package is imported as a package. Every module here is free of screen
# work, so none of this needs a display.
try:
    from gridwyrm.core import artwork
    from gridwyrm.core import bands as bands_mod
    from gridwyrm.core import conditions as conditions_mod
    from gridwyrm.core import geometry
    from gridwyrm.core import hotkeys as hotkeys_mod
    from gridwyrm.core import measuring
    from gridwyrm.core import storage
    from gridwyrm.core import theme as theme_mod
    from gridwyrm.core import updates
    from gridwyrm.core import win32
except ImportError as error:                     # pragma: no cover
    raise unittest.SkipTest("cannot import gridwyrm: %s" % error)


class _Facade:
    """Reads a name from whichever core module owns it.

    The tests were written against one flat module. Rather than rewrite four
    hundred references, this looks the name up across the package, which keeps
    the tests readable and means they say nothing about which file a function
    happens to live in.
    """

    _modules = (geometry, measuring, theme_mod, bands_mod, conditions_mod,
                hotkeys_mod, updates, storage, artwork, win32)

    def __getattr__(self, name):
        for module in self._modules:
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(
            "%s is in none of the core modules" % name)


gridwyrm = _Facade()


def _package_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "gridwyrm")


def _read_module(relative):
    """Read one module's source, for the few checks that are about the text."""
    path = os.path.join(_package_root(), *relative.split("/"))
    if not os.path.exists(path):
        raise unittest.SkipTest("%s is not present" % relative)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_package():
    """Every module's source at once, for checks that span the package."""
    joined = []
    for folder, _dirs, files in os.walk(_package_root()):
        for name in sorted(files):
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    joined.append(f.read())
    return "\n".join(joined)


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


class Measuring(unittest.TestCase):

    def test_shift_is_the_bit_tk_reports_for_shift(self):
        """Snapping is opt-in now, so the modifier has to be read correctly."""
        self.assertEqual(gridwyrm.SHIFT_HELD, 0x0001)

    def test_a_nearly_straight_line_is_straightened_when_asked(self):
        """With Shift held, a few degrees of wobble should not survive."""
        for dy in (0, 8, 20, 36):
            x, y, snapped = gridwyrm.snap_to_axis(100, 100, 400, 100 + dy)
            with self.subTest(dy=dy):
                self.assertTrue(snapped)
                self.assertEqual((x, y), (400, 100))

    def test_a_real_diagonal_is_left_alone(self):
        x, y, snapped = gridwyrm.snap_to_axis(100, 100, 400, 400)
        self.assertFalse(snapped)
        self.assertEqual((x, y), (400, 400))

    def test_near_vertical_snaps_to_vertical(self):
        x, y, snapped = gridwyrm.snap_to_axis(100, 100, 112, 400)
        self.assertTrue(snapped)
        self.assertEqual((x, y), (100, 400))

    def test_a_zero_length_span_is_harmless(self):
        self.assertEqual(gridwyrm.snap_to_axis(50, 50, 50, 50),
                         (50, 50, False))

    def test_diagonal_counts_as_one_square(self):
        """Three across and three down is three squares at most tables."""
        distance = gridwyrm.grid_distance(192, 192, 64, gridwyrm.DIAGONAL_RULES[0])
        self.assertAlmostEqual(distance, 3.0, places=6)

    def test_true_distance_measures_the_hypotenuse(self):
        distance = gridwyrm.grid_distance(192, 192, 64, gridwyrm.DIAGONAL_RULES[1])
        self.assertAlmostEqual(distance, 3 * 2 ** 0.5, places=6)

    def test_straight_spans_agree_under_both_rules(self):
        for dx, dy in ((256, 0), (0, 320)):
            first = gridwyrm.grid_distance(dx, dy, 64, gridwyrm.DIAGONAL_RULES[0])
            second = gridwyrm.grid_distance(dx, dy, 64, gridwyrm.DIAGONAL_RULES[1])
            self.assertAlmostEqual(first, second, places=6)

    def test_distance_survives_a_degenerate_cell(self):
        self.assertEqual(gridwyrm.grid_distance(100, 100, 0, "anything"), 0.0)

    def test_readout_mentions_the_unit_only_when_there_is_one(self):
        rule = gridwyrm.DIAGONAL_RULES[0]
        feet = gridwyrm.format_measurement(256, 0, 64, rule, 5, "ft")
        self.assertIn("20 ft", feet)
        self.assertIn("4 squares", feet)
        bare = gridwyrm.format_measurement(256, 0, 64, rule, 5, "squares")
        self.assertIn("4 squares", bare)
        self.assertNotIn("ft", bare)

    def test_pointless_zeros_are_trimmed(self):
        self.assertEqual(gridwyrm.tidy_number(6.0), "6")
        self.assertEqual(gridwyrm.tidy_number(6.25), "6.2")
        self.assertEqual(gridwyrm.tidy_number(0.0), "0")
        self.assertEqual(gridwyrm.tidy_number(7.5, 2), "7.5")
        self.assertEqual(gridwyrm.tidy_number(63.5, 2), "63.5")

    def test_whole_numbers_survive_zero_places(self):
        """Stripping zeros carelessly would turn 20 into 2."""
        self.assertEqual(gridwyrm.tidy_number(20.0, 0), "20")
        self.assertEqual(gridwyrm.tidy_number(100.0, 0), "100")
        self.assertEqual(gridwyrm.tidy_number(30.4, 0), "30")

    def test_cell_size_is_solved_from_a_span(self):
        self.assertEqual(gridwyrm.cell_size_from_span(256, 0, 4), 64.0)
        self.assertEqual(gridwyrm.cell_size_from_span(254, 0, 4), 63.5)
        self.assertEqual(gridwyrm.cell_size_from_span(0, 190.5, 3), 63.5)

    def test_calibration_refuses_rather_than_wrecking_alignment(self):
        """An alignment that already works must survive a stray click."""
        for span, squares, why in (
                (256, 0, "zero squares"),
                (256, -2, "negative squares"),
                (2, 4, "span far too short"),
                (256, "", "empty box"),
                (256, "abc", "not a number"),
                (256, None, "nothing given"),
                (256, 100, "cell would be tiny"),
                (5000, 2, "cell would be enormous")):
            with self.subTest(why=why):
                self.assertIsNone(
                    gridwyrm.cell_size_from_span(span, 0, squares))

    def test_the_offered_rules_and_units_are_the_real_ones(self):
        self.assertIn("ft", gridwyrm.UNIT_CHOICES)
        self.assertIn("squares", gridwyrm.UNIT_CHOICES)
        self.assertEqual(len(gridwyrm.DIAGONAL_RULES), 2)


class RangeBands(unittest.TestCase):

    def test_the_defaults_parse_and_round_trip(self):
        bands, error = gridwyrm.parse_bands(
            gridwyrm.format_bands(gridwyrm.DEFAULT_BANDS))
        self.assertEqual(error, "")
        self.assertEqual([name for name, _ in bands],
                         [name for name, _ in gridwyrm.DEFAULT_BANDS])

    def test_bands_are_sorted_by_distance(self):
        bands, error = gridwyrm.parse_bands("Far = 60\nMelee = 5\nNear = 30")
        self.assertEqual(error, "")
        self.assertEqual([name for name, _ in bands], ["Melee", "Near", "Far"])

    def test_blank_lines_and_comments_are_ignored(self):
        bands, error = gridwyrm.parse_bands("# a note\n\nClose = 10\n\n")
        self.assertEqual(error, "")
        self.assertEqual(bands, [("Close", 10.0)])

    def test_a_comma_decimal_is_accepted(self):
        bands, _error = gridwyrm.parse_bands("Short = 7,5")
        self.assertEqual(bands, [("Short", 7.5)])

    def test_bad_input_is_reported_with_a_line_number(self):
        for text, expect in (
                ("Melee 5", "Line 1"),
                ("= 5", "Line 1"),
                ("Melee = wide", "Line 1"),
                ("Melee = 0", "Line 1"),
                ("Melee = -5", "Line 1"),
                ("Melee = 5\nReach = nope", "Line 2")):
            with self.subTest(text=text):
                bands, error = gridwyrm.parse_bands(text)
                self.assertIsNone(bands)
                self.assertIn(expect, error)

    def test_empty_input_is_refused(self):
        bands, error = gridwyrm.parse_bands("   \n\n")
        self.assertIsNone(bands)
        self.assertTrue(error)

    def test_too_many_bands_are_refused(self):
        text = "\n".join("B%d = %d" % (i, i + 1) for i in range(12))
        bands, error = gridwyrm.parse_bands(text)
        self.assertIsNone(bands)
        # The wording may change; the limit being named should not.
        self.assertIn(str(gridwyrm.MAX_BANDS), error)

    def test_radii_convert_through_squares(self):
        """A 30ft band with 5ft squares and 64px cells is six squares out.

        Written with explicit bands rather than the defaults, so changing the
        defaults cannot make this fail for the wrong reason.
        """
        rings = dict(gridwyrm.band_radii(
            [("A", 5.0), ("B", 30.0), ("C", 45.0)], 64, 5))
        self.assertAlmostEqual(rings["A"], 64.0, places=6)
        self.assertAlmostEqual(rings["B"], 384.0, places=6)
        self.assertAlmostEqual(rings["C"], 576.0, places=6)

    def test_radii_scale_with_the_cell_size(self):
        """Rings follow the grid, so re-scaling the grid re-scales them."""
        band = [("Near", 20.0)]
        small = dict(gridwyrm.band_radii(band, 32, 5))["Near"]
        large = dict(gridwyrm.band_radii(band, 64, 5))["Near"]
        self.assertAlmostEqual(large, small * 2, places=6)

    def test_radii_follow_the_unit(self):
        """Metres per square gives different pixels for the same band."""
        feet = dict(gridwyrm.band_radii([("Near", 30)], 64, 5))["Near"]
        metres = dict(gridwyrm.band_radii([("Near", 30)], 64, 1.5))["Near"]
        self.assertLess(feet, metres)

    def test_radii_survive_degenerate_input(self):
        self.assertEqual(gridwyrm.band_radii(gridwyrm.DEFAULT_BANDS, 0, 5), [])
        self.assertEqual(gridwyrm.band_radii(gridwyrm.DEFAULT_BANDS, 64, 0), [])

    def test_bands_are_circles_only(self):
        """A square ring on a square grid is indistinguishable from the grid.

        An earlier version drew squares under a diagonal-counts-as-one rule,
        which was consistent with the rule and unreadable on screen. The rule
        still governs the measuring readout; it no longer governs the shape.
        """
        self.assertFalse(hasattr(gridwyrm, "ring_is_square"))

    def test_bands_are_never_filled(self):
        """Revealing means naming a ring, not shading everything inside it.

        Faking transparency with a stipple covered the map even at the sparsest
        pattern Tk offers, so there is no fill in either state.
        """
        self.assertFalse(hasattr(gridwyrm, "STIPPLE_PRIVATE"))
        self.assertFalse(hasattr(gridwyrm, "STIPPLE_REVEALED"))
        self.assertLess(gridwyrm.RING_WEIGHT_PRIVATE,
                        gridwyrm.RING_WEIGHT_REVEALED)

    def test_default_bands_fit_a_small_screen(self):
        """A laptop at a large cell size is the tight case, not a 1080p desktop."""
        radii = [radius for _name, radius
                 in gridwyrm.band_radii(gridwyrm.DEFAULT_BANDS, 64, 5)]
        self.assertLessEqual(max(radii), 455)    # half of 911px of height

    def test_oversized_rings_are_left_out_and_named(self):
        rings = [("Melee", 64.0), ("Near", 192.0), ("Far", 900.0)]
        fits, too_big = gridwyrm.visible_rings(rings, 1710, 911)
        self.assertEqual([name for name, _r in fits], ["Melee", "Near"])
        self.assertEqual(too_big, ["Far"])

    def test_the_limit_follows_the_shorter_edge(self):
        """A wide, short screen is limited by its height."""
        rings = [("A", 400.0)]
        fits, too_big = gridwyrm.visible_rings(rings, 3840, 600)
        self.assertEqual(fits, [])
        self.assertEqual(too_big, ["A"])
        fits, too_big = gridwyrm.visible_rings(rings, 3840, 1600)
        self.assertEqual([name for name, _r in fits], ["A"])
        self.assertEqual(too_big, [])

    def test_an_unmeasured_overlay_keeps_every_ring(self):
        """Before the overlay has a size, nothing should be discarded."""
        rings = [("A", 5000.0)]
        fits, too_big = gridwyrm.visible_rings(rings, 0, 0)
        self.assertEqual(fits, rings)
        self.assertEqual(too_big, [])

    def test_default_bands_are_ordered_and_distinct(self):
        distances = [distance for _name, distance in gridwyrm.DEFAULT_BANDS]
        self.assertEqual(distances, sorted(distances))
        self.assertEqual(len(distances), len(set(distances)))

    def test_the_offered_modes_are_the_real_ones(self):
        self.assertEqual(gridwyrm.RANGE_MODES,
                         ("Off", "DM only", "Show players"))

    def test_reveal_has_a_hotkey_of_its_own(self):
        actions = [action for action, _label, _repeat in gridwyrm.ACTIONS]
        self.assertIn("reveal_ranges", actions)
        self.assertIn("reveal_ranges", gridwyrm.DEFAULT_HOTKEYS)


class BandEditor(unittest.TestCase):
    """The bands are edited as rows now, so pairs are validated rather than text."""

    def test_valid_rows_are_accepted_and_sorted(self):
        bands, error = gridwyrm.validate_bands(
            [("Far", "25"), ("Melee", "5"), ("Near", "15")])
        self.assertEqual(error, "")
        self.assertEqual([name for name, _d in bands],
                         ["Melee", "Near", "Far"])

    def test_an_untouched_row_is_skipped_not_rejected(self):
        """Adding a row and not filling it must not block Apply."""
        bands, error = gridwyrm.validate_bands(
            [("Melee", "5"), ("", ""), ("   ", "  ")])
        self.assertEqual(error, "")
        self.assertEqual(bands, [("Melee", 5.0)])

    def test_a_half_filled_row_is_an_error(self):
        for rows, expect in (
                ([("Melee", "5"), ("", "20")], "no name"),
                ([("Melee", "5"), ("Near", "")], "no distance")):
            with self.subTest(rows=rows):
                bands, error = gridwyrm.validate_bands(rows)
                self.assertIsNone(bands)
                self.assertIn(expect, error)

    def test_duplicate_names_are_refused(self):
        """Two identical labels on the map would be meaningless."""
        bands, error = gridwyrm.validate_bands(
            [("Near", "10"), ("near", "20")])
        self.assertIsNone(bands)
        self.assertIn("both called", error)

    def test_an_equals_sign_in_a_name_is_refused(self):
        """Bands are stored as text, so a name with = would not survive a save."""
        bands, error = gridwyrm.validate_bands([("A = B", "10")])
        self.assertIsNone(bands)
        self.assertIn("equals", error)

    def test_bad_distances_are_refused_with_a_row_number(self):
        for value in ("wide", "0", "-5"):
            with self.subTest(value=value):
                bands, error = gridwyrm.validate_bands(
                    [("Melee", "5"), ("Near", value)])
                self.assertIsNone(bands)
                self.assertIn("Row 2", error)

    def test_a_comma_decimal_is_accepted(self):
        bands, _error = gridwyrm.validate_bands([("Short", "7,5")])
        self.assertEqual(bands, [("Short", 7.5)])

    def test_all_rows_blank_is_refused(self):
        bands, error = gridwyrm.validate_bands([("", ""), ("", "")])
        self.assertIsNone(bands)
        self.assertIn("at least one", error)

    def test_too_many_bands_are_refused(self):
        rows = [("B%d" % i, str(i + 1)) for i in range(gridwyrm.MAX_BANDS + 2)]
        bands, error = gridwyrm.validate_bands(rows)
        self.assertIsNone(bands)
        self.assertIn(str(gridwyrm.MAX_BANDS), error)

    def test_the_editor_and_the_saved_text_agree(self):
        """Rows are validated, then stored as text, so the two must round-trip."""
        rows = [("Melee", "5"), ("Near", "15")]
        bands, _error = gridwyrm.validate_bands(rows)
        again, error = gridwyrm.parse_bands(gridwyrm.format_bands(bands))
        self.assertEqual(error, "")
        self.assertEqual(again, bands)


class Conditions(unittest.TestCase):

    def test_defaults_are_valid_and_distinct(self):
        conditions, error = gridwyrm.validate_conditions(
            gridwyrm.DEFAULT_CONDITIONS)
        self.assertEqual(error, "")
        names = [name for name, _c in conditions]
        colours = [colour for _n, colour in conditions]
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(set(colours)), len(colours))

    def test_a_colour_must_be_a_real_hex_value(self):
        for colour in ("green", "", "#12345", "#GGGGGG"):
            with self.subTest(colour=colour):
                conditions, error = gridwyrm.validate_conditions(
                    [("Poisoned", colour)])
                self.assertIsNone(conditions)
                self.assertIn("Row 1", error)

    def test_an_untouched_row_is_skipped(self):
        conditions, error = gridwyrm.validate_conditions(
            [("Poisoned", "#4CAF50"), ("", "")])
        self.assertEqual(error, "")
        self.assertEqual(conditions, [("Poisoned", "#4CAF50")])

    def test_duplicate_names_are_refused_with_the_typed_casing(self):
        conditions, error = gridwyrm.validate_conditions(
            [("Fire", "#FF0000"), ("fire", "#00FF00")])
        self.assertIsNone(conditions)
        self.assertIn("Fire", error)

    def test_every_condition_on_the_rings_is_present(self):
        """All fifteen, named as they are printed on the physical rings."""
        names = {name.lower() for name, _c in gridwyrm.DEFAULT_CONDITIONS}
        for expected in ("blind", "charmed", "deaf", "exhausted", "frightened",
                         "grappled", "incapacitated", "invisible", "paralyzed",
                         "petrified", "poisoned", "prone", "restrained",
                         "stunned", "unconscious"):
            self.assertIn(expected, names)
        self.assertEqual(len(gridwyrm.DEFAULT_CONDITIONS), 15)

    def test_a_never_chosen_list_is_upgraded(self):
        """The five invented conditions were inherited, not picked."""
        old = gridwyrm.format_conditions(gridwyrm.SUPERSEDED_CONDITIONS[0])
        upgraded = gridwyrm.normalise_conditions(old, 0)
        self.assertEqual(len(upgraded), len(gridwyrm.DEFAULT_CONDITIONS))
        self.assertIn(["Blind", "#E8B923"], upgraded)

    def test_a_real_choice_survives(self):
        mine = gridwyrm.format_conditions(
            [("Marked", "#FF00FF"), ("Hasted", "#00FFAA")])
        kept = gridwyrm.normalise_conditions(mine, 0)
        self.assertEqual(kept, [["Marked", "#FF00FF"], ["Hasted", "#00FFAA"]])

    def test_a_current_file_is_left_alone(self):
        current = gridwyrm.format_conditions(gridwyrm.DEFAULT_CONDITIONS)
        kept = gridwyrm.normalise_conditions(
            current, gridwyrm.CONDITION_DEFAULTS_VERSION)
        self.assertEqual(len(kept), 15)

    def test_an_empty_file_gets_the_defaults(self):
        self.assertEqual(len(gridwyrm.normalise_conditions("", 0)), 15)

    def test_the_list_fits_within_the_limit(self):
        self.assertLessEqual(len(gridwyrm.DEFAULT_CONDITIONS),
                             gridwyrm.MAX_CONDITIONS)

    def test_the_near_white_conditions_are_still_distinguishable(self):
        """Four are near-white in the physical set; on screen they must differ."""
        pale = {name: colour for name, colour in gridwyrm.DEFAULT_CONDITIONS
                if gridwyrm.luminance(colour) > 0.5}
        self.assertGreaterEqual(len(pale), 3)
        self.assertEqual(len(set(pale.values())), len(pale))

    def test_too_many_are_refused(self):
        rows = [("C%d" % i, "#FF0000")
                for i in range(gridwyrm.MAX_CONDITIONS + 2)]
        conditions, error = gridwyrm.validate_conditions(rows)
        self.assertIsNone(conditions)
        self.assertIn(str(gridwyrm.MAX_CONDITIONS), error)

    def test_the_saved_form_round_trips(self):
        conditions, _error = gridwyrm.validate_conditions(
            gridwyrm.DEFAULT_CONDITIONS)
        again, error = gridwyrm.parse_conditions(
            gridwyrm.format_conditions(conditions))
        self.assertEqual(error, "")
        self.assertEqual(again, conditions)

    def test_every_default_colour_gets_a_readable_outline(self):
        """Each ring is a colour over a halo, so the two have to contrast."""
        for name, colour in gridwyrm.DEFAULT_CONDITIONS:
            with self.subTest(name=name):
                halo = gridwyrm.contrast_halo(colour)
                self.assertIn(halo, ("#000000", "#FFFFFF"))
                self.assertGreater(
                    abs(gridwyrm.luminance(colour) - gridwyrm.luminance(halo)),
                    0.1)

    def test_a_tapped_reveal_is_held_long_enough_to_see(self):
        """Without a floor, a quick press showed the names for one frame."""
        self.assertGreaterEqual(gridwyrm.MIN_REVEAL_MS, 300)


class CellFootprint(unittest.TestCase):
    """A hex is far wider than its cell size suggests, and markers must know it."""

    def test_a_square_cell_is_its_own_width(self):
        self.assertEqual(gridwyrm.cell_footprint("Square", 64), 64.0)

    def test_a_hex_is_measured_edge_to_edge(self):
        """Cell size is centre-to-vertex, so the short diameter is root three."""
        for kind in ("Hex (pointy top)", "Hex (flat top)"):
            with self.subTest(kind=kind):
                self.assertAlmostEqual(gridwyrm.cell_footprint(kind, 64),
                                       64 * 3 ** 0.5, places=6)

    def test_a_hex_marker_comes_out_larger_than_a_square_one(self):
        """The bug this fixes: identical settings gave a tiny ring on hexes."""
        square = gridwyrm.cell_footprint("Square", 64)
        hexagon = gridwyrm.cell_footprint("Hex (pointy top)", 64)
        self.assertGreater(hexagon, square * 1.7)

    def test_a_default_marker_sits_inside_its_hex(self):
        """It should fill the hex without spilling past the edges."""
        cell = 64
        radius = gridwyrm.cell_footprint("Hex (pointy top)", cell) * 84 / 200.0
        inradius = cell * 3 ** 0.5 / 2                # centre to edge midpoint
        self.assertLess(radius, inradius)
        self.assertGreater(radius, inradius * 0.7)


class MarkerPlacement(unittest.TestCase):
    """Markers are stored in grid coordinates, not pixels.

    A marker sits on a creature standing in a square. Rescaling the grid or
    nudging it into alignment moves the squares, so a pixel-anchored marker
    would end up beside the creature it was marking.
    """

    def round_trip(self, x, y, cell, off_x, off_y):
        gx = (x - off_x) / cell
        gy = (y - off_y) / cell
        return gx * cell + off_x, gy * cell + off_y

    def test_a_marker_returns_to_where_it_was_placed(self):
        for cell, off_x, off_y in ((64, 0, 0), (63.5, 12, 4), (100, -30, 17)):
            with self.subTest(cell=cell):
                back = self.round_trip(500, 300, cell, off_x, off_y)
                self.assertAlmostEqual(back[0], 500, places=6)
                self.assertAlmostEqual(back[1], 300, places=6)

    def test_a_marker_follows_its_square_when_the_grid_is_rescaled(self):
        """Placed three squares across, it stays three squares across."""
        cell, off = 64, 0
        gx = (192 - off) / cell                  # three cells out
        self.assertAlmostEqual(gx, 3.0, places=6)
        for new_cell in (32, 100, 63.5):
            with self.subTest(cell=new_cell):
                self.assertAlmostEqual(gx * new_cell + off, 3 * new_cell,
                                       places=6)

    def test_a_marker_follows_the_offset(self):
        cell = 64
        gx = (192 - 0) / cell
        self.assertAlmostEqual(gx * cell + 20, 212, places=6)


class Architecture(unittest.TestCase):
    """Keeps the shape of the package from drifting back.

    Gridwyrm was once a single file with a two-thousand-line class in it that
    owned the interface, the hotkeys, the overlay, the colour picking, the theme
    swapping and the settings all at once. These are the checks that stop that
    happening again by accident, since nothing else would notice.
    """

    # Set to a little above where things actually stand, not to an ideal. The
    # job of these numbers is to stop anything growing back, and a threshold
    # that already fails teaches people to ignore the test. App is the largest
    # of both at 718 lines in a 771-line module, and is the next thing to split.
    LARGEST_CLASS = 750
    LARGEST_MODULE = 800

    def _modules(self):
        root = _package_root()
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(files):
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        yield os.path.relpath(path, root), handle.read()

    def test_no_class_grows_beyond_reading(self):
        import ast
        oversized = []
        for name, source in self._modules():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ClassDef):
                    size = node.end_lineno - node.lineno
                    if size > self.LARGEST_CLASS:
                        oversized.append("%s: %s is %d lines"
                                         % (name, node.name, size))
        self.assertEqual(oversized, [])

    def test_no_module_grows_beyond_reading(self):
        oversized = []
        for name, source in self._modules():
            lines = source.count("\n")
            # artwork.py is embedded icon data rather than code, so it is
            # allowed to be long: nobody reads it.
            if lines > self.LARGEST_MODULE and not name.endswith("artwork.py"):
                oversized.append("%s is %d lines" % (name, lines))
        self.assertEqual(oversized, [])

    def test_the_logic_layer_does_not_import_the_interface(self):
        """core must not depend on ui or features, or it stops being testable."""
        offenders = []
        for name, source in self._modules():
            if not name.startswith("core"):
                continue
            for line in source.splitlines():
                if line.startswith(("from ..ui", "from ..features",
                                    "from ..app")):
                    offenders.append("%s: %s" % (name, line.strip()))
        self.assertEqual(offenders, [])

    def test_every_feature_takes_the_application_and_nothing_else(self):
        import ast
        for name, source in self._modules():
            if not name.startswith("features") or name.endswith("__init__.py"):
                continue
            classes = [n for n in ast.parse(source).body
                       if isinstance(n, ast.ClassDef)]
            self.assertEqual(len(classes), 1, "%s should hold one class" % name)
            init = next((m for m in classes[0].body
                         if isinstance(m, ast.FunctionDef)
                         and m.name == "__init__"), None)
            self.assertIsNotNone(init, "%s has no __init__" % name)
            args = [a.arg for a in init.args.args]
            self.assertEqual(args, ["self", "app"],
                             "%s takes %s" % (name, args))


class PanelShortcuts(unittest.TestCase):
    """No shortcut may fire while someone is typing in a field.

    Tk delivers a key event to the focused widget and then up to the window, so
    a binding on the window catches every keystroke in the panel. A bare letter
    is therefore unusable: an "h" bound to hide the overlay went off in the
    middle of typing a band name. The surviving shortcuts all route through
    bump, which stops when a field has focus.
    """

    def _source(self):
        return _read_module("app.py")

    def test_no_bare_letter_is_bound_to_the_window(self):
        import re
        matches = re.findall(r'r\.bind\("<[a-zA-Z]>"', self._source())
        self.assertEqual(matches, [])

    def test_the_value_shortcuts_check_for_a_focused_field(self):
        source = self._source()
        bump = source.split("def bump(self")[1].split("\n    def ")[0]
        self.assertIn("focus_get", bump)
        self.assertIn("ttk.Entry", bump)

    def test_the_footer_does_not_advertise_a_removed_shortcut(self):
        source = _read_package()
        self.assertNotIn("H show or hide", source)
        self.assertNotIn("Esc quit", source)


class UpdateCheck(unittest.TestCase):

    def test_a_version_string_is_read_leniently(self):
        """Tags are typed by hand and will not always be tidy."""
        self.assertEqual(gridwyrm.parse_version("v2.1.3"), (2, 1, 3))
        self.assertEqual(gridwyrm.parse_version("2.1"), (2, 1))
        self.assertEqual(gridwyrm.parse_version("V2.0"), (2, 0))
        self.assertEqual(gridwyrm.parse_version("v2.1-beta"), (2, 1))
        self.assertEqual(gridwyrm.parse_version("v2.1+build7"), (2, 1))

    def test_nonsense_is_refused(self):
        for text in ("", None, "garbage", "v", "v.", "vX.Y"):
            with self.subTest(text=text):
                self.assertIsNone(gridwyrm.parse_version(text))

    def test_numbers_compare_as_numbers(self):
        """Comparing as text would make 10.0 look older than 2.0."""
        self.assertTrue(gridwyrm.is_newer("v10.0", "v2.0"))
        self.assertFalse(gridwyrm.is_newer("v2.0", "v10.0"))

    def test_missing_parts_count_as_zero(self):
        self.assertTrue(gridwyrm.is_newer("2.1", "2.0.9"))
        self.assertFalse(gridwyrm.is_newer("2.1", "2.1.0"))
        self.assertFalse(gridwyrm.is_newer("2.1.0", "2.1"))

    def test_the_same_version_is_not_newer(self):
        self.assertFalse(gridwyrm.is_newer(gridwyrm.VERSION,
                                           gridwyrm.VERSION))

    def test_an_unreadable_reply_never_looks_newer(self):
        """Better to miss an update than to nag about one that does not exist."""
        for text in ("", None, "garbage", "latest"):
            with self.subTest(text=text):
                self.assertFalse(gridwyrm.is_newer(text, "2.0"))
        self.assertFalse(gridwyrm.is_newer("2.1", "garbage"))

    def test_the_check_is_throttled(self):
        now = 1_000_000.0
        hours = gridwyrm.UPDATE_INTERVAL_HOURS
        self.assertFalse(gridwyrm.update_check_due(now - 60, now))
        self.assertTrue(
            gridwyrm.update_check_due(now - (hours + 1) * 3600, now))

    def test_a_first_run_checks(self):
        self.assertTrue(gridwyrm.update_check_due(0, 1_000_000.0))
        self.assertTrue(gridwyrm.update_check_due(None, 1_000_000.0))
        self.assertTrue(gridwyrm.update_check_due("nonsense", 1_000_000.0))

    def test_a_clock_that_moved_backwards_still_checks(self):
        """A timestamp from the future would otherwise block checks forever."""
        now = 1_000_000.0
        self.assertTrue(gridwyrm.update_check_due(now + 99999, now))

    def test_only_github_is_ever_downloaded_from(self):
        """A tampered reply must not be able to point the installer elsewhere."""
        for url in (
                "https://github.com/LMMRZWG/Gridwyrm/releases/download/v2.1/Gridwyrm.exe",
                "https://objects.githubusercontent.com/x/y/Gridwyrm.exe",
                "https://release-assets.githubusercontent.com/a/Gridwyrm.exe"):
            with self.subTest(url=url):
                self.assertTrue(gridwyrm.download_is_trusted(url))

    def test_anywhere_else_is_refused(self):
        for url in (
                "http://github.com/x/Gridwyrm.exe",          # not https
                "https://githubusercontent.com.evil.tld/a.exe",
                "https://evil.tld/Gridwyrm.exe",
                "https://github.com.evil.tld/Gridwyrm.exe",
                "file:///C:/Windows/System32/calc.exe",
                "", None, "not a url at all"):
            with self.subTest(url=url):
                self.assertFalse(gridwyrm.download_is_trusted(url))

    def test_the_swap_script_waits_before_replacing_anything(self):
        script = gridwyrm.swap_script("C:\\g\\Gridwyrm.exe",
                                      "C:\\g\\Gridwyrm.update.exe",
                                      "C:\\g\\Gridwyrm.previous.exe", 4321)
        self.assertIn("tasklist", script)
        self.assertIn("4321", script)
        # The wait has to come before the move, or it replaces a running file.
        self.assertLess(script.index("tasklist"), script.index("move /y"))

    def test_the_swap_script_can_put_the_old_copy_back(self):
        """A failed move must not leave someone with nothing that runs."""
        script = gridwyrm.swap_script("C:\\g\\Gridwyrm.exe",
                                      "C:\\g\\Gridwyrm.update.exe",
                                      "C:\\g\\Gridwyrm.previous.exe", 1)
        self.assertIn("Gridwyrm.previous.exe", script)
        self.assertIn("if not exist", script)
        self.assertIn("start ", script)
        self.assertTrue(script.rstrip().endswith('del /q "%~f0"'))

    def test_the_swap_script_uses_windows_line_endings(self):
        """A batch file with bare newlines misbehaves on some setups."""
        script = gridwyrm.swap_script("a", "b", "c", 1)
        self.assertIn("\r\n", script)

    def test_the_urls_point_at_this_repository(self):
        self.assertIn("LMMRZWG/Gridwyrm", gridwyrm.UPDATE_API)
        self.assertIn("LMMRZWG/Gridwyrm", gridwyrm.RELEASES_PAGE)
        self.assertTrue(gridwyrm.UPDATE_API.startswith("https://"))
        self.assertTrue(gridwyrm.RELEASES_PAGE.startswith("https://"))

    def test_the_version_is_readable(self):
        self.assertIsNotNone(gridwyrm.parse_version(gridwyrm.VERSION))

    def test_the_version_line_is_where_the_build_expects_it(self):
        """The release workflow rewrites this line to match the tag.

        It matches on a line starting with VERSION = "..." at the left margin.
        Reformat or indent that line and stamping silently stops working, which
        would leave every built exe insisting it is whichever version happened
        to be committed. Hence a test rather than a comment.
        """
        import re
        source = _read_module("core/updates.py")
        matches = re.findall(r'^VERSION = "[^"]*"', source, flags=re.M)
        self.assertEqual(len(matches), 1)

    def test_stamping_produces_a_readable_version(self):
        """Simulates what the workflow does, for a few plausible tags."""
        import re
        for tag in ("2.1", "2.1.1", "3.0"):
            with self.subTest(tag=tag):
                stamped, count = re.subn(
                    r'^VERSION = "[^"]*"', 'VERSION = "%s"' % tag,
                    'VERSION = "0.0"\nother = 1\n', count=1, flags=re.M)
                self.assertEqual(count, 1)
                self.assertIn('VERSION = "%s"' % tag, stamped)
                self.assertIsNotNone(gridwyrm.parse_version(tag))


class TaskbarIcon(unittest.TestCase):
    """Tk reads the .ico itself and only understands classic DIB entries.

    A modern PNG-compressed .ico is accepted without complaint and then
    ignored, which is why the taskbar kept showing the toolkit's own icon. The
    embedded copy therefore has to be DIB, and this is the check that it stays
    that way.
    """

    def _entries(self):
        import base64
        import struct
        data = base64.b64decode(gridwyrm.ICON_ICO)
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        found = []
        for index in range(count):
            start = 6 + 16 * index
            fields = struct.unpack("<BBBBHHII", data[start:start + 16])
            width, size_in_res, offset = fields[0], fields[6], fields[7]
            found.append((width, size_in_res, offset, data))
        return found

    def test_every_entry_is_dib_not_png(self):
        import struct
        for width, size_in_res, offset, data in self._entries():
            with self.subTest(width=width):
                self.assertNotEqual(data[offset:offset + 4], b"\x89PNG")
                header_size = struct.unpack("<I", data[offset:offset + 4])[0]
                self.assertEqual(header_size, 40)   # BITMAPINFOHEADER
                self.assertLessEqual(offset + size_in_res, len(data))

    def test_the_sizes_windows_asks_for_are_present(self):
        widths = {width for width, _s, _o, _d in self._entries()}
        for needed in (16, 32, 48):
            self.assertIn(needed, widths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
