import customtkinter as ct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os, re, subprocess, threading, sys

# --- 1. 拖拽根窗口初始化 ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class RootWindow(TkinterDnD.Tk):
        def __init__(self):
            super().__init__()
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
    return os.path.join(base_path, ffmpeg_bin)

class VideoConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.configure(bg="#050505")
        self.root.title("视频工厂Pro")
        
        self.root.geometry("850x750")
        self.root.minsize(800, 600)
        
        self.output_dir = tk.StringVar()
        self.bitrate = tk.StringVar(value="6000k")
        self.max_size_mb = 450  # 限制大小 450MB

        # --- UI 布局 (保持原样) ---
        self.header = ct.CTkLabel(root, text="视频工厂", font=("微软雅黑", 22, "bold"))
        self.header.pack(pady=(15, 5))

        self.frame_list = ct.CTkFrame(root, corner_radius=15)
        self.frame_list.pack(padx=20, pady=10, fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", rowheight=28, borderwidth=0)
        style.map("Treeview", background=[('selected', '#1f538d')])

        tree_container = tk.Frame(self.frame_list, bg="#2b2b2b")
        tree_container.pack(padx=15, pady=(15, 5), fill="both", expand=True)

        self.tree = ttk.Treeview(tree_container, columns=("path", "status"), show="headings", height=8)
        self.tree.heading("path", text=" 文件夹路径")
        self.tree.heading("status", text=" 状态")
        self.tree.column("path", width=500)
        self.tree.column("status", width=120, anchor="center")
        
        self.scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill="y")

        if HAS_DND:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind('<<Drop>>', self.handle_drop)
            hint = "✨ 支持拖拽文件夹 | 超过 450MB 自动触发断点切分"
        else:
            hint = "未检测到拖拽库"

        self.hint_lbl = ct.CTkLabel(self.frame_list, text=hint, text_color="gray", font=("微软雅黑", 12))
        self.hint_lbl.pack(pady=(0, 10))

        self.btn_group = ct.CTkFrame(self.frame_list, fg_color="transparent")
        self.btn_group.pack(pady=(0, 10))
        ct.CTkButton(self.btn_group, text="添加文件夹", width=120, command=self.add_folder).pack(side=tk.LEFT, padx=10)
        ct.CTkButton(self.btn_group, text="删除选中项", width=120, fg_color="#c0392b", hover_color="#962d22", command=self.delete_selected).pack(side=tk.LEFT, padx=10)

        self.frame_set = ct.CTkFrame(root, corner_radius=15)
        self.frame_set.pack(padx=20, pady=5, fill="x")

        ct.CTkLabel(self.frame_set, text="输出目录:").grid(row=0, column=0, padx=15, pady=10)
        self.entry_out = ct.CTkEntry(self.frame_set, textvariable=self.output_dir, width=400)
        self.entry_out.grid(row=0, column=1, padx=5, sticky="ew")
        ct.CTkButton(self.frame_set, text="浏览", width=60, command=self.select_output).grid(row=0, column=2, padx=15)
        self.frame_set.grid_columnconfigure(1, weight=1)

        ct.CTkLabel(self.frame_set, text="视频码率:").grid(row=1, column=0, padx=15, pady=(0, 15))
        self.bit_entry = ct.CTkEntry(self.frame_set, textvariable=self.bitrate, width=120)
        self.bit_entry.grid(row=1, column=1, sticky="w", padx=5, pady=(0, 15))

        self.ctrl_frame = ct.CTkFrame(root, fg_color="transparent")
        self.ctrl_frame.pack(padx=20, pady=10, fill="x")

        self.start_btn = ct.CTkButton(self.ctrl_frame, text="开始批量转换", font=("微软雅黑", 16, "bold"), 
                                      height=45, fg_color="#27ae60", hover_color="#219150", command=self.start_task)
        self.start_btn.pack(pady=10)

        self.prog = ct.CTkProgressBar(self.ctrl_frame, width=700)
        self.prog.set(0)
        self.prog.pack(pady=5, fill="x")

        self.status_lbl = ct.CTkLabel(self.ctrl_frame, text="就绪", text_color="#95a5a6")
        self.status_lbl.pack(pady=(0, 10))

    # --- 逻辑核心 ---

    def handle_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        for p in paths:
            if os.path.isdir(p):
                self.tree.insert("", tk.END, values=(os.path.normpath(p), "等待中"))

    def add_folder(self):
        f = filedialog.askdirectory()
        if f: self.tree.insert("", tk.END, values=(os.path.normpath(f), "等待中"))

    def delete_selected(self):
        for i in self.tree.selection(): self.tree.delete(i)

    def select_output(self):
        f = filedialog.askdirectory()
        if f: self.output_dir.set(os.path.normpath(f))

    def start_task(self):
        items = self.tree.get_children()
        if not items or not self.output_dir.get():
            messagebox.showwarning("提示", "请确保已添加文件夹并选择了输出路径")
            return
        threading.Thread(target=self.run_process, daemon=True).start()

    def get_video_info(self, ffmpeg_exe, file_path):
        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run([ffmpeg_exe, "-i", file_path], capture_output=True, text=True, errors='ignore', startupinfo=si)
        dur_match = re.search(r"Duration:\s(\d+):(\d+):(\d+.\d+)", res.stderr)
        if dur_match:
            return (int(dur_match.group(1))*3600 + int(dur_match.group(2))*60 + float(dur_match.group(3)))
        return 0

    def find_scene_cuts(self, ffmpeg_exe, file_path, threshold=0.3):
        """整合 videos_cut 的场景检测逻辑"""
        cmd = [ffmpeg_exe, "-i", file_path, "-filter:v", f"select=gt(scene\\,{threshold}),showinfo", "-f", "null", "-"]
        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        proc = subprocess.Popen(cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True, errors='ignore', startupinfo=si)
        scenes = []
        for line in proc.stdout:
            if "pts_time:" in line:
                match = re.search(r"pts_time:([0-9.]+)", line)
                if match: scenes.append(float(match.group(1)))
        return sorted(list(set(scenes)))

    def run_process(self):
        self.start_btn.configure(state="disabled")
        ffmpeg_exe = get_ffmpeg_path()
        out_base = self.output_dir.get()
        items = self.tree.get_children()

        # 提取码率数值用于计算 (例如 "6000k" -> 6000000)
        try:
            bitrate_val = int(re.search(r"(\d+)", self.bitrate.get()).group(1)) * 1000
        except:
            bitrate_val = 6000000

        try:
            for item in items:
                f_path = self.tree.item(item, "values")[0]
                files = sorted([f for f in os.listdir(f_path) if f.lower().endswith(".mp4")])
                
                # 全局集数偏移量
                episode_offset = 0
                
                for f_idx, filename in enumerate(files):
                    match = re.match(r"(\d+)-(.*)\.mp4", filename)
                    if not match: continue
                    
                    raw_ep, name = int(match.group(1)), match.group(2)
                    in_p = os.path.join(f_path, filename)
                    dur = self.get_video_info(ffmpeg_exe, in_p)
                    
                    # 预估大小 (Bytes) = (码率 + 音频约192k) * 时长 / 8
                    est_size_mb = ((bitrate_val + 192000) * dur) / (8 * 1024 * 1024)
                    
                    save_dir = os.path.join(out_base, name)
                    os.makedirs(save_dir, exist_ok=True)

                    # --- 核心切分逻辑 ---
                    num_splits = int(est_size_mb // self.max_size_mb) + (1 if est_size_mb % self.max_size_mb > 0 else 0)
                    
                    if num_splits > 1:
                        self.status_lbl.configure(text=f"检测到超大文件，正在分析断点: {filename}")
                        scene_points = self.find_scene_cuts(ffmpeg_exe, in_p)
                        
                        # 根据大小平分时间点
                        target_dur = dur / num_splits
                        cut_points = [0.0]
                        last_point = 0.0
                        
                        for _ in range(num_splits - 1):
                            ideal_time = last_point + target_dur
                            # 找最接近理想切分点的场景断点
                            best_point = min(scene_points, key=lambda x: abs(x - ideal_time)) if scene_points else ideal_time
                            cut_points.append(best_point)
                            last_point = best_point
                        cut_points.append(dur)
                        
                        # 执行分段压制
                        for i in range(len(cut_points)-1):
                            start_t = cut_points[i]
                            segment_dur = cut_points[i+1] - start_t
                            curr_ep = raw_ep + episode_offset
                            out_p = os.path.join(save_dir, f"{name}-第{curr_ep}集.mp4")
                            
                            self.convert_video(ffmpeg_exe, in_p, out_p, start_t, segment_dur, name, curr_ep)
                            if i < len(cut_points)-2:
                                episode_offset += 1 # 只有切分出的段落才增加偏移
                    else:
                        # 正常压制
                        curr_ep = raw_ep + episode_offset
                        out_p = os.path.join(save_dir, f"{name}-第{curr_ep}集.mp4")
                        self.convert_video(ffmpeg_exe, in_p, out_p, 0, dur, name, curr_ep)

                    self.tree.item(item, values=(f_path, f"进行中 ({f_idx+1}/{len(files)})"))

                self.tree.item(item, values=(f_path, "已完成 √"))
            messagebox.showinfo("任务结束", "所有视频已压制并自动切分完成！")
        except Exception as e:
            messagebox.showerror("运行异常", str(e))
        finally:
            self.start_btn.configure(state="normal")
            self.prog.set(0)
            self.status_lbl.configure(text="就绪")

    def convert_video(self, ffmpeg_exe, in_p, out_p, start, duration, name, ep):
        """修复音频错位并适配 Apple Silicon (M1/M2/M3/M4) 硬件加速"""
        si = subprocess.STARTUPINFO() if os.name == 'nt' else None
        if si: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # 默认使用 CPU 编码 (libx264)
        video_codec = "libx264"
        
        # 如果是 Mac，尝试使用硬件加速 (VideoToolbox)
        if sys.platform == "darwin":
            video_codec = "h264_videotoolbox"

        cmd = [
            ffmpeg_exe, "-y", 
            "-ss", str(start), 
            "-t", str(duration), 
            "-i", in_p, 
            "-c:v", video_codec,  # 动态选择编码器
            "-b:v", self.bitrate.get(), 
            "-c:a", "aac", "-b:a", "192k", 
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            "-progress", "pipe:1", 
            out_p
        ]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si)

        for line in proc.stdout:
            t_match = re.search(r"time=(\d+):(\d+):(\d+.\d+)", line)
            if t_match and duration > 0:
                h, m, s = t_match.groups()
                cur = int(h)*3600 + int(m)*60 + float(s)
                self.prog.set(min(cur / duration, 1.0))
                self.status_lbl.configure(text=f"正在压制(M4加速版)：{name} - 第{ep}集")
                self.root.update_idletasks()
        proc.wait()

if __name__ == "__main__":
    root = RootWindow()
    app = VideoConverterApp(root)
    root.mainloop()

