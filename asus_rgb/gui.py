"""Native desktop frontend: one saved profile, independent device results."""
from __future__ import annotations
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import colorchooser, ttk, font as tkfont
from . import native, animation

KINDS = {'keyboard':'键盘','mouse':'鼠标','motherboard':'主板 / ARGB',
         'memory':'内存','stand':'耳机架','terminal':'灯光扩展器','unsupported':'未支持'}

def main():
    root = tk.Tk()
    root.title('ASUS RGB · 全设备同步控制')
    root.geometry('1200x920'); root.minsize(940,780)
    root.configure(padx=22,pady=18)
    root.columnconfigure(0,weight=1)
    root.rowconfigure(2,weight=1)
    profile=native.load_profile()
    colour=tk.StringVar(value='#'+profile['colour'])
    brightness=tk.DoubleVar(value=profile['brightness'])
    mode_names={'常亮':'static','呼吸':'breathing','色彩循环':'cycle','彩虹流动':'rainbow'}
    mode=tk.StringVar(value=next(k for k,v in mode_names.items() if v==profile['mode']))
    palette=tk.StringVar(value=' '.join('#'+c for c in profile['palette']))
    period=tk.DoubleVar(value=profile['period'])
    status=tk.StringVar(value='正在检测设备…')
    messages=queue.Queue()
    ttk.Label(root,text='ASUS RGB',font=('',24,'bold')).grid(row=0,column=0,sticky='w')
    ttk.Label(root,text='键盘 · 鼠标 · 主板灯光接口 · 内存 · ROG Throne · Aura Terminal').grid(row=1,column=0,sticky='w',pady=(4,14))
    body_font=tkfont.nametofont('TkDefaultFont')
    heading_font=body_font.copy();heading_font.configure(weight='bold')
    row_height=max(36, body_font.metrics('linespace')+14)
    style=ttk.Style(root)
    style.configure('ASUS.Treeview',font=body_font,rowheight=row_height)
    style.configure('ASUS.Treeview.Heading',font=heading_font,padding=(10,10))
    table=ttk.Frame(root);table.grid(row=2,column=0,sticky='nsew')
    table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
    tree=ttk.Treeview(table,columns=('device','kind','result'),show='headings',height=8,style='ASUS.Treeview')
    tree.heading('device',text='设备',anchor='w');tree.column('device',width=390,minwidth=290,anchor='w')
    tree.heading('kind',text='类型',anchor='w');tree.column('kind',width=max(150,body_font.measure('主板 / ARGB')+28),minwidth=130,stretch=False,anchor='w')
    tree.heading('result',text='最近操作结果',anchor='w');tree.column('result',width=460,minwidth=330,anchor='w')
    tree.grid(row=0,column=0,sticky='nsew')
    vertical=ttk.Scrollbar(table,orient='vertical',command=tree.yview)
    vertical.grid(row=0,column=1,sticky='ns')
    horizontal=ttk.Scrollbar(table,orient='horizontal',command=tree.xview)
    horizontal.grid(row=1,column=0,sticky='ew')
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    row=ttk.Frame(root);row.grid(row=3,column=0,sticky='ew',pady=(18,10))
    ttk.Label(row,text='同步颜色').pack(side='left')
    ttk.Entry(row,textvariable=colour,width=12).pack(side='left',padx=10)
    preview=tk.Label(row,width=4,bg=colour.get(),relief='sunken');preview.pack(side='left')
    def choose():
        selected=colorchooser.askcolor(color=colour.get(),parent=root)[1]
        if selected:colour.set(selected);preview.configure(bg=selected)
    ttk.Button(row,text='选择颜色',command=choose).pack(side='left',padx=10)
    ttk.Label(row,text='灯效').pack(side='left',padx=(12,0))
    ttk.Combobox(row,textvariable=mode,values=list(mode_names),state='readonly',width=12).pack(side='left',padx=10)
    row=ttk.Frame(root);row.grid(row=4,column=0,sticky='ew',pady=(0,12))
    ttk.Label(row,text='同步亮度').pack(side='left')
    ttk.Scale(row,from_=0,to=100,variable=brightness).pack(side='left',fill='x',expand=True,padx=12)
    level=ttk.Label(row,width=5);level.pack(side='right')
    def update_level(*_):level.configure(text=f'{round(brightness.get())}%')
    brightness.trace_add('write',update_level);update_level()
    row=ttk.Frame(root);row.grid(row=5,column=0,sticky='ew',pady=(0,8))
    ttk.Label(row,text='彩虹颜色').pack(side='left')
    ttk.Entry(row,textvariable=palette).pack(side='left',fill='x',expand=True,padx=12)
    def add_palette_colour():
        selected=colorchooser.askcolor(parent=root)[1]
        if selected:palette.set(palette.get().strip()+' '+selected)
    ttk.Button(row,text='添加颜色',command=add_palette_colour).pack(side='right')
    row=ttk.Frame(root);row.grid(row=6,column=0,sticky='ew',pady=(0,10))
    gradient=tk.Canvas(row,height=20,highlightthickness=0);gradient.pack(side='left',fill='x',expand=True,padx=(0,12))
    ttk.Button(row,text='标准彩虹',command=lambda:palette.set(' '.join('#'+c for c in animation.DEFAULT_PALETTE))).pack(side='right')
    def draw_gradient(*_):
        try:
            colours=animation.palette_values(palette.get())
        except ValueError:return
        width=max(100,gradient.winfo_width());gradient.delete('all')
        for x,colour_value in enumerate(animation.frame(colours,0,[i/width for i in range(width)],100)):
            gradient.create_line(x,0,x,20,fill='#'+bytes(colour_value).hex())
    palette.trace_add('write',draw_gradient);gradient.bind('<Configure>',draw_gradient)
    row=ttk.Frame(root);row.grid(row=7,column=0,sticky='ew',pady=(0,12))
    ttk.Label(row,text='流动一轮').pack(side='left')
    ttk.Scale(row,from_=1,to=60,variable=period).pack(side='left',fill='x',expand=True,padx=12)
    speed_label=ttk.Label(row,width=8);speed_label.pack(side='right')
    def update_speed(*_):speed_label.configure(text=f'{period.get():.1f} 秒')
    period.trace_add('write',update_speed);update_speed()
    ttk.Label(root,text='彩虹颜色填 2–16 个色值，按顺序渐变；可添加、删除或调整顺序。').grid(row=8,column=0,sticky='w')
    ttk.Label(root,text='选择“彩虹流动”后应用保存。每轮秒数越小越快；自定义动画需要后台服务运行。').grid(row=9,column=0,sticky='w',pady=(4,12))
    row=ttk.Frame(root);row.grid(row=10,column=0,sticky='ew',pady=(0,12))
    button=ttk.Button(row,text='应用到全部并保存');button.pack(side='left')
    scan=ttk.Button(row,text='重新检测设备');scan.pack(side='left',padx=12)
    ttk.Label(root,textvariable=status,wraplength=1000).grid(row=11,column=0,sticky='w')
    def key(d):return d.path+':'+str(d.report)
    def worker(action, settings):
        try:
            if action=='apply':
                rgb,brightness_value,mode_value,palette_value,period_value=settings
                # The saved profile is the desired state, including asleep devices.
                # Save before I/O so partial failures never bring back an old colour.
                native.save_profile(rgb,brightness_value,mode_value,palette_value,period_value)
                subprocess.run(['systemctl','--user','start','asus-rgb.service'],check=True,capture_output=True)
            devices=native.discover()
            messages.put(('devices',devices))
            if action=='scan':
                messages.put(('status',f'检测到 {len(devices)} 个设备。颜色选择不会自动应用，请点击应用按钮。'))
            else:
                failures=0
                for device in devices:
                    if device.kind=='unsupported':continue
                    if mode_value=='rainbow':
                        text='自定义动画等待后台接管'
                        messages.put(('result',(key(device),text)))
                        continue
                    result=native.apply_devices([device],rgb,brightness_value,mode_value)[0][1]
                    if result:
                        failures+=1
                        text='休眠 / 未连接，等待重试' if device.kind in ('mouse','keyboard') else result
                    elif device.kind in ('memory','mouse'):text='颜色与模式已读回验证'
                    elif device.kind in ('keyboard','stand'):text='设备已确认接收灯光指令'
                    else:text='灯光指令已发送（无颜色读回）'
                    if not result and mode_value=='rainbow' and device.kind=='mouse':text='单区色彩循环，已读回验证'
                    messages.put(('result',(key(device),text)))
                text=('已保存，后台正在应用自定义动画。' if mode_value=='rainbow' else '已保存并应用。') if not failures else f'已保存；{failures} 个设备未成功，后台将重试。'
                messages.put(('status',text))
        except Exception as exc:messages.put(('status',str(exc)))
        finally:messages.put(('done',None))
    def start(action):
        settings=None
        if action=='apply':
            try:
                rgb=tuple(bytes.fromhex(colour.get().strip().lstrip('#')))
                native.lighting_command('keyboard',rgb,round(brightness.get()),mode_names[mode.get()])
                colours,seconds=animation.validate(palette.get(),period.get())
                settings=(rgb,round(brightness.get()),mode_names[mode.get()],colours,seconds)
                preview.configure(bg='#'+bytes(rgb).hex())
            except (ValueError,tk.TclError) as exc:
                status.set('设置无效：'+str(exc));return
        button.configure(state='disabled');scan.configure(state='disabled')
        status.set('正在应用并分别检查设备…' if action=='apply' else '正在检测设备…')
        threading.Thread(target=worker,args=(action,settings),daemon=True).start()
    button.configure(command=lambda:start('apply'));scan.configure(command=lambda:start('scan'))
    def poll():
        while not messages.empty():
            kind,value=messages.get()
            if kind=='devices':
                tree.delete(*tree.get_children())
                if value:
                    tree.column('device',width=max(390,max(body_font.measure(d.name) for d in value)+32))
                for d in value:
                    tree.insert('', 'end', iid=key(d), values=(d.name,KINDS[d.kind],'等待操作'))
            elif kind=='result':
                iid,text=value
                if tree.exists(iid):tree.set(iid,'result',text)
            elif kind=='status':status.set(value)
            else:button.configure(state='normal');scan.configure(state='normal')
        if mode.get()=='彩虹流动':
            for iid,text in animation.read_status().items():
                if tree.exists(iid):tree.set(iid,'result',text)
        root.after(100,poll)
    poll();start('scan');root.mainloop()
