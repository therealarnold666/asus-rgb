import unittest

from asus_rgb.cli import colour


class ColourTests(unittest.TestCase):
    def test_parses_hex_colour(self):
        self.assertEqual(colour("#ff5500"), (255, 85, 0))


    def test_rejects_bad_colour(self):
        with self.assertRaises(Exception):
            colour("red")
