from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

USB_ROOT = Path("/sys/bus/usb/devices")
ASUS_VENDOR_ID = "0b05"


@dataclass(frozen=True)
class UsbDevice:
    path: str
    product_id: str
    product: str


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def asus_usb_devices(root: Path = USB_ROOT) -> list[UsbDevice]:
    devices = []
    for item in root.iterdir() if root.exists() else ():
        if _read(item / "idVendor").lower() == ASUS_VENDOR_ID:
            devices.append(UsbDevice(item.name, _read(item / "idProduct"), _read(item / "product") or "Unknown ASUS device"))
    return sorted(devices, key=lambda device: device.path)
