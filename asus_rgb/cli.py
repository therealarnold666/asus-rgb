from __future__ import annotations

import argparse
import sys

from .discovery import asus_usb_devices
from .openrgb import Client, OpenRGBError


def colour(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("colour must be six hexadecimal digits, e.g. ff5500")
    try:
        return tuple(bytes.fromhex(value))  # type: ignore[return-value]
    except ValueError as error:
        raise argparse.ArgumentTypeError("colour must be hexadecimal") from error


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="asus-rgb", description="Native ASUS OMNI keyboard/mouse RGB control")
    result.add_argument("--backend", choices=("native", "openrgb"), default="native", help="native OMNI control (default), or legacy OpenRGB SDK")
    result.add_argument("--host", default="127.0.0.1", help="OpenRGB SDK host (default: loopback)")
    result.add_argument("--port", type=int, default=6742, help="OpenRGB SDK port")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="open native desktop controls")
    commands.add_parser("restore", help="restore saved lighting")
    commands.add_parser("watch", help="restore at login and receiver reconnect")
    commands.add_parser("scan", help="list paired ASUS OMNI peripherals")
    set_command = commands.add_parser("set", help="set keyboard/mouse RGB lighting")
    set_command.add_argument("colour", type=colour, help="RRGGBB, for example ff5500")
    set_command.add_argument("--brightness", type=int, choices=range(101), default=70, metavar="0-100")
    set_command.add_argument("--mode", choices=("static", "breathing", "cycle", "rainbow"), default="static")
    set_command.add_argument("--palette", help="2-16 hexadecimal colours separated by spaces or commas")
    set_command.add_argument("--period", type=float, help="seconds per full rainbow cycle (1-60)")
    set_command.add_argument("--target", choices=("all", "keyboard", "mouse", "motherboard", "memory", "stand", "terminal"), default="all")
    set_command.add_argument("--save", action="store_true", help="save synchronized profile for login restore")
    set_command.add_argument("--device", type=int, action="append", help="OpenRGB controller index (repeatable)")
    set_command.add_argument("--dry-run", action="store_true", help="show target controllers without changing them")
    return result


def open_client(args: argparse.Namespace) -> Client:
    return Client(args.host, args.port)


def run(args: argparse.Namespace) -> int:
    if args.command == "gui":
        from .gui import main as gui_main
        gui_main()
        return 0
    if args.backend == "native":
        return run_native(args)
    if args.command not in ("scan", "set"):
        print("This command requires the native backend", file=sys.stderr)
        return 2
    usb = asus_usb_devices()
    try:
        with open_client(args) as client:
            controllers = client.controllers()
            targets = [item for item in controllers if item.is_target]
            if args.command == "scan":
                print("OpenRGB-controllable ASUS devices and DRAM:")
                for item in targets:
                    zones = f", {len(item.zones)} zones" if item.zones else ""
                    print(f"  [{item.index}] {item.name} ({item.vendor or 'unknown vendor'}; {item.led_count} LEDs{zones})")
                    for zone in item.zones:
                        print(f"      zone {zone.index}: {zone.name} ({zone.led_count}/{zone.led_max} LEDs)")
                    if item.colours:
                        unique = {f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in item.colours}
                        print(f"      current colours: {', '.join(sorted(unique))}")
                if not targets:
                    print("  none")
            else:
                selected = targets if not args.device else [item for item in targets if item.index in args.device]
                missing = set(args.device or ()) - {item.index for item in selected}
                if missing:
                    raise OpenRGBError(f"not a supported ASUS/DRAM OpenRGB controller: {', '.join(map(str, sorted(missing)))}")
                if not selected:
                    raise OpenRGBError("no controllable ASUS or DRAM RGB controllers found")
                label = ''.join(f'{byte:02x}' for byte in args.colour)
                for item in selected:
                    print(f"{'Would set' if args.dry_run else 'Set'} [{item.index}] {item.name} to #{label}")
                    if not args.dry_run:
                        client.set_colour(item, args.colour)
                if not args.dry_run:
                    client.flush_updates()
    except OpenRGBError as error:
        if args.command == "scan":
            print("OpenRGB-controllable ASUS devices:\n  unavailable (OpenRGB SDK is not running)")
            print("\nASUS USB devices detected by Linux:")
            for item in usb:
                print(f"  {item.path}: {item.product} (0b05:{item.product_id})")
            if not usb:
                print("  none")
            print(f"\nOpenRGB status: {error}", file=sys.stderr)
            return 0
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.command == "scan":
        print("\nASUS USB devices detected by Linux:")
        for item in usb:
            print(f"  {item.path}: {item.product} (0b05:{item.product_id})")
        if not usb:
            print("  none")
    return 0


def run_native(args):
    from . import native
    try:
        if args.command == "scan":
            for d in native.discover():
                print(f"{d.name}: {d.kind}, PID {d.pid:04x}, report {d.report}, {d.path}")
            return 0
        if args.command == "watch":
            native.watch()
            return 0
        if args.command == "restore":
            if native.load_profile()['mode']=='rainbow':
                import subprocess
                subprocess.run(['systemctl','--user','start','asus-rgb.service'],check=True)
                print('Saved custom rainbow animation queued to background service')
                return 0
            results = native.restore()
        else:
            if args.device:
                raise native.NativeError("Native control uses --target keyboard/mouse/all, not --device")
            if args.save and args.target != "all":
                raise native.NativeError("--save stores a shared profile; use --target all")
            if args.dry_run:
                for d in native.discover():
                    if d.report and args.target in ("all", d.kind):
                        print(f"Would set {d.name}: #{bytes(args.colour).hex()}, {args.brightness}%, {args.mode}")
                return 0
            if args.mode=='rainbow':
                if args.target!='all':
                    raise native.NativeError('Custom rainbow uses the shared profile; use --target all')
                native.save_profile(args.colour,args.brightness,args.mode,args.palette,args.period)
                import subprocess
                subprocess.run(['systemctl','--user','start','asus-rgb.service'],check=True)
                print('Custom rainbow palette and speed saved; background service applies each device')
                return 0
            if args.save:
                native.save_profile(args.colour, args.brightness, args.mode,args.palette,args.period)
            results = native.apply(args.colour, args.brightness, args.mode, args.target)
        for device, error in results:
            success = ('colour/mode read-back verified' if device.kind in ('mouse', 'memory')
                       else 'device acknowledged lighting command' if device.kind in ('keyboard', 'stand')
                       else 'lighting command sent; device has no colour read-back')
            print(f"{device.name}: {error or success}")
        if any(error for _, error in results):
            return 2
        return 0
    except (native.NativeError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    args=parser().parse_args()
    from pathlib import Path
    if (Path.home()/'.config/asus-rgb/SUSPENDED').exists():
        print('RGB 控制已暂停：逐灯珠测试期间发生异常重启，待排查后恢复。',file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
