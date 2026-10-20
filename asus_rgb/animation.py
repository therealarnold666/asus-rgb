"""Per-LED palette interpolation and bounded native animation workers."""
from __future__ import annotations
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import threading
import time
from . import native, hardware

DEFAULT_PALETTE=['ff0000','ff8800','ffff00','00ff00','00ffff','0055ff','aa00ff']
AZOTH_IDS=bytes.fromhex('00 08 10 18 20 28 30 38 40 48 50 58 60 01 09 11 19 21 29 31 39 41 49 51 59 61 69 79 02 0a 12 1a 22 2a 32 3a 42 4a 52 5a 62 6a 7a 03 0b 13 1b 23 2b 33 3b 43 4b 53 5b 6b 7b 04 14 1c 24 2c 34 3c 44 4c 54 5c 64 74 7c 05 0d 15 35 55 5d 65 6d 75 7d')
STATUS=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp'))/f'asus-rgb-animation-{os.getuid()}.json'

def palette_values(values):
    if isinstance(values,str):values=re.split(r'[,;，；\s]+',values.strip())
    result=[v.strip().removeprefix('#').lower() for v in values if v.strip()]
    if not 2<=len(result)<=16:raise ValueError('彩虹颜色需要 2–16 个，使用空格或逗号分隔')
    for value in result:
        if len(value)!=6 or len(bytes.fromhex(value))!=3:raise ValueError('每个颜色需为六位十六进制，例如 #ff0088')
    return result

def validate(palette,period):
    palette=palette_values(palette)
    period=float(period)
    if not 1<=period<=60:raise ValueError('流动一轮的时间需要在 1–60 秒之间')
    return palette,period

def frame(palette, phase, positions, brightness):
    colours=[tuple(bytes.fromhex(v)) for v in palette]
    result=[];n=len(colours)
    for position in positions:
        t=((position-phase)%1)*n;i=int(t);amount=t-i
        a,b=colours[i%n],colours[(i+1)%n]
        result.append(tuple(round((a[j]+(b[j]-a[j])*amount)*brightness/100) for j in range(3)))
    return result

def colour_packets(channel,colours):
    for offset in range(0,len(colours),20):
        section=colours[offset:offset+20]
        packet=[0xec,0x40,channel|(0x80 if offset+len(section)==len(colours) else 0),offset,len(section)]
        for colour in section:packet.extend(colour)
        yield packet

def raw_usb(fd,packet):
    if os.write(fd,bytes(packet).ljust(65,b'\0'))!=65:raise native.NativeError('incomplete animation write')

def memory_write_colours(fd,colours):
    # Use the previously verified byte-register path, not SMBus block writes.
    # The memory worker is capped at 2 Hz independently of USB devices.
    for led,(r,g,b) in enumerate(colours):
        for offset,value in enumerate((r,b,g)):
            hardware.write_reg(fd,0x8100+led*3+offset,value)

