"""
Modern GUI Application for AI Vocal & Instrumental Separator using CustomTkinter.
Enhanced with Multi-Threading, Batch Processing & Concurrent File Workers.
"""

import os
import sys
import threading
import time
import subprocess
from typing import List, Optional, Dict
import tkinter as tk
from tkinter import filedialog, messagebox

# Fix UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import customtkinter as ctk

from engine import (
    VocalSeparatorEngine,
    process_files_concurrent,
    get_optimal_cpu_threads,
    MODELS_DATA,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    is_video_file
)

# Configure CustomTkinter Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class VocalRemoverApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🎵 AI Vocal Remover & Karaoke Creator - Tách Giọng & Nhạc Nền (Tăng Tốc Siêu Nhanh)")
        self.geometry("990x840")
        self.minsize(890, 740)

        # Application State
        self.cpu_cores = os.cpu_count() or 4
        self.optimal_threads = get_optimal_cpu_threads(workers=1)
        self.selected_files: List[str] = []
        self.output_dir: str = os.path.abspath("output")
        self.is_processing: bool = False
        self.cancel_requested: bool = False

        self._build_ui()

    def _build_ui(self):
        # Main Grid Layout (2 columns: left settings, right log & status)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main Container
        self.main_frame = ctk.CTkFrame(self, corner_radius=12)
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.main_frame.grid_columnconfigure(0, weight=6)
        self.main_frame.grid_columnconfigure(1, weight=4)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # --- HEADER ---
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8))

        title_row = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_row.pack(fill="x")

        title_label = ctk.CTkLabel(
            title_row,
            text="🎵 AI VOCAL & INSTRUMENTAL REMOVER",
            font=ctk.CTkFont(size=21, weight="bold")
        )
        title_label.pack(side="left")

        cpu_badge = ctk.CTkLabel(
            title_row,
            text=f"⚡ CPU: {self.cpu_cores} Cores • Turbo Active ({self.optimal_threads}T)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1f538d",
            corner_radius=6,
            padx=8,
            pady=2
        )
        cpu_badge.pack(side="right")

        subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="Tách bỏ giọng nói, giữ lại beat/nhạc nền chất lượng cao bằng AI (MDX-Net) • Tối ưu Đa Luồng & SciPy Turbo",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        subtitle_label.pack(anchor="w", pady=(2, 0))

        # --- LEFT PANEL (Controls & Settings) ---
        self.left_panel = ctk.CTkScrollableFrame(self.main_frame, corner_radius=10)
        self.left_panel.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=8)
        self.left_panel.grid_columnconfigure(0, weight=1)

        # 1. File Selection Section
        file_box = ctk.CTkFrame(self.left_panel, corner_radius=8)
        file_box.pack(fill="x", padx=4, pady=5)

        ctk.CTkLabel(
            file_box,
            text="📂 1. Chọn File Nguồn (Âm thanh / Video)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        btn_row = ctk.CTkFrame(file_box, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=4)

        self.btn_add_files = ctk.CTkButton(
            btn_row,
            text="+ Chọn File (Audio/Video)",
            command=self._select_files,
            height=32,
            fg_color="#1f538d",
            hover_color="#14375e"
        )
        self.btn_add_files.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_add_folder = ctk.CTkButton(
            btn_row,
            text="+ Chọn Thư Mục",
            command=self._select_folder,
            height=32,
            fg_color="#2b7a78",
            hover_color="#17252a"
        )
        self.btn_add_folder.pack(side="left", fill="x", expand=True, padx=(4, 4))

        self.btn_clear_files = ctk.CTkButton(
            btn_row,
            text="Xóa",
            command=self._clear_files,
            height=32,
            width=70,
            fg_color="#802b2b",
            hover_color="#5a1e1e"
        )
        self.btn_clear_files.pack(side="left", padx=(4, 0))

        # Files count & preview
        self.file_count_lbl = ctk.CTkLabel(
            file_box,
            text="Chưa có file nào được chọn.",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        )
        self.file_count_lbl.pack(anchor="w", padx=12, pady=(2, 2))

        self.file_list_txt = ctk.CTkTextbox(file_box, height=80, font=ctk.CTkFont(size=11))
        self.file_list_txt.pack(fill="x", padx=12, pady=(2, 8))
        self.file_list_txt.insert("1.0", "Hỗ trợ: MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, AVI, MOV, WEBM...")
        self.file_list_txt.configure(state="disabled")

        # 2. Separation Mode Section
        mode_box = ctk.CTkFrame(self.left_panel, corner_radius=8)
        mode_box.pack(fill="x", padx=4, pady=5)

        ctk.CTkLabel(
            mode_box,
            text="🎯 2. Chế Độ Tách (Mode)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self.mode_var = ctk.StringVar(value="instrumental")

        modes = [
            ("instrumental", "🎼 Chỉ lấy Nhạc Nền (Instrumental / Beat - Xóa bỏ giọng nói)"),
            ("vocals", "🎤 Chỉ lấy Giọng Nói (Vocals - Xóa bỏ nhạc nền)"),
            ("both", "🎧 Xuất cả 2 Track (File Nhạc Nền + File Giọng Nói riêng)"),
            ("video_replace", "🎬 Xuất Video Mới Đã Xóa Giọng Nói (Giữ nguyên chất lượng video)")
        ]

        for val, label_text in modes:
            rb = ctk.CTkRadioButton(
                mode_box,
                text=label_text,
                variable=self.mode_var,
                value=val,
                font=ctk.CTkFont(size=12)
            )
            rb.pack(anchor="w", padx=14, pady=3)

        # 3. Multi-threading & Turbo Speed Settings Section
        perf_box = ctk.CTkFrame(self.left_panel, corner_radius=8)
        perf_box.pack(fill="x", padx=4, pady=5)

        ctk.CTkLabel(
            perf_box,
            text="⚡ 3. Chế Độ Tăng Tốc & Đa Luồng (Turbo Speed)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#63b3ed"
        ).pack(anchor="w", padx=12, pady=(8, 4))

        perf_grid = ctk.CTkFrame(perf_box, fg_color="transparent")
        perf_grid.pack(fill="x", padx=12, pady=4)
        perf_grid.grid_columnconfigure((0, 1), weight=1)

        # Speed Preset (Overlap)
        ctk.CTkLabel(perf_grid, text="🚀 Tốc độ xử lý (Speed Preset):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#ffd166").grid(row=0, column=0, sticky="w", padx=2)
        self.overlap_combo = ctk.CTkComboBox(
            perf_grid,
            values=[
                "🚀 Siêu Tốc (Overlap 0% - Nhanh gấp 2.5x)",
                "⚡ Rất Nhanh (Overlap 25% - Tối ưu thời gian)",
                "⚖️ Cân Bằng (Overlap 50% - Chuẩn UVR)",
                "💎 Chất Lượng Cao (Overlap 75% - Tinh chỉnh tối đa)"
            ],
            height=30
        )
        self.overlap_combo.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(2, 6))
        self.overlap_combo.set("🚀 Siêu Tốc (Overlap 0% - Nhanh gấp 2.5x)")

        # CPU Threads Allocation
        ctk.CTkLabel(perf_grid, text="Số luồng CPU cho AI:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=1, sticky="w", padx=2)
        cpu_opts = [
            f"Tự động tối ưu ({self.optimal_threads} luồng)",
            f"Tối đa CPU ({self.cpu_cores} luồng)",
            "8 luồng",
            "6 luồng",
            "4 luồng",
            "2 luồng"
        ]
        self.cpu_threads_combo = ctk.CTkComboBox(
            perf_grid,
            values=cpu_opts,
            height=30
        )
        self.cpu_threads_combo.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(2, 6))
        self.cpu_threads_combo.set(f"Tự động tối ưu ({self.optimal_threads} luồng)")

        # File Workers (Concurrent Files)
        ctk.CTkLabel(perf_grid, text="Số file xử lý đồng thời (Workers):", font=ctk.CTkFont(size=11)).grid(row=2, column=0, sticky="w", padx=2)
        self.workers_combo = ctk.CTkComboBox(
            perf_grid,
            values=[
                "2 file song song (Khuyên dùng)",
                "1 file (Tuần tự)",
                "3 file song song",
                "4 file song song",
                f"Tối đa ({self.cpu_cores} file)"
            ],
            height=30
        )
        self.workers_combo.grid(row=3, column=0, sticky="ew", padx=(0, 4), pady=(2, 6))
        self.workers_combo.set("2 file song song (Khuyên dùng)")

        # AI Batch Size
        ctk.CTkLabel(perf_grid, text="Kích thước Batch AI:", font=ctk.CTkFont(size=11)).grid(row=2, column=1, sticky="w", padx=2)
        self.batch_combo = ctk.CTkComboBox(
            perf_grid,
            values=["1 đoạn/lần (Tối ưu tốc độ CPU)", "2 đoạn/lần", "4 đoạn/lần"],
            height=30
        )
        self.batch_combo.grid(row=3, column=1, sticky="ew", padx=(4, 0), pady=(2, 6))
        self.batch_combo.set("1 đoạn/lần (Tối ưu tốc độ CPU)")

        # 4. Model & Audio Format Section
        settings_box = ctk.CTkFrame(self.left_panel, corner_radius=8)
        settings_box.pack(fill="x", padx=4, pady=5)

        ctk.CTkLabel(
            settings_box,
            text="⚙️ 4. Mô Hình AI & Định Dạng Xuất",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Model Selector
        self.model_options_map = {
            "MDX-Net Inst HQ 3 (Khuyên dùng - Chuẩn tách Beat/Nhạc nền)": "UVR-MDX-NET-Inst_HQ_3",
            "MDX-Net Kim Vocal 2 (Tối ưu lọc sạch Giọng Nói / Vocal)": "UVR_MDXNET_KIM_Vocal_2",
            "MDX-Net Voc FT (Tinh chỉnh Lời Hát)": "UVR-MDX-NET-Voc_FT"
        }
        self.model_combo = ctk.CTkComboBox(
            settings_box,
            values=list(self.model_options_map.keys()),
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.model_combo.pack(fill="x", padx=12, pady=(2, 6))
        self.model_combo.set("MDX-Net Inst HQ 3 (Khuyên dùng - Chuẩn tách Beat/Nhạc nền)")

        # Output Format
        fmt_row = ctk.CTkFrame(settings_box, fg_color="transparent")
        fmt_row.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(fmt_row, text="Định dạng Audio xuất:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        self.format_combo = ctk.CTkComboBox(
            fmt_row,
            values=["mp3 (320kbps)", "wav (24-bit)", "flac (Lossless)", "m4a (320kbps)"],
            height=30,
            width=180
        )
        self.format_combo.pack(side="left", fill="x", expand=True)
        self.format_combo.set("mp3 (320kbps)")

        # 5. Output Directory Section
        out_box = ctk.CTkFrame(self.left_panel, corner_radius=8)
        out_box.pack(fill="x", padx=4, pady=5)

        ctk.CTkLabel(
            out_box,
            text="💾 5. Thư Mục Lưu Kết Quả",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        out_row = ctk.CTkFrame(out_box, fg_color="transparent")
        out_row.pack(fill="x", padx=12, pady=(2, 8))

        self.out_path_entry = ctk.CTkEntry(out_row, height=32, font=ctk.CTkFont(size=12))
        self.out_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.out_path_entry.insert(0, self.output_dir)

        self.btn_browse_out = ctk.CTkButton(
            out_row,
            text="Chọn...",
            width=65,
            height=32,
            command=self._select_output_dir
        )
        self.btn_browse_out.pack(side="left", padx=(0, 4))

        self.btn_open_out = ctk.CTkButton(
            out_row,
            text="Mở Thư Mục",
            width=90,
            height=32,
            fg_color="#444",
            hover_color="#555",
            command=self._open_output_dir
        )
        self.btn_open_out.pack(side="left")

        # --- RIGHT PANEL (Logs & Actions) ---
        self.right_panel = ctk.CTkFrame(self.main_frame, corner_radius=10)
        self.right_panel.grid(row=1, column=1, sticky="nsew", padx=(8, 14), pady=8)
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=1)

        # Log Header
        log_head = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        log_head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        
        ctk.CTkLabel(
            log_head,
            text="📋 Nhật Ký & Tiến Độ Đa Luồng",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left")

        self.btn_clear_log = ctk.CTkButton(
            log_head,
            text="Xóa Log",
            width=60,
            height=24,
            fg_color="#333",
            hover_color="#444",
            font=ctk.CTkFont(size=11),
            command=self._clear_logs
        )
        self.btn_clear_log.pack(side="right")

        # Log Textbox
        self.log_textbox = ctk.CTkTextbox(
            self.right_panel,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
            corner_radius=8
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        self._log("✨ Khởi động AI Vocal Remover & Karaoke Creator (Multi-Thread Engine).")
        self._log(f"💻 Hệ thống: {self.cpu_cores} nhân CPU sẵn sàng cho xử lý song song.")
        self._log("💡 Chọn file ở bảng bên trái và nhấn BẮT ĐẦU TÁCH ÂM THANH.")

        # Progress Box
        self.progress_frame = ctk.CTkFrame(self.right_panel, corner_radius=8)
        self.progress_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=6)

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Trạng thái: Sẵn sàng",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        self.progress_label.pack(fill="x", padx=10, pady=(6, 2))

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=14)
        self.progress_bar.pack(fill="x", padx=10, pady=(2, 4))
        self.progress_bar.set(0.0)

        self.percent_label = ctk.CTkLabel(
            self.progress_frame,
            text="0% • 0/0 file",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        )
        self.percent_label.pack(anchor="e", padx=10, pady=(0, 4))

        # Main Action Buttons
        act_row = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        act_row.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 10))

        self.btn_start = ctk.CTkButton(
            act_row,
            text="🚀 BẮT ĐẦU TÁCH ĐA LUỒNG",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            fg_color="#28a745",
            hover_color="#1e7e34",
            command=self._start_processing
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_cancel = ctk.CTkButton(
            act_row,
            text="⛔ DỪNG",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=44,
            width=80,
            fg_color="#dc3545",
            hover_color="#bd2130",
            state="disabled",
            command=self._cancel_processing
        )
        self.btn_cancel.pack(side="left", padx=(4, 0))

    # --- EVENT HANDLERS & LOGIC ---

    def _select_files(self):
        filetypes = [
            ("All Supported Media", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma *.mp4 *.mkv *.avi *.mov *.webm *.opus *.flv"),
            ("Audio Files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma *.opus"),
            ("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv"),
            ("All Files", "*.*")
        ]
        files = filedialog.askopenfilenames(title="Chọn các file âm thanh hoặc video", filetypes=filetypes)
        if files:
            for f in files:
                norm_p = os.path.abspath(f)
                if norm_p not in self.selected_files:
                    self.selected_files.append(norm_p)
            self._update_file_list()

    def _select_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa các file cần tách")
        if folder:
            valid_exts = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
            found = 0
            for root, _, files in os.walk(folder):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_exts:
                        full_p = os.path.abspath(os.path.join(root, f))
                        if full_p not in self.selected_files:
                            self.selected_files.append(full_p)
                            found += 1
            self._log(f"📁 Đã quét thư mục và thêm {found} file hợp lệ.")
            self._update_file_list()

    def _clear_files(self):
        self.selected_files.clear()
        self._update_file_list()

    def _update_file_list(self):
        n = len(self.selected_files)
        self.file_count_lbl.configure(text=f"Đã chọn: {n} file")
        self.file_list_txt.configure(state="normal")
        self.file_list_txt.delete("1.0", "end")
        if n == 0:
            self.file_list_txt.insert("1.0", "Chưa chọn file nào...")
        else:
            for idx, f in enumerate(self.selected_files, 1):
                self.file_list_txt.insert("end", f"{idx}. {os.path.basename(f)}\n")
        self.file_list_txt.configure(state="disabled")

    def _select_output_dir(self):
        folder = filedialog.askdirectory(title="Chọn thư mục lưu kết quả", initialdir=self.output_dir)
        if folder:
            self.output_dir = os.path.abspath(folder)
            self.out_path_entry.delete(0, "end")
            self.out_path_entry.insert(0, self.output_dir)

    def _open_output_dir(self):
        out_d = self.out_path_entry.get().strip() or self.output_dir
        os.makedirs(out_d, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(out_d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out_d])
        else:
            subprocess.Popen(["xdg-open", out_d])

    def _log(self, message: str):
        def _do():
            timestamp = time.strftime("%H:%M:%S")
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", f"[{timestamp}] {message}\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, _do)

    def _clear_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _set_progress(self, pct: float, status_msg: str, detail_txt: str = ""):
        def _do():
            clamped_p = max(0.0, min(1.0, pct))
            self.progress_bar.set(clamped_p)
            pct_int = int(clamped_p * 100)
            if detail_txt:
                self.percent_label.configure(text=f"{pct_int}% • {detail_txt}")
            else:
                self.percent_label.configure(text=f"{pct_int}%")
            self.progress_label.configure(text=f"Trạng thái: {status_msg}")
        self.after(0, _do)

    def _start_processing(self):
        if not self.selected_files:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn ít nhất một file âm thanh hoặc video để xử lý!")
            return

        out_dir = self.out_path_entry.get().strip()
        if not out_dir:
            out_dir = os.path.abspath("output")
        self.output_dir = out_dir

        # Parse format and bitrate
        fmt_raw = self.format_combo.get()
        if "wav" in fmt_raw:
            fmt = "wav"
        elif "flac" in fmt_raw:
            fmt = "flac"
        elif "m4a" in fmt_raw:
            fmt = "m4a"
        else:
            fmt = "mp3"

        # Overlap
        overlap_raw = self.overlap_combo.get()
        if "0%" in overlap_raw or "Siêu Tốc" in overlap_raw:
            overlap = 0.0
        elif "25%" in overlap_raw or "Rất Nhanh" in overlap_raw:
            overlap = 0.25
        elif "75%" in overlap_raw or "Chất Lượng Cao" in overlap_raw:
            overlap = 0.75
        else:
            overlap = 0.5

        # Workers
        workers_raw = self.workers_combo.get()
        if "1 file" in workers_raw or "1 luồng" in workers_raw:
            max_workers = 1
        elif "3 file" in workers_raw or "3 luồng" in workers_raw:
            max_workers = 3
        elif "4 file" in workers_raw or "4 luồng" in workers_raw:
            max_workers = 4
        elif "Tối đa" in workers_raw:
            max_workers = self.cpu_cores
        else:
            max_workers = 2

        # Batch Size
        batch_raw = self.batch_combo.get()
        if "4 đoạn" in batch_raw:
            batch_size = 4
        elif "2 đoạn" in batch_raw:
            batch_size = 2
        else:
            batch_size = 1

        # CPU threads per worker
        cpu_raw = self.cpu_threads_combo.get()
        if "10" in cpu_raw:
            cpu_threads = 10
        elif "8" in cpu_raw:
            cpu_threads = 8
        elif "6" in cpu_raw:
            cpu_threads = 6
        elif "4" in cpu_raw:
            cpu_threads = 4
        elif "2" in cpu_raw:
            cpu_threads = 2
        else:
            cpu_threads = get_optimal_cpu_threads(workers=max_workers)

        model_display = self.model_combo.get()
        model_key = self.model_options_map.get(model_display, "UVR-MDX-NET-Inst_HQ_3")
        mode = self.mode_var.get()

        self.is_processing = True
        self.cancel_requested = False
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_add_files.configure(state="disabled")
        self.btn_add_folder.configure(state="disabled")

        # Run processing thread
        thread = threading.Thread(
            target=self._process_worker,
            args=(
                self.selected_files.copy(),
                self.output_dir,
                mode,
                model_key,
                fmt,
                "320k",
                overlap,
                max_workers,
                batch_size,
                cpu_threads
            ),
            daemon=True
        )
        thread.start()

    def _cancel_processing(self):
        if self.is_processing:
            self.cancel_requested = True
            self._log("⚠️ Đang dừng các luồng xử lý...")
            self.btn_cancel.configure(state="disabled")

    def _process_worker(
        self,
        files: List[str],
        output_dir: str,
        mode: str,
        model_key: str,
        audio_format: str,
        bitrate: str,
        overlap: float,
        max_workers: int,
        batch_size: int,
        cpu_threads: int
    ):
        total_files = len(files)
        effective_workers = min(max_workers, total_files)
        self._log(f"🚀 Bắt đầu xử lý {total_files} file với {effective_workers} luồng đồng thời...")
        self._log(f"⚙️ Cấu hình: Model={model_key} | Workers={effective_workers} | BatchSize={batch_size} | CPUThreads={cpu_threads} | Mode={mode}")

        start_time = time.time()

        def on_file_prog(fpath: str, p: float, msg: str):
            pass

        def on_total_prog(p: float, done_count: int, total_cnt: int, msg: str):
            detail = f"{done_count}/{total_cnt} file hoàn thành"
            self._set_progress(p, msg, detail)

        def on_log(msg: str):
            self._log(msg)

        success_count, results, errors = process_files_concurrent(
            files=files,
            output_dir=output_dir,
            mode=mode,
            model_key=model_key,
            audio_format=audio_format,
            bitrate=bitrate,
            overlap=overlap,
            batch_size=batch_size,
            max_workers=effective_workers,
            cpu_threads_per_worker=cpu_threads,
            file_progress_callback=on_file_prog,
            total_progress_callback=on_total_prog,
            log_callback=on_log,
            cancel_check=lambda: self.cancel_requested
        )

        total_elapsed = time.time() - start_time
        if not self.cancel_requested:
            self._set_progress(1.0, "Hoàn tất tất cả!", f"{success_count}/{total_files} file")
            self._log(f"🎉 HOÀN THÀNH XUẤT SẮC: {success_count}/{total_files} file trong {total_elapsed:.1f}s!")
        else:
            self._set_progress(0.0, "Đã dừng", f"{success_count}/{total_files} file")
            self._log(f"⏹️ Đã dừng xử lý. Hoàn thành: {success_count}/{total_files} file.")

        # Reset UI
        def _finish_ui():
            self.is_processing = False
            self.btn_start.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            self.btn_add_files.configure(state="normal")
            self.btn_add_folder.configure(state="normal")
            if success_count > 0 and not self.cancel_requested:
                if messagebox.askyesno("Thành Công", f"Đã tách xong {success_count} file ({total_elapsed:.1f}s)!\nBạn có muốn mở thư mục kết quả không?"):
                    self._open_output_dir()

        self.after(0, _finish_ui)


def main():
    app = VocalRemoverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
