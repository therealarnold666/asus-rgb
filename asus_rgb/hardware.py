"""Native Aura USB and positively identified ENE DRAM lighting.

Protocol facts: ASUS Aura USB and ENE SMBus reference drivers in OpenRGB.
This module does not invoke OpenRGB. No address remapping, SPD access, firmware
updates or nonvolatile save commands are performed.
"""
from __future__ import annotations
import ctypes
import fcntl
import os
from pathlib import Path
import select
import time
from .native import Peripheral, NativeError, receiver

class SMBData(ctypes.Union):
    _fields_ = [('byte', ctypes.c_uint8), ('word', ctypes.c_uint16), ('block', ctypes.c_uint8 * 34)]
class SMBRequest(ctypes.Structure):
    _fields_ = [('rw', ctypes.c_uint8), ('command', ctypes.c_uint8),
                ('size', ctypes.c_uint32), ('data', ctypes.POINTER(SMBData))]

def smbus(fd, read, command, size, value=0):
    data = SMBData(); data.word = value
    request = SMBRequest(read, command, size, ctypes.pointer(data))
    fcntl.ioctl(fd, 0x720, request)
    return data.word if size == 3 else data.byte

def read_reg(fd, address):
    smbus(fd, 0, 0, 3, ((address & 255) << 8) | (address >> 8))
    return smbus(fd, 1, 0x81, 2)

def write_reg(fd, address, value):
    smbus(fd, 0, 0, 3, ((address & 255) << 8) | (address >> 8))
    smbus(fd, 0, 1, 2, value)

def identify_dram(fd, address):
    fcntl.ioctl(fd, 0x703, address)
    if [smbus(fd, 1, reg, 2) for reg in range(0xa0, 0xb0)] != list(range(16)):
        return None
    version = bytes(read_reg(fd, 0x1000+i) for i in range(16)).split(b'\0')[0]
    if version != b'AUDA0-E6K5-0101':
        return None
    count = sum(read_reg(fd, 0x1c03+i) for i in range(8))
    if not 1 <= count <= 32:
        return None
    return count

def is_throne_lighting(props):
    return (props.get('HID_ID') == '0003:00000B05:000018C5'
            and props.get('HID_PHYS', '').endswith('/input0'))

def discover():
    devices = []
    for entry in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
        try:
            props = dict(line.split('=',1) for line in (entry/'device/uevent').read_text().splitlines())
            hid_id = props.get('HID_ID','')
            kind, name, pid = '', '', 0
            if hid_id == '0003:00000B05:000019AF':
                if b'\x85\xec' not in (entry/'device/report_descriptor').read_bytes(): continue
                kind, name, pid = 'motherboard', 'ASUS Aura · 主板灯光接口', 0x19af
            elif hid_id == '0003:00000B05:00001889':
                kind, name, pid = 'terminal', 'ROG Aura Terminal', 0x1889
            elif is_throne_lighting(props):
                kind, name, pid = 'stand', 'ROG Throne Qi', 0x18c5
            if kind:
                devices.append(Peripheral('/dev/'+entry.name, 0xec if kind != 'stand' else 0, pid, kind, name))
        except OSError:
            continue
    for entry in sorted(Path('/sys/class/i2c-dev').glob('i2c-*')):
        if 'SMBus PIIX4 adapter port 0' not in (entry/'name').read_text(): continue
        path = '/dev/'+entry.name
        with receiver(path) as fd:
            # Existing addresses only. Never remap RAM controllers or touch SPD.
            for address in range(0x70,0x78):
                try:
                    count = identify_dram(fd, address)
                    if count:
                        devices.append(Peripheral(path, address, count, 'memory', f'ENE 内存灯光 · 0x{address:02x} ({count} LEDs)'))
                except OSError:
                    continue
    return devices

def send_usb(fd, packet):
    if len(packet) > 65: raise NativeError('Aura packet too large')
    if os.write(fd, bytes(packet).ljust(65,b'\0')) != 65:
        raise NativeError('incomplete Aura USB write')
    time.sleep(.005)

def aura_config(fd):
    end = time.monotonic()+1.5
    while select.select([fd],[],[],0)[0]:
        os.read(fd,1024)
        if time.monotonic()>end: raise NativeError('excessive Aura pending data')
    send_usb(fd,[0xec,0xb0])
    while time.monotonic()<end:
        if not select.select([fd],[],[],max(0,end-time.monotonic()))[0]: break
        reply=os.read(fd,1024)
        if len(reply)>=64 and reply[:2]==b'\xec\x30': return reply[4:64]
    raise NativeError('Aura controller did not reply to configuration query')

