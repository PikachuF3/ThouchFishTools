import customtkinter as ct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os, re, subprocess, threading, sys, time
import ctypes
from concurrent.futures import ThreadPoolExecutor

# --- 1. Windows 任务栏图标修复 (必须在窗口创建前) ---
try:
    # 设置唯一的 AppUserModelID，让 Windows 将其视为独立应用
    myappid = 'videofactory.pro.1.6.5'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass

# --- 2. 资源路径处理函数 ---
def resource_path(relative_path):
    """ 获取程序运行时的绝对路径 (兼容 PyInstaller 打包) """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的临时解压目录
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发环境下的当前目录
    return os.path.join(os.path.abspath("."), relative_path)

# --- Windows 任务栏闪烁支持 ---
try:
    def flash_window(hwnd):
        ctypes.windll.user32.FlashWindow(hwnd, True)
except:
    def flash_window(hwnd): pass

# --- 拖拽库安全加载 ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class RootWindow(TkinterDnD.Tk):
        def __init__(self):
            super().__init__()
            self.block_update_dimensions_event = lambda: None
            self.unblock_update_dimensions_event = lambda: None
    HAS_DND = True
except ImportError:
    class RootWindow(tk.Tk):
        def __init__(self):
            super().__init__()
    HAS_DND = False

ct.set_appearance_mode("dark")
ct.set_default_color_theme("blue")

def get_ffmpeg_path():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    ffmpeg_bin = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    local_ffmpeg = os.path.join(base_path, ffmpeg_bin)
    return local_ffmpeg if os.path.exists(local_ffmpeg) else "ffmpeg"

def get_platform_encoders():
    if sys.platform == "darwin":
        return ["CPU", "Apple加速"]
    else:
        return ["CPU", "NVIDIA显卡", "Intel显卡", "AMD显卡"]

class VideoConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.configure(bg="#050505")
        self.root.title("视频工厂 Pro - v1.6.5")
        self.root.geometry("850x620")
        
        # --- 3. 设置窗口左上角图标 ---
        try:
            icon_file = resource_path("logo.ico")
            if os.path.exists(icon_file):
                self.root.iconbitmap(icon_file)
        except Exception as e:
            print(f"图标加载失败: {e}")

        # --- 变量初始化 ---
        self.output_dir = tk.StringVar()
        self.bitrate = tk.StringVar(value="6000k")
        self.concurrency = tk.StringVar(value="2")
        self.split_mode = tk.StringVar(value="fixed")
        self.first_ep_time = tk.StringVar(value="4.30")
        self.min_segment_sec = tk.StringVar(value="60")
        self.encoder_options = get_platform_encoders()
        self.encoder_var = tk.StringVar(value=self.encoder_options[0])
        self.gpu_index = tk.StringVar(value="0") 
        
        self.ffmpeg_path = get_ffmpeg_path()
        self.total_duration = 0      
        self.completed_duration = 0  
        self.active_durations = {}   
        self.total_segments_est = 0  
        self.start_time = 0
        self.is_running = False
        self.error_occurred = False 
        self.current_processes = []

        self._setup_ui()

    def _setup_ui(self):
        # 顶部按钮
        self.top_btn_frame = ct.CTkFrame(self.root, fg_color="#1a1a1a", corner_radius=0)
        self.top_btn_frame.pack(pady=(0, 10), fill="x")
        self.function_btns = []
        
        btns_config = [
            ("添加视频", self.add_files, None),
            ("添加目录", self.add_folder_only, "#ac7c20"),
            ("删除选中", self.delete_selected, "#34495e"),
            ("清空列表", self.delete_all, "#c0392b"),
            ("导出设置", self.open_settings, "#2980b9")
        ]
        for i, (text, cmd, color) in enumerate(btns_config):
            b = ct.CTkButton(self.top_btn_frame, text=text, width=105, command=cmd)
            if color: b.configure(fg_color=color)
            b.pack(side=tk.LEFT, padx=(20, 5) if i == 0 else 5, pady=15)
            self.function_btns.append(b)

        self.stop_btn = ct.CTkButton(self.top_btn_frame, text="终止进程", width=110, 
                                    fg_color="#7f8c8d", hover_color="#c0392b",
                                    command=self.stop_all_tasks)
        self.stop_btn.pack(side=tk.RIGHT, padx=20, pady=15)

        self.out_path_frame = ct.CTkFrame(self.root, fg_color="transparent")
        self.out_path_frame.pack(pady=5, padx=20, fill="x")
        ct.CTkLabel(self.out_path_frame, text="输出目录:", font=("微软雅黑", 13)).pack(side=tk.LEFT, padx=(5, 10))
        self.entry_out = ct.CTkEntry(self.out_path_frame, textvariable=self.output_dir, height=35)
        self.entry_out.pack(side=tk.LEFT, fill="x", expand=True, padx=5)
        self.btn_browse = ct.CTkButton(self.out_path_frame, text="浏览", width=80, height=35, command=self.select_output)
        self.btn_browse.pack(side=tk.LEFT, padx=5)
        self.function_btns.append(self.btn_browse)

        self.frame_list = ct.CTkFrame(self.root, corner_radius=15)
        self.frame_list.pack(padx=20, pady=5, fill="both", expand=True)
        self.tree = ttk.Treeview(self.frame_list, columns=("path", "status"), show="headings")
        self.tree.heading("path", text=" 文件路径")
        self.tree.heading("status", text=" 任务进度")
        self.tree.column("path", width=500)
        self.tree.column("status", width=150, anchor="center")
        self.tree.pack(padx=15, pady=(15, 5), fill="both", expand=True)
        if HAS_DND:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind('<<Drop>>', self.handle_drop)
        self.hint_lbl = ct.CTkLabel(self.frame_list, text="✨ 支持拖拽文件或文件夹到此处", text_color="gray", font=("微软雅黑", 12))
        self.hint_lbl.pack(pady=(0, 5))

        self.ctrl_frame = ct.CTkFrame(self.root, fg_color="transparent")
        self.ctrl_frame.pack(padx=20, pady=10, fill="x")
        self.start_btn = ct.CTkButton(self.ctrl_frame, text="开始执行任务", font=("微软雅黑", 16, "bold"), height=50, fg_color="#27ae60", command=self.start_task)
        self.start_btn.pack(pady=5, fill="x")
        self.prog = ct.CTkProgressBar(self.ctrl_frame)
        self.prog.set(0)
        self.prog.pack(fill="x", pady=(5, 0))

        self.info_bar = ct.CTkFrame(self.root, height=30, fg_color="#1a1a1a")
        self.info_bar.pack(side=tk.BOTTOM, fill="x")
        self.status_lbl = ct.CTkLabel(self.info_bar, text="就绪", text_color="#95a5a6", font=("微软雅黑", 12))
        self.status_lbl.pack(side=tk.LEFT, padx=15)
        self.speed_lbl = ct.CTkLabel(self.info_bar, text="速度: -- | 剩: --", text_color="#95a5a6", font=("微软雅黑", 12))
        self.speed_lbl.pack(side=tk.RIGHT, padx=15)

    def stop_all_tasks(self):
        if not self.is_running:
            return
        if messagebox.askyesno("确认", "确定要终止当前所有压制任务吗？"):
            self.error_occurred = True
            self.is_running = False
            for p in self.current_processes:
                try: p.terminate()
                except: pass
            self.current_processes = []
            self.root.after(0, lambda: [
                self.status_lbl.configure(text="任务已手动终止", text_color="#e67e22"),
                self.prog.set(0),
                self.speed_lbl.configure(text="速度: -- | 剩: --"),
                self.set_ui_state(True)
            ])

    def open_settings(self):
        win = tk.Toplevel(self.root); win.title("导出设置"); win.geometry("400x460"); win.configure(bg="#1a1a1a")
        win.resizable(False, False); win.transient(self.root); win.grab_set()
        
        # 这里的 Toplevel 也可以设置图标
        try: win.iconbitmap(resource_path("logo.ico"))
        except: pass

        container = ct.CTkFrame(win, fg_color="#1a1a1a", corner_radius=0); container.pack(fill="both", expand=True, padx=25, pady=15)
        
        ct.CTkLabel(container, text="📊 基本设置", font=("微软雅黑", 14, "bold"), text_color="#3498db").pack(anchor="w", pady=(5, 5))
        for label, var in [("视频码率:", self.bitrate), ("并发任务:", self.concurrency)]:
            row = ct.CTkFrame(container, fg_color="transparent"); row.pack(fill="x", pady=2)
            ct.CTkLabel(row, text=label).pack(side=tk.LEFT); ct.CTkEntry(row, textvariable=var, width=130, height=28).pack(side=tk.RIGHT)

        ct.CTkLabel(container, text="⚙️ 编码设置", font=("微软雅黑", 14, "bold"), text_color="#e67e22").pack(anchor="w", pady=(10, 5))
        row_e = ct.CTkFrame(container, fg_color="transparent"); row_e.pack(fill="x", pady=2)
        ct.CTkLabel(row_e, text="编码器方案:").pack(side=tk.LEFT)
        ct.CTkOptionMenu(row_e, values=self.encoder_options, variable=self.encoder_var, width=130, height=28).pack(side=tk.RIGHT)
        row_g = ct.CTkFrame(container, fg_color="transparent"); row_g.pack(fill="x", pady=2)
        ct.CTkLabel(row_g, text="GPU 编号:").pack(side=tk.LEFT); ct.CTkEntry(row_g, textvariable=self.gpu_index, width=130, height=28).pack(side=tk.RIGHT)

        ct.CTkLabel(container, text="✂️ 分割策略", font=("微软雅黑", 14, "bold"), text_color="#2ecc71").pack(anchor="w", pady=(10, 5))
        f_mode = ct.CTkFrame(container, fg_color="transparent"); f_mode.pack(fill="x", pady=2)
        ct.CTkRadioButton(f_mode, text="固定时长", variable=self.split_mode, value="fixed", font=("微软雅黑", 12)).pack(side=tk.LEFT)
        ct.CTkRadioButton(f_mode, text="自动平分", variable=self.split_mode, value="auto", font=("微软雅黑", 12)).pack(side=tk.RIGHT)
        for label, var in [("首集时长:", self.first_ep_time), ("最小分段:", self.min_segment_sec)]:
            row = ct.CTkFrame(container, fg_color="transparent"); row.pack(fill="x", pady=2)
            ct.CTkLabel(row, text=label).pack(side=tk.LEFT); ct.CTkEntry(row, textvariable=var, width=130, height=28).pack(side=tk.RIGHT)

        ct.CTkButton(container, text="确 定", fg_color="#27ae60", height=35, command=win.destroy).pack(side=tk.BOTTOM, pady=(20, 5), fill="x")

    # (中间的业务逻辑处理方法 get_video_duration, orchestrator, process_single_file 等保持不变...)
    def orchestrator(self):
        ffmpeg = self.ffmpeg_path; all_tasks = []
        self.root.after(0, lambda: self.status_lbl.configure(text="正在分析时长...", text_color="#95a5a6"))
        for item_id in self.tree.get_children():
            path = self.tree.item(item_id, "values")[0]
            files = [path] if not os.path.isdir(path) else sorted([os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".mp4")])
            item_info = {"id": item_id, "files": files, "total": len(files), "done": 0}
            for f in files:
                d = self.get_video_duration(ffmpeg, f)
                if d > 0:
                    self.total_duration += d; self.total_segments_est += max(1, int(d // 60))
                    all_tasks.append((f, item_info, ffmpeg))

        if not all_tasks:
            self.root.after(0, lambda: messagebox.showerror("错误", "未找到有效视频")); self.is_running = False; self.set_ui_state(True); return

        try:
            with ThreadPoolExecutor(max_workers=int(self.concurrency.get())) as executor:
                list(executor.map(lambda p: self.process_single_file(*p), all_tasks))
            
            if not self.error_occurred and self.is_running:
                total_elapsed = time.time() - self.start_time
                h, m, s = int(total_elapsed // 3600), int((total_elapsed % 3600) // 60), int(total_elapsed % 60)
                final_time = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"
                self.root.after(0, lambda: [self.status_lbl.configure(text=f"已完成，耗时：{final_time}", text_color="#27ae60"), self.prog.set(1.0), flash_window(self.root.winfo_id())])
        except Exception:
            pass 
        finally:
            self.is_running = False; self.root.after(0, lambda: self.set_ui_state(True))

    def process_single_file(self, file_path, parent_task, ffmpeg):
        if self.error_occurred: return 
        out_root = self.output_dir.get(); min_sec = float(self.min_segment_sec.get()); dur = self.get_video_duration(ffmpeg, file_path)
        fname = os.path.basename(file_path); raw_ep = 1; title = os.path.splitext(fname)[0]
        
        ep_match = re.search(r"第(\d+)集", fname)
        start_num_match = re.match(r"^(\d+)", fname)
        if ep_match:
            raw_ep = int(ep_match.group(1)); title = re.sub(r"[-]?第\d+集", "", title).strip()
        elif start_num_match:
            raw_ep = int(start_num_match.group(1)); title = re.sub(r"^\d+[- ]*", "", title).strip()
        
        save_path = os.path.join(out_root, title); os.makedirs(save_path, exist_ok=True)
        cuts = [0.0]
        if self.split_mode.get() == "fixed":
            scenes = self.find_scenes(ffmpeg, file_path); target_first = self.parse_time_to_sec(self.first_ep_time.get())
            if dur > target_first:
                valid = [p for p in scenes if p >= target_first and (dur - p) >= min_sec]
                cuts.append(min(valid, key=lambda x: x - target_first) if valid else target_first)
            while dur - cuts[-1] >= (min_sec * 1.5):
                last_p = cuts[-1]; target_nxt = last_p + 60.0; valid_nxt = [p for p in scenes if (p - last_p) >= min_sec and (dur - p) >= min_sec]
                if valid_nxt: cuts.append(min(valid_nxt, key=lambda x: abs(x - target_nxt)))
                elif (dur - (last_p + 60.0)) >= min_sec: cuts.append(last_p + 60.0)
                else: break
        if cuts[-1] < dur: cuts.append(dur)

        for i in range(len(cuts)-1):
            if self.error_occurred: break 
            curr_ep = raw_ep + i; seg_dur = cuts[i+1] - cuts[i]; out_f = os.path.join(save_path, f"{title}-第{curr_ep}集.mp4")
            self.convert_realtime(ffmpeg, file_path, out_f, cuts[i], seg_dur, title, curr_ep)
            self.completed_duration += seg_dur; self.active_durations.pop(f"{title}_{curr_ep}", None)
        
        parent_task["done"] += 1
        self.root.after(0, lambda: self.tree.item(parent_task["id"], values=(parent_task["files"][0] if len(parent_task["files"])==1 else os.path.dirname(file_path), f"已完成 ({parent_task['done']}/{parent_task['total']})")))

    def convert_realtime(self, ffmpeg, in_p, out_p, start, dur, title, ep):
        if self.error_occurred: return
        encoder_map = {"CPU": "libx264", "Apple加速": "h264_videotoolbox", "NVIDIA显卡": "h264_nvenc", "Intel显卡": "h264_qsv", "AMD显卡": "h264_amf"}
        v_codec = encoder_map.get(self.encoder_var.get(), "libx264")
        gpu_id = self.gpu_index.get().strip() if self.gpu_index.get() else "0"
        
        cmd = [ffmpeg, "-y", "-ss", str(round(start, 3)), "-t", str(round(dur, 3)), "-i", in_p, "-c:v", v_codec]
        if "nvenc" in v_codec: cmd += ["-gpu", gpu_id]
        elif "qsv" in v_codec: cmd += ["-qsv_device", gpu_id]
        cmd += ["-b:v", self.bitrate.get(), "-c:a", "aac", "-b:a", "192k", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", "-progress", "pipe:1", out_p]

        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', startupinfo=si)
        self.current_processes.append(proc)
        
        task_key = f"{title}_{ep}"; last_error_log = []
        for line in proc.stdout:
            if self.error_occurred:
                proc.terminate(); break
            if "out_time_ms=" in line:
                try:
                    curr_ms = int(line.split('=')[1]); self.active_durations[task_key] = curr_ms / 1000000
                    self.root.after(0, lambda t=title, e=ep: self.update_smooth_ui(t, e))
                except: pass
            else:
                if line.strip(): last_error_log.append(line.strip())
                if len(last_error_log) > 15: last_error_log.pop(0)
        
        proc.wait()
        if proc in self.current_processes: self.current_processes.remove(proc)
        
        if proc.returncode != 0 and not self.error_occurred:
            self.error_occurred = True 
            err_details = "\n".join(last_error_log)
            self.root.after(0, lambda: [
                self.status_lbl.configure(text="任务出错已终止", text_color="#e74c3c"),
                self.prog.set(0),
                messagebox.showerror("压制出错", f"第 {ep} 集转换失败！\n\n错误信息：\n{err_details}")
            ])

    def update_smooth_ui(self, title, ep):
        if not self.is_running or self.error_occurred: return
        self.status_lbl.configure(text=f"压制中: {title} - 第{ep}集", text_color="#95a5a6")
        total_done_sec = self.completed_duration + sum(self.active_durations.values())
        if self.total_duration > 0:
            prog_p = total_done_sec / self.total_duration; self.prog.set(min(prog_p, 0.999))
            elapsed = time.time() - self.start_time
            if total_done_sec > 2:
                eq_done_eps = prog_p * self.total_segments_est; avg = elapsed / max(eq_done_eps, 0.001)
                rem_time = avg * (self.total_segments_est - eq_done_eps)
                rem_str = f"{int(rem_time//60)}m{int(rem_time%60)}s" if rem_time > 60 else f"{int(rem_time)}s"
                self.speed_lbl.configure(text=f"速度: {avg:.1f}s/ep | 剩: {rem_str}")

    def set_ui_state(self, is_normal):
        state = "normal" if is_normal else "disabled"
        for btn in self.function_btns: btn.configure(state=state)
        self.stop_btn.configure(fg_color="#c0392b" if not is_normal else "#7f8c8d")
        if is_normal: self.start_btn.configure(state="normal", fg_color="#27ae60", text="开始执行任务")
        else: self.start_btn.configure(state="disabled", fg_color="gray", text="正在运行...")

    def get_video_duration(self, ffmpeg, path):
        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True, errors='ignore', startupinfo=si)
        match = re.search(r"Duration:\s(\d+):(\d+):(\d+.\d+)", res.stderr)
        return int(match.group(1))*3600 + int(match.group(2))*60 + float(match.group(3)) if match else 0

    def find_scenes(self, ffmpeg, path):
        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        cmd = [ffmpeg, "-i", path, "-filter:v", "select=gt(scene\\,0.3),showinfo", "-f", "null", "-"]
        proc = subprocess.Popen(cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True, errors='ignore', startupinfo=si)
        scenes = []
        for line in proc.stdout:
            if "pts_time:" in line:
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m: scenes.append(float(m.group(1)))
        return sorted(list(set(scenes)))

    def parse_time_to_sec(self, t_str):
        try: m, s = map(int, t_str.split('.')); return m * 60 + s
        except: return 270

    def add_files(self):
        files = filedialog.askopenfilenames(filetypes=[("视频文件", "*.mp4 *.mkv *.mov"), ("所有文件", "*.*")])
        for f in files: self.add_path_to_tree(os.path.normpath(f))

    def add_folder_only(self):
        folder = filedialog.askdirectory()
        if folder: self.add_path_to_tree(os.path.normpath(folder))

    def add_path_to_tree(self, p):
        count = 0
        if os.path.isdir(p): count = len([f for f in os.listdir(p) if f.lower().endswith(".mp4")])
        elif p.lower().endswith((".mp4", ".mkv", ".mov")): count = 1
        if count > 0: self.tree.insert("", tk.END, values=(p, f"等待中 (0/{count})"))

    def delete_all(self):
        for i in self.tree.get_children(): self.tree.delete(i)

    def delete_selected(self):
        for item in self.tree.selection(): self.tree.delete(item)

    def select_output(self):
        f = filedialog.askdirectory()
        if f: self.output_dir.set(os.path.normpath(f))

    def handle_drop(self, event):
        if self.is_running: return
        paths = self.root.tk.splitlist(event.data)
        for p in paths: self.add_path_to_tree(os.path.normpath(p))

    def start_task(self):
        if not self.tree.get_children() or not self.output_dir.get():
            messagebox.showwarning("提示", "请检查列表和输出路径"); return
        
        for item_id in self.tree.get_children():
            current_vals = self.tree.item(item_id, "values")
            match = re.search(r"\((\d+)/(\d+)\)", current_vals[1])
            if match:
                total_count = match.group(2)
                self.tree.item(item_id, values=(current_vals[0], f"等待中 (0/{total_count})"))

        self.status_lbl.configure(text="准备中...", text_color="#95a5a6")
        self.prog.set(0)
        self.speed_lbl.configure(text="速度: -- | 剩: --")
        
        self.is_running = True; self.error_occurred = False; self.set_ui_state(False)
        self.start_time = time.time(); self.completed_duration = 0
        self.total_duration = 0; self.total_segments_est = 0; self.active_durations = {}; self.current_processes = []
        threading.Thread(target=self.orchestrator, daemon=True).start()

if __name__ == "__main__":
    root = RootWindow()
    app = VideoConverterApp(root)
    root.mainloop()
