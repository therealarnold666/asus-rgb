from pathlib import Path
import unittest

from asus_rgb.discovery import asus_usb_devices


class DiscoveryTests(unittest.TestCase):
    def test_discovers_only_asus_devices(self):
        with __import__('tempfile').TemporaryDirectory() as directory:
            root = Path(directory)
            asus = root / "1-2"
            asus.mkdir()
            (asus / "idVendor").write_text("0b05\n")
            (asus / "idProduct").write_text("19af\n")
            (asus / "product").write_text("AURA LED Controller\n")
            other = root / "1-3"
            other.mkdir()
            (other / "idVendor").write_text("1234\n")
            self.assertEqual(asus_usb_devices(root)[0].product, "AURA LED Controller")
            self.assertEqual(len(asus_usb_devices(root)), 1)
