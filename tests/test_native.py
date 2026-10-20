import os
from pathlib import Path
import unittest
from unittest.mock import patch
from asus_rgb.native import NativeError, exchange, parse_pairs, receiver_paths

class NativeTests(unittest.TestCase):
    def test_pair_list_decodes_supported_product_ids(self):
        reply = bytes.fromhex('01a0000200a41d0204691b0305').ljust(64,b'\0')
        devices = parse_pairs('/dev/hidraw11', reply)
        self.assertEqual([(d.pid,d.report,d.kind) for d in devices],
                         [(0x1da4,2,'keyboard'),(0x1b69,3,'mouse')])

    def test_unknown_pair_cannot_receive_lighting_commands(self):
        reply = bytes.fromhex('01a000020034120204').ljust(64,b'\0')
        self.assertEqual(parse_pairs('/dev/test',reply)[0].report,0)

    @patch('asus_rgb.native.os.write', return_value=64)
    @patch('asus_rgb.native.os.read')
    @patch('asus_rgb.native.select.select')
    def test_ignores_other_device_reply_on_shared_interface(self, poll, read, write):
        poll.side_effect = [([],[],[]), ([8],[],[]), ([8],[],[])]
        read.side_effect = [bytes([3,0x51,0x28,0,0,0]), bytes([2,0x51,0x2c,0,0,30])]
        result=exchange(8,2,[0x51,0x2c,0,0,30])
        self.assertEqual(result[:3],bytes([2,0x51,0x2c]))
        self.assertEqual(len(write.call_args.args[1]),64)

    @patch('asus_rgb.native.os.write', return_value=64)
    @patch('asus_rgb.native.select.select', return_value=([],[],[]))
    def test_no_ack_is_a_failure(self, poll, write):
        with self.assertRaises(NativeError): exchange(8,3,[0x51,0x28],timeout=0.01)
