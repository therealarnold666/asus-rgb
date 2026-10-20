import struct
import unittest

from asus_rgb.openrgb import Client


def field(value: str) -> bytes:
    raw = value.encode() + b"\0"
    return struct.pack("<H", len(raw)) + raw


class OpenRGBProtocolTests(unittest.TestCase):
    def test_marks_dram_as_a_global_target(self):
        from asus_rgb.openrgb import Controller
        self.assertTrue(Controller(0, "ENE DRAM", "", 8).is_target)
    def test_parses_protocol_one_controller_and_led_count(self):
        body = struct.pack("<I", 0) + field("ROG AURA Terminal") + field("ASUS")
        body += b"".join(field("") for _ in range(4))
        body += struct.pack("<HIHH", 0, 0, 0, 3)  # modes, active mode, zones, LEDs
        body += b"".join(field(f"LED {index}") + struct.pack("<I", index) for index in range(3))
        body += struct.pack("<H", 3) + b"\x01\x02\x03\0" * 3
        payload = struct.pack("<I", len(body) + 4) + body
        controller = Client.parse_controller(7, payload)
        self.assertEqual((controller.index, controller.vendor, controller.led_count), (7, "ASUS", 3))
        self.assertEqual(set(controller.colours), {(1, 2, 3)})

    def test_update_payload_repeats_a_colour_for_every_led(self):
        # The payload format is size, uint16 colour count, and RGBColor values.
        from asus_rgb.openrgb import Controller
        class Socket:
            sent = b""
            def sendall(self, data):
                self.sent = data
        client = Client()
        client._socket = Socket()  # type: ignore[assignment]
        client.set_colour(Controller(2, "Aura", "ASUS", 2), (1, 2, 3))
        header = struct.unpack("<4sIII", client._socket.sent[:16])
        data_size, colour_count = struct.unpack("<IH", client._socket.sent[16:22])
        self.assertEqual(header, (b"ORGB", 2, 1050, 14))
        self.assertEqual((data_size, colour_count), (14, 2))
        self.assertEqual(client._socket.sent[22:], b"\x01\x02\x03\0" * 2)
