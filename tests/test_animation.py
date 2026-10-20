import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from asus_rgb import animation,native

class AnimationTests(unittest.TestCase):
    def test_palette_parses_spaces_and_commas(self):
        self.assertEqual(animation.palette_values('#FF0000 #00ff00, #0000ff'),['ff0000','00ff00','0000ff'])
    def test_gradients_wrap_and_dim(self):
        colours=animation.frame(['ff0000','0000ff'],0,[0,.25,.5,.75,1],50)
        self.assertEqual(colours,[(128,0,0),(64,0,64),(0,0,128),(64,0,64),(128,0,0)])
    def test_speed_changes_phase_without_altering_palette(self):
        palette=['ff0000','0000ff'];elapsed=2
        self.assertNotEqual(animation.frame(palette,elapsed/8,[0],100),animation.frame(palette,elapsed/16,[0],100))
    def test_invalid_palette_and_speed_rejected(self):
        for colours,seconds in [(['ffffff'],8),(['xxxxxx','000000'],8),(['ffffff','000000'],0)]:
            with self.assertRaises(ValueError):animation.validate(colours,seconds)
    def test_custom_settings_survive_reload_and_mode_change(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(native,'CONFIG',Path(folder)/'profile.json'):
            native.save_profile((255,0,153),70,'rainbow',['00ffff','ff00ff'],6)
            self.assertEqual(native.load_profile()['palette'],['00ffff','ff00ff'])
            self.assertEqual(native.load_profile()['period'],6)
            native.save_profile((255,255,255),70,'static')
            self.assertEqual(native.load_profile()['palette'],['00ffff','ff00ff'])
    def test_memory_uses_byte_registers_in_rbg_order(self):
        with patch.object(animation.hardware,'write_reg') as write:
            animation.memory_write_colours(9,[(10,20,30)])
        self.assertEqual([c.args for c in write.call_args_list],[(9,0x8100,10),(9,0x8101,30),(9,0x8102,20)])
    def test_colour_packets_have_distinct_led_colours_and_commit(self):
        colours=animation.frame(['ff0000','0000ff'],0,[i/120 for i in range(120)],100)
        packets=list(animation.colour_packets(0,colours))
        self.assertEqual(len(packets),6)
        self.assertTrue(all(len(p)==65 for p in packets))
        self.assertEqual(packets[-1][2],0x80)
        self.assertNotEqual(packets[0][5:8],packets[0][8:11])
