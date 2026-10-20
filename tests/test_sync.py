import unittest
from unittest.mock import patch
from asus_rgb.native import Peripheral, restore_pending
from asus_rgb.hardware import direct_packets

class SyncRegressionTests(unittest.TestCase):
    def test_sleeping_mouse_does_not_reapply_other_devices(self):
        memory=Peripheral('/dev/i2c-10',0x71,10,'memory','RAM')
        mouse=Peripheral('/dev/hidraw11',3,0x1b69,'mouse','Mouse')
        profile={'colour':'0055ff','brightness':70,'mode':'static'}
        with patch('asus_rgb.native.apply_devices') as apply:
            apply.side_effect=[[(memory,None)],[(mouse,'asleep')]]
            cached,_=restore_pending([memory,mouse],profile,{})
        with patch('asus_rgb.native.apply_devices',return_value=[(mouse,None)]) as apply:
            cached,results=restore_pending([memory,mouse],profile,cached)
            self.assertEqual([d.kind for d,e in results],['mouse'])
            self.assertEqual(apply.call_args.args[0],[mouse])
        changed=dict(profile,colour='ffffff')
        with patch('asus_rgb.native.apply_devices') as apply:
            apply.side_effect=[[(memory,None)],[(mouse,None)]]
            _,results=restore_pending([memory,mouse],changed,cached)
            self.assertEqual(len(results),2)

    def test_direct_header_fills_every_led_and_applies_last_packet(self):
        packets=list(direct_packets(1,120,(20,40,80)))
        self.assertEqual([p[3] for p in packets],[0,20,40,60,80,100])
        self.assertEqual(sum(p[4] for p in packets),120)
        self.assertTrue(all(len(p)==65 for p in packets))
        self.assertTrue(all(p[2]==1 for p in packets[:-1]))
        self.assertEqual(packets[-1][2],0x81)

class ThroneRegressionTests(unittest.TestCase):
    def test_percent_brightness_converts_to_five_hardware_levels(self):
        from asus_rgb.hardware import throne_packet
        self.assertEqual([throne_packet((255,0,0),p,'static')[7] for p in (0,1,25,50,70,100)],
                         [0,1,1,2,3,4])

    def test_animated_mode_has_running_speed_and_valid_brightness(self):
        from asus_rgb.hardware import throne_packet
        packet=throne_packet((255,217,153),70,'cycle')
        self.assertEqual(packet[5:8],[4,127,3])
        self.assertEqual(packet[10:13],[0,0,0])

    def test_throne_lighting_is_ghs80_not_the_audio_device(self):
        from asus_rgb.hardware import is_throne_lighting
        self.assertTrue(is_throne_lighting({'HID_ID':'0003:00000B05:000018C5','HID_PHYS':'usb-example/input0'}))
        self.assertFalse(is_throne_lighting({'HID_ID':'0003:00000B05:000018C4','HID_PHYS':'usb-example/input3'}))
        self.assertFalse(is_throne_lighting({'HID_ID':'0003:00000B05:000018C5','HID_PHYS':'usb-example/input1'}))

class RainbowTests(unittest.TestCase):
    def test_azoth_wave_has_three_acknowledged_chunks(self):
        from asus_rgb.native import keyboard_commands
        commands=keyboard_commands((255,0,153),100,'rainbow')
        self.assertEqual([c[:4] for c in commands],[[0x51,0x2c,4,2],[0x51,0x2c,4,1],[0x51,0x2c,4,0]])
        self.assertEqual(commands[0][4:9],[30,100,1,0,2])
        self.assertTrue(all(len(c)==15 for c in commands))

    def test_mouse_uses_supported_single_zone_cycle_for_rainbow(self):
        from asus_rgb.native import lighting_command
        command=lighting_command('mouse',(255,0,153),70,'rainbow')
        self.assertEqual(command[4],2)

    def test_throne_rainbow_is_a_spatial_mode_distinct_from_cycle(self):
        from asus_rgb.hardware import throne_packet
        self.assertEqual(throne_packet((255,0,0),70,'rainbow')[5],5)
        self.assertEqual(throne_packet((255,0,0),70,'cycle')[5],4)
