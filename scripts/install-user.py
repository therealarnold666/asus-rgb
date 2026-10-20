#!/usr/bin/env python3
"""Install a launcher, desktop entry and background service for the current user."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

def systemd_quote(value):
    value=str(value)
    if '\n' in value or '\r' in value:raise ValueError('Newlines are not supported in installation paths')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'

def systemd_path(value):
    value=str(value)
    if '\n' in value or '\r' in value:raise ValueError('Newlines are not supported in installation paths')
    return value.replace('%','%%')

def install(home,source,python):
    launcher=home/'.local/bin/asus-rgb'
    launcher.parent.mkdir(parents=True,exist_ok=True)
    launcher.write_text('#!/bin/sh\ncd '+shlex.quote(str(source))+' || exit 1\nexec '+shlex.quote(str(python))+' -m asus_rgb.cli "$@"\n')
    launcher.chmod(0o755)
    units=home/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
    unit=units/'asus-rgb.service'
    unit.write_text('[Unit]\nDescription=ASUS RGB lighting background service\nAfter=graphical-session.target\n\n[Service]\nType=simple\nWorkingDirectory='+systemd_path(source)+'\nExecStart='+systemd_quote(python)+' -m asus_rgb.cli watch\nEnvironment=PYTHONUNBUFFERED=1\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n')
    apps=home/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    desktop_path=str(launcher).replace('\\','\\\\').replace('"','\\"').replace('%','%%')
    (apps/'asus-rgb.desktop').write_text('[Desktop Entry]\nType=Application\nName=ASUS RGB\nComment=Native ASUS RGB lighting controls\nExec="'+desktop_path+'" gui\nIcon=preferences-desktop-keyboard\nTerminal=false\nCategories=Settings;HardwareSettings;\n')
    return unit

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-start',action='store_true',help='install files without changing the running service')
    args=parser.parse_args()
    if os.geteuid()==0:parser.error('Run as the desktop user, not with sudo')
    source=Path(__file__).resolve().parents[1]
    unit=install(Path.home(),source,Path(sys.executable))
    if not args.no_start:
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','enable','--now','asus-rgb.service'],check=True)
    print('Installed ASUS RGB user launcher, desktop entry and service: '+str(unit))
    print('Your profile is preserved. Closing the GUI does not stop the service.')
    print('For startup before login, opt in with: loginctl enable-linger "$USER"')

if __name__=='__main__':main()