class Session:
    def __init__(self,device,profile):
        self.device=device;self.config=None;self.started=False
        with native.receiver(device.path) as fd:
            if device.kind=='memory':
                if hardware.identify_dram(fd,device.report)!=device.pid:raise native.NativeError('DRAM identity changed')
                hardware.write_reg(fd,0x8020,1);hardware.write_reg(fd,0x80a0,1)
            elif device.kind in ('motherboard','terminal'):
                self.config=hardware.aura_config(fd)
                count=self.config[2]
                if not 1<=count<=5:raise native.NativeError('unsupported Aura layout')
                if device.kind=='motherboard':
                    hardware.send_usb(fd,[0xec,0x52,0x53,0,1])
                    for i in range(count+(1 if self.config[27] else 0)):
                        hardware.send_usb(fd,[0xec,0x35,i,0,0,0xff])
                else:
                    for i in range(count):hardware.send_usb(fd,[0xec,0x3b,i,0,0xff,0,0,0])
            elif device.kind=='stand':
                hardware.throne_exchange(fd,[0,0x12,0])
                hardware.throne_exchange(fd,hardware.throne_packet((0,0,0),100,'static'))
            elif device.kind=='keyboard':
                native.exchange(fd,device.report,native.lighting_command('keyboard',(0,0,0),100,'static'))

    def render(self,profile,phase):
        d=self.device;palette=profile['palette'];brightness=profile['brightness']
        with native.receiver(d.path) as fd:
            if d.kind=='memory':
                fcntl.ioctl(fd,0x703,d.report)
                memory_write_colours(fd,frame(palette,phase,[i/d.pid for i in range(d.pid)],brightness))
                if not self.started:
                    # Verify a complete spatial frame once before claiming success.
                    expected=frame(palette,phase,[i/d.pid for i in range(d.pid)],brightness)
                    got=bytes(hardware.read_reg(fd,0x8100+i) for i in range(d.pid*3))
                    want=bytes(value for r,g,b in expected for value in (r,b,g))
                    if got!=want:raise native.NativeError('DRAM animation frame read-back mismatch')
            elif d.kind in ('motherboard','terminal'):
                colours=frame(palette,phase,[i/120 for i in range(120)],brightness)
                for channel in range(self.config[2]):
                    for packet in colour_packets(channel,colours):raw_usb(fd,packet)
                if d.kind=='motherboard' and self.config[27]:
                    fixed=self.config[27]
                    for packet in colour_packets(4,frame(palette,phase,[i/fixed for i in range(fixed)],brightness)):raw_usb(fd,packet)
            elif d.kind=='keyboard':
                colours=frame(palette,phase,[(led//8)/16 for led in AZOTH_IDS],brightness)
                for start in range(0,len(AZOTH_IDS),14):
                    ids=AZOTH_IDS[start:start+14];command=[0xc0,0x81,len(ids),0]
                    for led,colour in zip(ids,colours[start:start+14]):command.extend([led,*colour])
                    native.exchange(fd,d.report,command,timeout=.35,reply_prefix=bytes([d.report,0xc0,0x82]))
            elif d.kind=='stand':
                colours=frame(palette,phase,[i/17 for i in range(17)]+[0],brightness)
                for offset,count in ((0,15),(15,3)):
                    packet=[0,0xc0,0x81,offset//15,0]
                    for colour in colours[offset:offset+count]:packet.extend([0,*colour])
                    hardware.throne_exchange(fd,packet)
            elif d.kind=='mouse':
                colour=frame(palette,phase,[0],brightness)[0]
                # Brightness is already applied in the generated RGB value.
                native.exchange(fd,d.report,native.lighting_command('mouse',colour,100,'static'),timeout=.35)
            self.started=True

class Runner:
    def __init__(self,devices):
        self.devices=devices;self.stop=threading.Event();self.status={};self.lock=threading.Lock()
        self.threads=[]
        for device in devices:
            t=threading.Thread(target=self.worker,args=(device,),daemon=True);t.start();self.threads.append(t)
    def worker(self,device):
        session=None
        interval={'keyboard':.12,'mouse':.12,'memory':.50,'stand':.06}.get(device.kind,.05)
        while not self.stop.is_set():
            started=time.monotonic()
            try:
                profile=native.load_profile()
                if profile['mode']!='rainbow':break
                if session is None:session=Session(device,profile)
                session.render(profile,time.monotonic()/profile['period'])
                text='自定义渐变运行中'
            except (OSError,ValueError,native.NativeError,KeyError) as exc:
                session=None;text='等待重试: '+str(exc)
            with self.lock:self.status[device.path+':'+str(device.report)]=text
            wait=interval if session is not None else 3
            self.stop.wait(max(.005,wait-(time.monotonic()-started)))
    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=2)
    def write_status(self):
        with self.lock:value=dict(self.status)
        payload={'updated':time.time(),'devices':value}
        temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False));temp.replace(STATUS)

def read_status():
    try:
        value=json.loads(STATUS.read_text())
        if time.time()-value['updated']<5:return value['devices']
    except (OSError,ValueError,KeyError):pass
    return {}
