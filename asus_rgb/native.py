"""Direct Linux hidraw transport for supported ASUS OMNI peripherals.

Packet facts cross-checked against seerge/g-helper Peripherals sources.
No OpenRGB library or service is used. No firmware, pairing, input mappings,
DPI or on-device flash settings are written.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import select
import time

CONFIG = Path.home() / '.config/asus-rgb/profile.json'
KEYBOARDS = {0x1DA4: 'ROG Azoth 20th', 0x1A85: 'ROG Azoth',
             0x1B42: 'ROG Azoth Extreme', 0x1CF1: 'ROG Azoth Extreme SE'}
MICE = {0x1B68: 'ROG Harpe Ace Extreme', 0x1B69: 'ROG Harpe Ace Extreme'}
MODES = {'static': 0, 'breathing': 1, 'cycle': 2, 'rainbow': 4}

class NativeError(RuntimeError):
    pass

@dataclass(frozen=True)
class Peripheral:
    path: str
    report: int
    pid: int
    kind: str
    name: str

@contextmanager
def receiver(path):
    lockdir = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'asus-rgb-{os.getuid()}'
    lockdir.mkdir(mode=0o700, exist_ok=True)
    with (lockdir / (Path(path).name + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise NativeError(f'{path}: no access; install the ASUS RGB udev rules and check the active session') from exc
        try:
            yield fd
        finally:
            os.close(fd)

def exchange(fd, report, command, timeout=1.5, reply_prefix=None):
    packet = bytes([report, *command])
    if len(packet) > 64:
        raise NativeError('HID packet exceeds 64 bytes')
    deadline = time.monotonic() + timeout
    while select.select([fd], [], [], 0)[0]:
        os.read(fd, 1024)
        if time.monotonic() >= deadline:
            raise NativeError('receiver has excessive pending data')
    if os.write(fd, packet.ljust(64, b'\0')) != 64:
        raise NativeError('incomplete HID write')
    expected = reply_prefix or packet[:3]
    rejected = False
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], max(0, deadline-time.monotonic()))[0]:
            break
        reply = os.read(fd, 1024)
        if len(reply) >= 3 and reply[:3] == expected:
            if len(reply) > 5 and reply[5] == 0xFA:
                raise NativeError('device rejected this command')
            return reply
        if reply[0:3] == bytes([report, 0xFF, 0xAA]):
            rejected = True
    reason = 'command rejected' if rejected else 'no reply (device may be asleep or disconnected)'
    raise NativeError(f'report {report}: {reason}')

def receiver_paths(root=Path('/sys/class/hidraw')):
    paths = []
    for entry in sorted(root.glob('hidraw*')):
        try:
            props = dict(line.split('=', 1) for line in (entry/'device/uevent').read_text().splitlines())
            if props.get('HID_ID') != '0003:00000B05:00001ACE':
                continue
            # Only the vendor interface, never keyboard/mouse input streams.
            if not props.get('HID_PHYS', '').endswith('/input2'):
                continue
            descriptor = (entry/'device/report_descriptor').read_bytes()
            if b'\x06\x02\xff' in descriptor and b'\x85\x03' in descriptor:
                paths.append('/dev/' + entry.name)
        except OSError:
            continue
    return paths

def parse_pairs(path, reply):
    result = []
    for offset in range(5, len(reply)-3, 4):
        pid = int.from_bytes(reply[offset:offset+2], 'little')
        if not pid:
            break
        if pid in KEYBOARDS:
            result.append(Peripheral(path, 2, pid, 'keyboard', KEYBOARDS[pid]))
        elif pid in MICE:
            result.append(Peripheral(path, 3, pid, 'mouse', MICE[pid]))
        else:
            result.append(Peripheral(path, 0, pid, 'unsupported', f'Unknown paired device 0x{pid:04x}'))
    return result

def discover():
    paths = receiver_paths()
    result = []
    for path in paths:
        with receiver(path) as fd:
            result.extend(parse_pairs(path, exchange(fd, 1, [0xA0, 0, 0])))
    from . import hardware
    result.extend(hardware.discover())
    if not result:
        raise NativeError('No supported ASUS RGB controllers found')
    return result

def lighting_command(kind, rgb, brightness, mode):
    if not 0 <= brightness <= 100 or mode not in MODES:
        raise ValueError('invalid brightness or lighting mode')
    if len(rgb) != 3 or any(not 0 <= n <= 255 for n in rgb):
        raise ValueError('invalid RGB colour')
    code = MODES[mode]
    if kind == 'keyboard':
        return [0x51, 0x2C, code, 0, 30, brightness, 0, 0, 2, *rgb, 0, 0, 0, 0, 0, 0]
    if kind == 'mouse':
        code = 2 if mode == 'rainbow' else code
        return [0x51, 0x28, 3, 0, code, brightness, *rgb, 0, 0, 1 if code else 0]
    raise ValueError('unsupported device kind')

def keyboard_commands(rgb, brightness, mode):
    if mode != 'rainbow':
        return [lighting_command('keyboard', rgb, brightness, mode)]
    # Azoth wave palettes are sent as a three-chunk sequence, not one packet.
    commands=[]
    for tag in (2,1,0):
        command=[0x51,0x2c,4,tag]+[0]*11
        if tag==2:
            command[4:9]=[30,brightness,1,0,2]
        commands.append(command)
    return commands

def apply(rgb, brightness=70, mode='static', target='all'):
    devices = [d for d in discover() if d.kind != 'unsupported' and target in ('all', d.kind, d.path+':'+str(d.report))]
    if not devices:
        raise NativeError('No supported paired devices found')
    return apply_devices(devices, rgb, brightness, mode)

def apply_devices(devices, rgb, brightness=70, mode="static"):
    lighting_command("keyboard", rgb, brightness, mode)
    results = []
    for device in devices:
        try:
            if device.kind not in ("keyboard", "mouse"):
                from . import hardware
                hardware.apply_one(device, rgb, brightness, mode)
                results.append((device, None))
                continue
            with receiver(device.path) as fd:
                commands = (keyboard_commands(rgb, brightness, mode) if device.kind == 'keyboard'
                            else [lighting_command(device.kind, rgb, brightness, mode)])
                for command in commands:
                    exchange(fd, device.report, command)
                if device.kind == 'mouse':
                    readback = exchange(fd, device.report, [0x12, 0x03, 0])
                    if (len(readback) < 10 or tuple(readback[5:7]) != (2 if mode == 'rainbow' else MODES[mode], brightness)
                            or (mode == 'static' and tuple(readback[7:10]) != tuple(rgb))):
                        raise NativeError('mouse read-back did not match requested settings')
            results.append((device, None))
        except (OSError, NativeError) as exc:
            results.append((device, str(exc)))
    return results

def load_profile():
    from .animation import DEFAULT_PALETTE, validate
    try:
        value = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        value = {'colour': 'ffffff', 'brightness': 70, 'mode': 'static'}
    rgb = tuple(bytes.fromhex(value['colour']))
    lighting_command('keyboard', rgb, value['brightness'], value['mode'])
    value['palette'], value['period'] = validate(value.get('palette', DEFAULT_PALETTE),value.get('period',8))
    return value

def save_profile(rgb, brightness, mode, palette=None, period=None):
    from .animation import validate
    import tempfile
    lighting_command('keyboard', rgb, brightness, mode)
    previous=load_profile()
    colours,seconds=validate(palette if palette is not None else previous['palette'],
                            period if period is not None else previous['period'])
    value={'colour':bytes(rgb).hex(),'brightness':brightness,'mode':mode,'palette':colours,'period':seconds}
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=CONFIG.parent,delete=False) as temp:
        json.dump(value,temp,indent=2);temp.write('\n');temporary=temp.name
    os.replace(temporary,CONFIG)

def restore():
    profile = load_profile()
    return apply(tuple(bytes.fromhex(profile['colour'])), profile['brightness'], profile['mode'])

def restore_pending(devices, profile, applied):
    signature = json.dumps(profile, sort_keys=True)
    present = {(d.path, d.report) for d in devices}
    applied = {key:value for key,value in applied.items() if key in present}
    results = []
    for device in devices:
        key = (device.path, device.report)
        if applied.get(key) == signature:
            continue
        result = apply_devices([device], tuple(bytes.fromhex(profile['colour'])),
                               profile['brightness'], profile['mode'])[0]
        results.append(result)
        if not result[1]:
            applied[key] = signature
    return applied, results

def watch():
    """One animation worker per device; all share the same palette clock."""
    from .animation import Runner
    applied={};runner=None;devices=[];last_scan=0;last_mode=None
    try:
        while True:
            try:
                profile=load_profile()
                if time.monotonic()-last_scan>15:
                    devices=[d for d in discover() if d.kind!='unsupported']
                    last_scan=time.monotonic()
                if profile['mode']=='rainbow':
                    if runner is None or runner.devices!=devices:
                        if runner:runner.close()
                        runner=Runner(devices)
                    runner.write_status()
                    applied={}
                else:
                    if runner:runner.close();runner=None
                    applied,results=restore_pending(devices,profile,applied)
                    for device,error in results:
                        print(f'Waiting: {device.name}: {error}' if error else f'Restored: {device.name}',flush=True)
                if profile['mode']!=last_mode:
                    print(f"Active mode: {profile['mode']}",flush=True);last_mode=profile['mode']
            except (OSError,NativeError,ValueError,KeyError) as exc:
                print(f'Waiting: {exc}',flush=True)
            time.sleep(1)
    finally:
        if runner:runner.close()
