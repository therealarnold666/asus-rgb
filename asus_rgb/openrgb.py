"""Small dependency-free OpenRGB SDK client.

The wire format is three little-endian uint32 values followed by a payload.
Only the stable controller enumeration and LED-update messages are needed.
"""
from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import time

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
REQUEST_CONTROLLER_UPDATE_LEDS = 1050
REQUEST_CONTROLLER_UPDATE_ZONE_LEDS = 1051
REQUEST_CONTROLLER_RESIZE_ZONE = 1000


class OpenRGBError(RuntimeError):
    pass


@dataclass(frozen=True)
class Controller:
    index: int
    name: str
    vendor: str
    led_count: int
    zones: tuple["Zone", ...] = ()
    colours: tuple[tuple[int, int, int], ...] = ()

    @property
    def is_asus(self) -> bool:
        text = f"{self.name} {self.vendor}".lower()
        return "asus" in text or "rog" in text or "aura" in text

    @property
    def is_memory(self) -> bool:
        """DRAM RGB is commonly exposed by its LED-controller vendor, not ASUS."""
        text = f"{self.name} {self.vendor}".lower()
        return "dram" in text or "memory" in text

    @property
    def is_target(self) -> bool:
        return self.is_asus or self.is_memory


@dataclass(frozen=True)
class Zone:
    index: int
    name: str
    led_count: int
    led_min: int
    led_max: int


class Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 6742, timeout: float = 3):
        self.host, self.port, self.timeout = host, port, timeout
        self._socket: socket.socket | None = None
        self.protocol = 0

    def __enter__(self) -> "Client":
        try:
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
            self._socket.settimeout(self.timeout)
            _, _, payload = self.request(REQUEST_PROTOCOL_VERSION, 0, struct.pack("<I", 1))
            if len(payload) == 4:
                self.protocol = min(1, struct.unpack("<I", payload)[0])
        except OSError as error:
            self.close()
            raise OpenRGBError(f"cannot reach OpenRGB SDK at {self.host}:{self.port}: {error}") from error
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None

    def _read_exact(self, size: int) -> bytes:
        assert self._socket
        data = bytearray()
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise OpenRGBError("OpenRGB closed the connection")
            data.extend(chunk)
        return bytes(data)

    def request(self, packet: int, device: int, payload: bytes = b"") -> tuple[int, int, bytes]:
        assert self._socket
        self._socket.sendall(b"ORGB" + struct.pack("<III", device, packet, len(payload)) + payload)
        magic = self._read_exact(4)
        if magic != b"ORGB":
            raise OpenRGBError("invalid OpenRGB packet magic")
        response_device, response_packet, size = struct.unpack("<III", self._read_exact(12))
        return response_device, response_packet, self._read_exact(size)

    @staticmethod
    def _string(payload: bytes, start: int) -> tuple[str, int]:
        if start + 2 > len(payload):
            raise OpenRGBError("malformed OpenRGB controller data")
        (length,) = struct.unpack_from("<H", payload, start)
        end = start + 2 + length
        if end > len(payload):
            raise OpenRGBError("malformed OpenRGB controller data")
        return payload[start + 2:end].rstrip(b"\0").decode("utf-8", "replace"), end

    @classmethod
    def parse_controller(cls, index: int, payload: bytes) -> Controller:
        # Parse protocol 1 deliberately. It includes the vendor string while
        # avoiding later, evolving protocol additions.
        if len(payload) < 4:
            raise OpenRGBError("truncated OpenRGB controller data")
        offset = 8  # data_size and controller type
        name, offset = cls._string(payload, offset)
        vendor, offset = cls._string(payload, offset)
        for _ in range(4):  # description, version, serial, location
            _, offset = cls._string(payload, offset)
        if offset + 6 > len(payload):
            raise OpenRGBError("truncated OpenRGB mode data")
        mode_count = struct.unpack_from("<H", payload, offset)[0]
        offset += 6  # num_modes and active_mode
        for _ in range(mode_count):
            _, offset = cls._string(payload, offset)
            if offset + 38 > len(payload):
                raise OpenRGBError("truncated OpenRGB mode")
            offset += 36  # nine uint32 fields in protocol 1
            colour_count = struct.unpack_from("<H", payload, offset)[0]
            offset += 2 + 4 * colour_count
        if offset + 2 > len(payload):
            raise OpenRGBError("truncated OpenRGB zone data")
        zone_count = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
        zones = []
        for zone_index in range(zone_count):
            zone_name, offset = cls._string(payload, offset)
            if offset + 18 > len(payload):
                raise OpenRGBError("truncated OpenRGB zone")
            # type, minimum, maximum, current LED count
            _, zone_led_min, zone_led_max, zone_led_count = struct.unpack_from("<iIII", payload, offset)
            offset += 16
            matrix_size = struct.unpack_from("<H", payload, offset)[0]
            offset += 2 + matrix_size
            zones.append(Zone(zone_index, zone_name, zone_led_count, zone_led_min, zone_led_max))
        if offset + 2 > len(payload):
            raise OpenRGBError("truncated OpenRGB LED data")
        led_count = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
        for _ in range(led_count):
            _, offset = cls._string(payload, offset)
            if offset + 4 > len(payload):
                raise OpenRGBError("truncated OpenRGB LED value")
            offset += 4  # protocol 1 LED value
        if offset + 2 > len(payload):
            raise OpenRGBError("truncated OpenRGB colour data")
        colour_count = struct.unpack_from("<H", payload, offset)[0]
        offset += 2
        if offset + 4 * colour_count > len(payload):
            raise OpenRGBError("truncated OpenRGB colours")
        colours = tuple(tuple(payload[position:position + 3]) for position in range(offset, offset + 4 * colour_count, 4))
        return Controller(index, name, vendor, led_count, tuple(zones), colours)

    def controllers(self) -> list[Controller]:
        _, _, payload = self.request(REQUEST_CONTROLLER_COUNT, 0)
        if len(payload) != 4:
            raise OpenRGBError("invalid controller-count response")
        (count,) = struct.unpack("<I", payload)
        controllers = []
        for index in range(count):
            payload = struct.pack("<I", self.protocol) if self.protocol else b""
            _, _, data = self.request(REQUEST_CONTROLLER_DATA, index, payload)
            controllers.append(self.parse_controller(index, data))
        return controllers

    def _send_led_update(self, packet: int, controller: Controller, rgb: tuple[int, int, int], led_count: int, zone_index: int | None = None) -> None:
        if not led_count:
            return
        # UpdateLEDs data is its own size, a uint16 count, then RGBColor (RGBA)
        # values. Supplying one colour for every LED gives a true global colour.
        colours = bytes((*rgb, 0)) * led_count
        # OpenRGB's data_size includes the data_size field itself.  In protocol
        # 1, LED updates have no synchronous response (ACK arrived in protocol
        # 6), so waiting for one makes the server eventually close the socket.
        zone = struct.pack("<I", zone_index) if zone_index is not None else b""
        payload = (struct.pack("<IH", 6 + len(colours), led_count) if not zone
                   else struct.pack("<IIH", 10 + len(colours), zone_index, led_count)) + colours
        assert self._socket
        self._socket.sendall(b"ORGB" + struct.pack("<III", controller.index, packet, len(payload)) + payload)

    def set_colour(self, controller: Controller, rgb: tuple[int, int, int]) -> None:
        if controller.led_count:
            self._send_led_update(REQUEST_CONTROLLER_UPDATE_LEDS, controller, rgb, controller.led_count)
            return
        writable_zones = []
        for zone in controller.zones:
            if not zone.led_count and zone.led_max:
                # Addressable headers begin at zero until a size is configured.
                # Selecting the controller-supported maximum means every LED
                # physically chained to the header receives the same colour.
                self.resize_zone(controller, zone, zone.led_max)
                zone = Zone(zone.index, zone.name, zone.led_max, zone.led_min, zone.led_max)
            if zone.led_count:
                writable_zones.append(zone)
        if not writable_zones:
            raise OpenRGBError(f"{controller.name} has no configured addressable LEDs; set its zone sizes in OpenRGB first")
        for zone in writable_zones:
            self._send_led_update(REQUEST_CONTROLLER_UPDATE_ZONE_LEDS, controller, rgb, zone.led_count, zone.index)

    def resize_zone(self, controller: Controller, zone: Zone, size: int) -> None:
        assert self._socket
        payload = struct.pack("<II", zone.index, size)
        self._socket.sendall(b"ORGB" + struct.pack("<III", controller.index, REQUEST_CONTROLLER_RESIZE_ZONE, len(payload)) + payload)

    def flush_updates(self) -> None:
        """Allow OpenRGB's controller threads to consume queued LED updates."""
        time.sleep(0.15)