def direct_packets(channel, count, rgb):
    for start in range(0,count,20):
        amount=min(20,count-start)
        command=channel | (0x80 if start+amount==count else 0)
        yield [0xec,0x40,command,start,amount] + list(rgb)*amount

def throne_exchange(fd, packet):
    # Unnumbered HID: output includes a leading zero, input omits that byte.
    deadline = time.monotonic()+1.5
    while select.select([fd], [], [], 0)[0]:
        os.read(fd, 1024)
        if time.monotonic() >= deadline: raise NativeError('excessive Throne pending data')
    send_usb(fd, packet)
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], max(0, deadline-time.monotonic()))[0]: break
        reply=os.read(fd,1024)
        if len(reply)>=2 and reply[:2]==bytes(packet[1:3]): return reply
    raise NativeError('Throne lighting controller did not acknowledge command')

def throne_packet(rgb, brightness, mode):
    # Throne firmware uses five brightness levels, unlike OMNI's percentage.
    level = 0 if brightness == 0 else max(1, min(4, round(brightness * 4 / 100)))
    colour = rgb if mode not in ('cycle', 'rainbow') else (0, 0, 0)
    return [0, 0x51, 0x28, 0, 0, {'static':1,'breathing':2,'cycle':4,'rainbow':5}[mode],
            127, level, 0, 0, *colour]

def apply_one(device, rgb, brightness, mode):
    scaled = tuple(round(v*brightness/100) for v in rgb)
    with receiver(device.path) as fd:
        if device.kind == 'memory':
            count = identify_dram(fd,device.report)
            if count != device.pid: raise NativeError('DRAM controller identity changed')
            r,g,b=scaled
            for led in range(count):
                for offset,value in enumerate((r,b,g)):
                    write_reg(fd,0x8160+led*3+offset,value)
            write_reg(fd,0x8020,0)
            write_reg(fd,0x8021,{'static':1,'breathing':2,'cycle':4,'rainbow':5}[mode])
            write_reg(fd,0x8022,2)
            write_reg(fd,0x80a0,1)
            readback=bytes(read_reg(fd,0x8160+i) for i in range(count*3))
            if readback != bytes((r,b,g))*count:
                raise NativeError('DRAM colour read-back mismatch')
            if read_reg(fd,0x8021)!={'static':1,'breathing':2,'cycle':4,'rainbow':5}[mode]:
                raise NativeError('DRAM mode read-back mismatch')
            return '颜色与模式已读回验证'
        if device.kind == 'stand':
            version=throne_exchange(fd,[0,0x12,0])
            if len(version)<8:raise NativeError('invalid Throne firmware reply')
            packet=throne_packet(rgb, brightness, mode)
            reply=throne_exchange(fd,packet)
            if reply[:len(packet)-1]!=bytes(packet[1:]):
                raise NativeError('Throne lighting acknowledgement mismatch')
            return 'Throne 灯光控制器已确认接收'
        config=aura_config(fd)
        channels=config[2]
        if not 1 <= channels <= 5: raise NativeError('unsupported Aura channel count')
        if device.kind == 'motherboard':
            send_usb(fd,[0xec,0x52,0x53,0,1])
            fixed=config[27]
            base=1 if fixed else 0
        else:
            fixed=0; base=0
        # Static writes each LED on every header. Dynamic effects stay in firmware.
        if mode == 'static':
            if device.kind == 'motherboard':
                for channel in range(channels+base): send_usb(fd,[0xec,0x35,channel,0,0,0xff])
                if fixed:
                    for packet in direct_packets(4,fixed,scaled):send_usb(fd,packet)
            else:
                for channel in range(channels):send_usb(fd,[0xec,0x3b,channel,0,0xff,*scaled])
            for channel in range(channels):
                for packet in direct_packets(channel,120,scaled):send_usb(fd,packet)
        else:
            effect={'breathing':2,'cycle':4,'rainbow':5}[mode]
            if device.kind == 'motherboard':
                for channel in range(channels+base):
                    send_usb(fd,[0xec,0x35,channel,0,0,effect])
                count=fixed+channels
                if count>16:raise NativeError('unsupported Aura effect layout')
                mask=(1<<count)-1
                send_usb(fd,[0xec,0x36,mask>>8,mask&255,0]+list(scaled)*count)
            else:
                for channel in range(channels):send_usb(fd,[0xec,0x3b,channel,0,effect,*scaled])
        return '已读取控制器配置并发送灯光指令（无颜色读回）'
