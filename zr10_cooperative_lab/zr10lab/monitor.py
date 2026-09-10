"""独立桌面状态面板：读取 CSV，不阻塞、不控制正在运行的实验。"""
from __future__ import annotations
from collections import deque
import csv
import json
import math
from pathlib import Path


def monitor(session: str | Path):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("ZR10 协同观测 · 实验监视器")
    root.geometry("1160x780")
    root.configure(bg="#eef3f6")
    heading = tk.Label(root,text="ZR10  |  COOPERATIVE LAB",font=("Arial",22,"bold"),bg="#102e40",fg="white",pady=20)
    heading.pack(fill="x")
    status = tk.StringVar(value="等待实验记录……")
    tk.Label(root,textvariable=status,font=("Microsoft YaHei UI",11),bg="#eef3f6",pady=12).pack()
    canvas = tk.Canvas(root,bg="white",highlightthickness=0,height=430)
    canvas.pack(fill="both",expand=True,padx=20)
    columns = ("device","yaw","pitch","zoom","age","connected")
    tree = ttk.Treeview(root,columns=columns,show="headings",height=5)
    for key,title in zip(columns,("设备","方位 / deg","俯仰 / deg","倍率","姿态龄 / s","已连接")):
        tree.heading(key,text=title); tree.column(key,width=130,anchor="center")
    tree.pack(fill="x",padx=20,pady=12)
    tk.Label(root,text="ENU 俯视图：三角为设备，实心圆为测量轨迹，空心圆为预测。面板只读取日志。",bg="#eef3f6").pack(pady=5)
    path_arg = Path(session)
    streams = {}
    buffers = {"telemetry":deque(maxlen=500),"tracks":deque(maxlen=3000),"cycles":deque(maxlen=2)}
    current = None
    metadata = {}

    def close_streams():
        for stream,reader in streams.values():
            stream.close()
        streams.clear()

    def refresh():
        nonlocal current,metadata
        try:
            selected = path_arg
            if not (selected/"metadata.json").exists():
                choices = sorted(selected.glob("*/metadata.json"),key=lambda p:p.stat().st_mtime)
                if not choices:
                    root.after(600,refresh); return
                selected = choices[-1].parent
            if current != selected:
                close_streams(); current = selected
                metadata = json.loads((current/"metadata.json").read_text(encoding="utf-8"))
                for values in buffers.values():
                    values.clear()
                for name in buffers:
                    stream = (current/f"{name}.csv").open(encoding="utf-8-sig",newline="")
                    streams[name] = (stream,csv.DictReader(stream))
            for name,(stream,reader) in streams.items():
                # 日志周期flush整行；这里只取新增行，长时实验内存保持有界。
                for row in reader:
                    if row.get("t_s"):
                        buffers[name].append(row)
            if buffers["cycles"]:
                latest = buffers["cycles"][-1]
                m = json.loads(latest["metrics_json"])
                coverage = m.get('roi_cumulative_coverage')
                coverage_text = f"{coverage:.0%}" if isinstance(coverage, (int, float)) and math.isfinite(coverage) else "未知/未标定"
                status.set(f"{current.name}    时间 {float(latest['t_s']):.1f}s    实测 {latest['measured_tracks']}    周期 {float(latest['work_ms']):.1f}ms    区域累计覆盖 {coverage_text}")
            device_rows = {r["device_id"]:r for r in buffers["telemetry"]}
            tree.delete(*tree.get_children())
            for row in device_rows.values():
                tree.insert("","end",values=(row["device_id"],*(f"{float(row[k]):.2f}" for k in ("yaw_deg","pitch_deg","zoom","age_s")),row["connected"]))
            canvas.delete("all")
            devices = metadata.get("config",{}).get("devices",[])
            roi = metadata.get("config",{}).get("policy",{}).get("roi",{"x":[0,200],"y":[-100,100]})
            xs = [roi["x"][0],roi["x"][1],*(d["position_m"][0] for d in devices)]
            ys = [roi["y"][0],roi["y"][1],*(d["position_m"][1] for d in devices)]
            lo_x,hi_x,min_y,max_y = min(xs)-20,max(xs)+20,min(ys)-20,max(ys)+20
            width,height = canvas.winfo_width(),canvas.winfo_height()
            def xy(x,y):
                return 45+(x-lo_x)/(hi_x-lo_x)*(width-90),height-35-(y-min_y)/(max_y-min_y)*(height-70)
            for x in range(math.floor(lo_x/20)*20,math.ceil(hi_x/20)*20,20):
                a,b = xy(x,min_y),xy(x,max_y)
                canvas.create_line(*a,*b,fill="#edf1f5"); canvas.create_text(a[0],a[1]+16,text=str(x),fill="#778899")
            for y in range(math.floor(min_y/20)*20,math.ceil(max_y/20)*20,20):
                a,b = xy(lo_x,y),xy(hi_x,y)
                canvas.create_line(*a,*b,fill="#edf1f5"); canvas.create_text(a[0]-20,a[1],text=str(y),fill="#778899")
            for d in devices:
                x,y = xy(*d["position_m"][:2])
                canvas.create_polygon(x,y-7,x-7,y+7,x+7,y+7,fill="#087c83")
                canvas.create_text(x+12,y+12,text=d["id"],anchor="w",fill="#164256")
            groups = {}
            for row in buffers["tracks"]:
                groups.setdefault(row["track_id"],[]).append(row)
            colors = ("#e07936","#246bbc","#834da7","#248878")
            last_t = float(buffers["cycles"][-1]["t_s"]) if buffers["cycles"] else 0
            for i,(key,rows) in enumerate(groups.items()):
                points = [xy(float(r["x_m"]),float(r["y_m"])) for r in rows]
                if len(points)>1:
                    canvas.create_line(*[v for p in points for v in p],fill=colors[i%4],width=2)
                latest = rows[-1]
                if last_t-float(latest["t_s"])<2:
                    x,y = points[-1]
                    color = colors[i%4]
                    canvas.create_oval(x-5,y-5,x+5,y+5,outline=color,width=2,fill=color if latest["measured"]=="True" else "white")
                    canvas.create_text(x+10,y-10,text=f"{key} z={float(latest['z_m']):.1f}m",anchor="w",fill=color)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            status.set(f"等待日志刷新：{exc}")
        root.after(600,refresh)
    def shutdown():
        close_streams(); root.destroy()
    root.protocol("WM_DELETE_WINDOW",shutdown)
    root.after(100,refresh)
    root.mainloop()
