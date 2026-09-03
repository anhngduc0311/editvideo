"""
roi_selector.py - Interactive Visual Subtitle Blur Region & Subtitle Placement Studio
"""

from __future__ import annotations

import copy
import io
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Dict, Optional, Tuple
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image, ImageFilter, ImageTk, ImageDraw, ImageFont

# Tự động nạp static_ffmpeg nếu có
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

from config import BlurRegion, SubtitleStyle, SUBTITLE_PRESETS

logger = logging.getLogger(__name__)


def ass_to_hex(ass_color: str, default: str = "#ffffff") -> str:
    """Chuyển đổi mã màu ASS (&HAABBGGRR hoặc &HBBGGRR) sang Hex chuẩn CSS (#RRGGBB)"""
    if not ass_color:
        return default
    clean = ass_color.replace("&H", "").replace("&h", "").strip()
    if len(clean) == 8:
        bb = clean[2:4]
        gg = clean[4:6]
        rr = clean[6:8]
        return f"#{rr}{gg}{bb}"
    elif len(clean) == 6:
        bb = clean[0:2]
        gg = clean[2:4]
        rr = clean[4:6]
        return f"#{rr}{gg}{bb}"
    elif ass_color.startswith("#"):
        return ass_color
    return default


class VisualROISelectorDialog(ctk.CTkToplevel):
    """
    Studio Trực Quan 2-trong-1 (Visual Studio):
    1. Khoanh vùng làm mờ phụ đề tiếng Trung gốc (Blur Region).
    2. Chỉnh tay vị trí, kích thước, kiểu dáng và căn lề phụ đề Tiếng Việt (Subtitle Positioning & Styling).
    """

    def __init__(
        self,
        parent,
        video_path: Optional[Path] = None,
        initial_blur_region: Optional[BlurRegion] = None,
        initial_subtitle_style: Optional[SubtitleStyle] = None,
        on_save_callback: Optional[Callable[[BlurRegion, SubtitleStyle], None]] = None
    ):
        super().__init__(parent)

        self.title("🎯 Studio Chỉnh Sửa Trực Quan: Vùng Làm Mờ & Vị Trí Phụ Đề Tiếng Việt")
        self.geometry("1180, 890")
        self.minsize(980, 750)

        # Đưa cửa sổ lên trên cùng
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

        self.video_path = Path(video_path) if video_path else None
        self.blur_region = copy.copy(initial_blur_region) if initial_blur_region else BlurRegion()
        self.sub_style = copy.copy(initial_subtitle_style) if initial_subtitle_style else SubtitleStyle()
        self.on_save_callback = on_save_callback

        # Chế độ làm việc: "blur" (Vùng làm mờ) hoặc "subtitle" (Chỉnh tay phụ đề)
        self.active_mode = "subtitle"  # Mặc định mở vào chỉnh phụ đề theo mong muốn người dùng
        self.sample_text = "[ Phụ đề Tiếng Việt sẽ hiển thị tại đây ]"

        # Dữ liệu thời gian & Bộ nhớ đệm khung hình
        self.video_duration: float = self._get_video_duration()
        self.current_time_sec: float = min(2.0, self.video_duration * 0.2) if self.video_duration > 0 else 0.0
        self.frame_cache: Dict[int, Image.Image] = {}
        self.is_fetching_frame = False
        self.pending_seek_sec: Optional[float] = None
        self._seek_timer: Optional[str] = None

        # Dữ liệu ảnh
        self.orig_image: Optional[Image.Image] = None
        self.photo_img = None
        self.scale_factor = 1.0

        # Tọa độ vùng mờ trên ảnh gốc (Pixel)
        self.roi_x = self.blur_region.x
        self.roi_y = self.blur_region.y
        self.roi_w = self.blur_region.width
        self.roi_h = self.blur_region.height

        # Trạng thái kéo chuột
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False

        self._load_initial_frame()
        self._build_ui()
        self._sync_ui_from_style()
        self._draw_canvas()

    def _get_video_duration(self) -> float:
        """Đo độ dài video (Duration tính bằng giây) qua ffprobe hoặc ffmpeg"""
        if not self.video_path or not self.video_path.exists():
            return 10.0

        ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            try:
                cmd = [
                    ffprobe_bin, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(self.video_path)
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    dur = float(data.get("format", {}).get("duration", 0))
                    if dur > 0:
                        return dur
            except Exception:
                pass

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        try:
            cmd = [ffmpeg_bin, "-i", str(self.video_path)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
            if m:
                dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                if dur > 0:
                    return dur
        except Exception:
            pass

        return 30.0

    def _extract_video_frame(self, timestamp_sec: float) -> Optional[Image.Image]:
        """Trích xuất 1 khung hình từ video tại mốc thời gian timestamp_sec"""
        if not self.video_path or not self.video_path.exists():
            return self._create_placeholder_frame()

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        try:
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", f"{max(0.0, timestamp_sec):.2f}",
                "-i", str(self.video_path),
                "-vframes", "1",
                "-q:v", "2",
                "-f", "image2",
                "pipe:1"
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            if res.stdout and len(res.stdout) > 500:
                img = Image.open(io.BytesIO(res.stdout)).convert("RGB")
                return img
        except Exception as e:
            logger.warning(f"Lỗi trích xuất frame tại {timestamp_sec:.2f}s: {e}")

        return None

    def _create_placeholder_frame(self) -> Image.Image:
        """Tạo khung hình 1080x1920 mẫu giả lập video Douyin"""
        w, h = 1080, 1920
        img = Image.new("RGB", (w, h), color=(20, 24, 33))
        return img

    def _load_initial_frame(self):
        """Tải khung hình ban đầu"""
        img = self._extract_video_frame(self.current_time_sec)
        if img:
            self.orig_image = img
            cache_key = int(self.current_time_sec * 2)
            self.frame_cache[cache_key] = img
        else:
            self.orig_image = self._create_placeholder_frame()

        orig_w, orig_h = self.orig_image.size

        # Khởi tạo tọa độ mặc định vùng mờ nếu chưa có
        if self.blur_region.x is not None and self.blur_region.y is not None:
            self.roi_x = int(self.blur_region.x)
            self.roi_y = int(self.blur_region.y)
            self.roi_w = int(self.blur_region.width) if self.blur_region.width is not None else 683
            self.roi_h = int(self.blur_region.height) if self.blur_region.height is not None else 50
        else:
            if self.roi_w is None:
                self.roi_w = int(orig_w * 0.5336) if orig_w >= 1000 else orig_w
            if self.roi_h is None:
                self.roi_h = int(orig_h * self.blur_region.height_ratio)
            if self.roi_x is None:
                self.roi_x = int((orig_w - self.roi_w) / 2)
            if self.roi_y is None:
                self.roi_y = int(orig_h * self.blur_region.y_ratio)

    def _format_time(self, sec: float) -> str:
        sec = max(0.0, sec)
        m = int(sec // 60)
        s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(1, weight=1)

        # -------------------------------------------------------------
        # TOP TOOLBAR: Chuyển đổi chế độ (Mode Switcher)
        # -------------------------------------------------------------
        top_frame = ctk.CTkFrame(self, height=54, corner_radius=8, fg_color=("#1e293b", "#0f172a"))
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            top_frame,
            text="🛠 Chế độ làm việc:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8fafc"
        ).pack(side="left", padx=(14, 8), pady=8)

        self.seg_mode = ctk.CTkSegmentedButton(
            top_frame,
            values=["✍️ Chỉnh Tay Vị Trí & Kiểu Phụ Đề", "🟥 Khoanh Vùng Làm Mờ Sub Gốc"],
            command=self._on_mode_switched,
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.seg_mode.set("✍️ Chỉnh Tay Vị Trí & Kiểu Phụ Đề")
        self.seg_mode.pack(side="left", padx=4, pady=8)

        self.lbl_mode_hint = ctk.CTkLabel(
            top_frame,
            text="👉 Kéo trực tiếp trên hình để đổi vị trí phụ đề hoặc chỉnh ở cột bên phải",
            font=ctk.CTkFont(size=12),
            text_color="#38bdf8"
        )
        self.lbl_mode_hint.pack(side="right", padx=14)

        # -------------------------------------------------------------
        # CỘT TRÁI: Video Canvas + Timeline Scrubber
        # -------------------------------------------------------------
        left_container = ctk.CTkFrame(self, corner_radius=10)
        left_container.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=4)
        left_container.grid_columnconfigure(0, weight=1)
        left_container.grid_rowconfigure(0, weight=1)

        # Canvas hiển thị video & overlay
        self.canvas = tk.Canvas(
            left_container,
            bg="#0b0f19",
            highlightthickness=0,
            cursor="fleur"
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())

        # Timeline Scrubber Card
        timeline_card = ctk.CTkFrame(left_container, corner_radius=8, fg_color=("#1e293b", "#0f172a"))
        timeline_card.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 6))

        tl_header = ctk.CTkFrame(timeline_card, fg_color="transparent")
        tl_header.pack(fill="x", padx=10, pady=(4, 2))

        ctk.CTkLabel(
            tl_header,
            text="🎬 Kéo xem video:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#facc15"
        ).pack(side="left")

        self.lbl_time = ctk.CTkLabel(
            tl_header,
            text=f"⏱️ {self._format_time(self.current_time_sec)} / {self._format_time(self.video_duration)}",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_time.pack(side="left", padx=(8, 0))

        btn_box = ctk.CTkFrame(tl_header, fg_color="transparent")
        btn_box.pack(side="right")

        ctk.CTkButton(btn_box, text="⏪ -5s", width=46, height=22, font=ctk.CTkFont(size=10), fg_color="#334155", hover_color="#475569", command=lambda: self._seek_relative(-5.0)).pack(side="left", padx=1)
        ctk.CTkButton(btn_box, text="◀ -1s", width=42, height=22, font=ctk.CTkFont(size=10), fg_color="#334155", hover_color="#475569", command=lambda: self._seek_relative(-1.0)).pack(side="left", padx=1)
        ctk.CTkButton(btn_box, text="▶ +1s", width=42, height=22, font=ctk.CTkFont(size=10), fg_color="#334155", hover_color="#475569", command=lambda: self._seek_relative(1.0)).pack(side="left", padx=1)
        ctk.CTkButton(btn_box, text="⏩ +5s", width=46, height=22, font=ctk.CTkFont(size=10), fg_color="#334155", hover_color="#475569", command=lambda: self._seek_relative(5.0)).pack(side="left", padx=1)

        self.slider_timeline = ctk.CTkSlider(
            timeline_card,
            from_=0.0,
            to=max(1.0, self.video_duration),
            number_of_steps=int(max(20, self.video_duration * 4)),
            command=self._on_timeline_slider_changed,
            progress_color="#38bdf8",
            button_color="#0284c7"
        )
        self.slider_timeline.set(self.current_time_sec)
        self.slider_timeline.pack(fill="x", padx=10, pady=(2, 6))

        # -------------------------------------------------------------
        # CỘT PHẢI: Bảng Điều Khiển Tùy Chỉnh Phụ Đề & Vùng Mờ
        # -------------------------------------------------------------
        right_scroll = ctk.CTkScrollableFrame(self, corner_radius=10)
        right_scroll.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=4)
        right_scroll.grid_columnconfigure(0, weight=1)

        # 1. BẢNG ĐIỀU KHIỂN CHỈNH TAY PHỤ ĐỀ
        self.card_sub_ctrl = ctk.CTkFrame(right_scroll, corner_radius=8)
        self.card_sub_ctrl.pack(fill="x", padx=4, pady=4)

        ctk.CTkLabel(
            self.card_sub_ctrl,
            text="✍️ Tùy Chỉnh Phụ Đề Tiếng Việt",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=12, pady=(10, 4))

        # Vị trí Margin V (Khoảng cách mép dưới)
        margin_header = ctk.CTkFrame(self.card_sub_ctrl, fg_color="transparent")
        margin_header.pack(fill="x", padx=12, pady=(2, 0))
        ctk.CTkLabel(margin_header, text="📏 Vị trí độ cao (Margin V):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.lbl_margin_val = ctk.CTkLabel(
            margin_header,
            text=f"{self.sub_style.margin_v}px",
            font=ctk.CTkFont(weight="bold"),
            text_color="#10b981"
        )
        self.lbl_margin_val.pack(side="right")

        self.slider_margin_v = ctk.CTkSlider(
            self.card_sub_ctrl,
            from_=10,
            to=600,
            number_of_steps=118,
            command=self._on_margin_slider_changed
        )
        self.slider_margin_v.set(self.sub_style.margin_v)
        self.slider_margin_v.pack(fill="x", padx=12, pady=(2, 6))

        # Căn lề Alignment
        ctk.CTkLabel(self.card_sub_ctrl, text="📐 Căn lề vị trí:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(2, 2))
        self.seg_alignment = ctk.CTkSegmentedButton(
            self.card_sub_ctrl,
            values=["⬇️ Dưới cùng", "⏸️ Giữa màn hình", "⬆️ Trên cùng"],
            command=self._on_alignment_changed,
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8"
        )
        if self.sub_style.alignment == 5:
            self.seg_alignment.set("⏸️ Giữa màn hình")
        elif self.sub_style.alignment == 8:
            self.seg_alignment.set("⬆️ Trên cùng")
        else:
            self.seg_alignment.set("⬇️ Dưới cùng")
        self.seg_alignment.pack(fill="x", padx=12, pady=(0, 8))

        # Font chữ & Cỡ chữ
        font_row = ctk.CTkFrame(self.card_sub_ctrl, fg_color="transparent")
        font_row.pack(fill="x", padx=12, pady=2)
        font_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(font_row, text="Font chữ:").grid(row=0, column=0, sticky="w")
        self.cmb_font = ctk.CTkComboBox(
            font_row,
            values=["Georgia", "Times New Roman", "Cambria", "Arial", "Montserrat", "Roboto", "Tahoma", "Verdana", "Segoe UI"],
            command=self._on_font_changed
        )
        self.cmb_font.set(getattr(self.sub_style, "font_name", "Georgia"))
        self.cmb_font.grid(row=1, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkLabel(font_row, text="Cỡ chữ (Size):").grid(row=0, column=1, sticky="w")
        self.cmb_font_size = ctk.CTkComboBox(
            font_row,
            values=["16", "18", "20", "22", "24", "26", "28", "32", "36", "40", "44", "48", "54", "60"],
            command=self._on_font_size_changed
        )
        self.cmb_font_size.set(str(self.sub_style.font_size))
        self.cmb_font_size.grid(row=1, column=1, sticky="ew", padx=(4, 0))

        # Mẫu chữ CapCut Presets
        ctk.CTkLabel(
            self.card_sub_ctrl,
            text="🎨 Mẫu chữ CapCut:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        preset_grid = ctk.CTkFrame(self.card_sub_ctrl, fg_color="#18181b", corner_radius=6)
        preset_grid.pack(fill="x", padx=12, pady=(0, 8))
        for c in range(6):
            preset_grid.grid_columnconfigure(c, weight=1)

        self.preset_buttons = {}
        for idx, (p_id, p_val) in enumerate(SUBTITLE_PRESETS.items()):
            r = idx // 6
            c = idx % 6
            is_sel = (p_id == getattr(self.sub_style, "preset_id", "badge_white_on_black"))
            btn = ctk.CTkButton(
                preset_grid,
                text=p_val.get("preview_text", "Aa"),
                font=ctk.CTkFont(size=14, weight="bold"),
                width=44,
                height=36,
                corner_radius=6,
                fg_color=p_val["bg_color"],
                text_color=p_val["fg_color"],
                border_color="#06b6d4" if is_sel else (p_val["border_color"] if p_val["border_color"] != "transparent" else "#3f3f46"),
                border_width=3 if is_sel else 1,
                hover_color=p_val["bg_color"],
                command=lambda pid=p_id: self._select_preset(pid)
            )
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="ew")
            self.preset_buttons[p_id] = btn

        self.lbl_selected_preset = ctk.CTkLabel(
            self.card_sub_ctrl,
            text=f"Mẫu: {self.sub_style.name}",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        )
        self.lbl_selected_preset.pack(anchor="w", padx=12, pady=(0, 6))

        # Test Text Preview Input
        ctk.CTkLabel(self.card_sub_ctrl, text="💬 Câu chữ xem thử:").pack(anchor="w", padx=12, pady=(2, 2))
        self.entry_sample_text = ctk.CTkEntry(self.card_sub_ctrl, height=28)
        self.entry_sample_text.insert(0, self.sample_text)
        self.entry_sample_text.pack(fill="x", padx=12, pady=(0, 10))
        self.entry_sample_text.bind("<KeyRelease>", self._on_sample_text_changed)

        # 2. BẢNG ĐIỀU KHIỂN VÙNG LÀM MỜ (BLUR REGION)
        self.card_blur_ctrl = ctk.CTkFrame(right_scroll, corner_radius=8)
        self.card_blur_ctrl.pack(fill="x", padx=4, pady=4)

        ctk.CTkLabel(
            self.card_blur_ctrl,
            text="🟥 Vùng Làm Mờ Phụ Đề Gốc",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ef4444"
        ).pack(anchor="w", padx=12, pady=(10, 4))

        # Preset Buttons Vùng Mờ
        blur_preset_row = ctk.CTkFrame(self.card_blur_ctrl, fg_color="transparent")
        blur_preset_row.pack(fill="x", padx=12, pady=(2, 4))

        ctk.CTkButton(blur_preset_row, text="📍 Đáy", width=58, height=26, fg_color="#334155", hover_color="#475569", command=self._apply_bottom_preset).pack(side="left", padx=(0, 2))
        ctk.CTkButton(blur_preset_row, text="📍 Giữa", width=58, height=26, fg_color="#334155", hover_color="#475569", command=self._apply_middle_preset).pack(side="left", padx=2)
        ctk.CTkButton(blur_preset_row, text="📍 Đỉnh", width=58, height=26, fg_color="#334155", hover_color="#475569", command=self._apply_top_preset).pack(side="left", padx=2)
        ctk.CTkButton(blur_preset_row, text="🎯 Chuẩn Douyin", width=110, height=26, fg_color="#0284c7", hover_color="#0369a1", font=ctk.CTkFont(size=11, weight="bold"), command=self._apply_douyin_custom_preset).pack(side="left", padx=(2, 0))

        # Ô nhập tọa độ tùy chỉnh (Custom Pixel Coordinates: X, Y, W, H)
        coords_input_grid = ctk.CTkFrame(self.card_blur_ctrl, fg_color="#18181b", corner_radius=6)
        coords_input_grid.pack(fill="x", padx=12, pady=(4, 4))
        for col in range(4):
            coords_input_grid.grid_columnconfigure(col, weight=1)

        ctk.CTkLabel(coords_input_grid, text="X (px):", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8").grid(row=0, column=0, sticky="w", padx=4, pady=(2, 0))
        self.entry_roi_x = ctk.CTkEntry(coords_input_grid, width=54, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_roi_x.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 4))
        self.entry_roi_x.bind("<KeyRelease>", self._on_blur_entries_edited)

        ctk.CTkLabel(coords_input_grid, text="Y (px):", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8").grid(row=0, column=1, sticky="w", padx=4, pady=(2, 0))
        self.entry_roi_y = ctk.CTkEntry(coords_input_grid, width=54, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_roi_y.grid(row=1, column=1, sticky="ew", padx=2, pady=(0, 4))
        self.entry_roi_y.bind("<KeyRelease>", self._on_blur_entries_edited)

        ctk.CTkLabel(coords_input_grid, text="W (px):", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8").grid(row=0, column=2, sticky="w", padx=4, pady=(2, 0))
        self.entry_roi_w = ctk.CTkEntry(coords_input_grid, width=54, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_roi_w.grid(row=1, column=2, sticky="ew", padx=2, pady=(0, 4))
        self.entry_roi_w.bind("<KeyRelease>", self._on_blur_entries_edited)

        ctk.CTkLabel(coords_input_grid, text="H (px):", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8").grid(row=0, column=3, sticky="w", padx=4, pady=(2, 0))
        self.entry_roi_h = ctk.CTkEntry(coords_input_grid, width=54, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_roi_h.grid(row=1, column=3, sticky="ew", padx=2, pady=(0, 4))
        self.entry_roi_h.bind("<KeyRelease>", self._on_blur_entries_edited)

        # Thông số vùng mờ
        self.lbl_blur_info = ctk.CTkLabel(
            self.card_blur_ctrl,
            text=f"Tọa độ: X={self.roi_x or 293}, Y={self.roi_y or 517}, W={self.roi_w or 683}, H={self.roi_h or 50} (Y=71.8%)",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="gray70"
        )
        self.lbl_blur_info.pack(anchor="w", padx=12, pady=(2, 8))

        # -------------------------------------------------------------
        # BOTTOM BAR: SAVE & APPLY
        # -------------------------------------------------------------
        bottom_frame = ctk.CTkFrame(self, height=54, corner_radius=10)
        bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 10))
        bottom_frame.grid_columnconfigure(0, weight=1)

        btn_cancel = ctk.CTkButton(
            bottom_frame, text="Hủy bỏ", width=100, height=36,
            fg_color="#4b5563", hover_color="#374151",
            command=self.destroy
        )
        btn_cancel.pack(side="left", padx=14, pady=8)

        self.btn_save = ctk.CTkButton(
            bottom_frame, text="✔ LƯU & ÁP DỤNG CẢ 2 CÀI ĐẶT", width=260, height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981", hover_color="#059669",
            command=self._save_and_close
        )
        self.btn_save.pack(side="right", padx=14, pady=8)

    def _sync_ui_from_style(self):
        """Đồng bộ giao diện từ SubtitleStyle hiện tại"""
        self.slider_margin_v.set(self.sub_style.margin_v)
        self.lbl_margin_val.configure(text=f"{self.sub_style.margin_v}px")
        self.cmb_font.set(self.sub_style.font_name)
        self.cmb_font_size.set(str(self.sub_style.font_size))
        if self.sub_style.alignment == 5:
            self.seg_alignment.set("⏸️ Giữa màn hình")
        elif self.sub_style.alignment == 8:
            self.seg_alignment.set("⬆️ Trên cùng")
        else:
            self.seg_alignment.set("⬇️ Dưới cùng")
        self._sync_blur_entries_from_roi()

    def _sync_blur_entries_from_roi(self):
        """Đồng bộ giá trị từ roi_x/y/w/h vào các ô nhập Entry"""
        if hasattr(self, "entry_roi_x") and self.roi_x is not None:
            self.entry_roi_x.delete(0, "end")
            self.entry_roi_x.insert(0, str(int(self.roi_x)))
        if hasattr(self, "entry_roi_y") and self.roi_y is not None:
            self.entry_roi_y.delete(0, "end")
            self.entry_roi_y.insert(0, str(int(self.roi_y)))
        if hasattr(self, "entry_roi_w") and self.roi_w is not None:
            self.entry_roi_w.delete(0, "end")
            self.entry_roi_w.insert(0, str(int(self.roi_w)))
        if hasattr(self, "entry_roi_h") and self.roi_h is not None:
            self.entry_roi_h.delete(0, "end")
            self.entry_roi_h.insert(0, str(int(self.roi_h)))

    def _on_blur_entries_edited(self, _event=None):
        """Cập nhật tọa độ vùng mờ khi người dùng gõ trực tiếp vào ô X, Y, W, H"""
        try:
            x_str = self.entry_roi_x.get().strip()
            y_str = self.entry_roi_y.get().strip()
            w_str = self.entry_roi_w.get().strip()
            h_str = self.entry_roi_h.get().strip()
            if not x_str or not y_str or not w_str or not h_str:
                return
            x = int(x_str)
            y = int(y_str)
            w = int(w_str)
            h = int(h_str)
            if self.orig_image:
                orig_w, orig_h = self.orig_image.size
                self.roi_x = max(0, min(x, orig_w - 2))
                self.roi_y = max(0, min(y, orig_h - 2))
                self.roi_w = max(2, min(w, orig_w - self.roi_x))
                self.roi_h = max(2, min(h, orig_h - self.roi_y))
            else:
                self.roi_x, self.roi_y, self.roi_w, self.roi_h = x, y, w, h
            self._draw_canvas(update_entries=False)
        except ValueError:
            pass

    def _apply_douyin_custom_preset(self):
        """Áp dụng tọa độ vùng mờ phụ đề Douyin chuẩn: X=293, Y=517, W=683, H=50 (Y=71.8%)"""
        if not self.orig_image:
            return
        w, h = self.orig_image.size
        if w >= 1200 and h >= 700:
            scale_x = w / 1280.0
            scale_y = h / 720.0
            self.roi_x = int(293 * scale_x)
            self.roi_y = int(517 * scale_y)
            self.roi_w = int(683 * scale_x)
            self.roi_h = int(50 * scale_y)
        else:
            self.roi_x = 293
            self.roi_y = 517
            self.roi_w = 683
            self.roi_h = 50
        self._sync_blur_entries_from_roi()
        self._draw_canvas(update_entries=False)

    def _apply_bottom_preset(self):
        if not self.orig_image:
            return
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.718)
        self.roi_w = w
        self.roi_h = max(30, int(h * 0.0694))
        self._sync_blur_entries_from_roi()
        self._draw_canvas(update_entries=False)

    def _apply_top_preset(self):
        if not self.orig_image:
            return
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.06)
        self.roi_w = w
        self.roi_h = int(h * 0.14)
        self._sync_blur_entries_from_roi()
        self._draw_canvas(update_entries=False)

    def _apply_middle_preset(self):
        if not self.orig_image:
            return
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.44)
        self.roi_w = w
        self.roi_h = int(h * 0.16)
        self._sync_blur_entries_from_roi()
        self._draw_canvas(update_entries=False)

    def _on_mode_switched(self, val: str):
        if "Phụ Đề" in val:
            self.active_mode = "subtitle"
            self.lbl_mode_hint.configure(text="👉 Kéo trực tiếp trên hình để đổi vị trí phụ đề hoặc chỉnh ở cột bên phải")
            self.canvas.configure(cursor="fleur")
        else:
            self.active_mode = "blur"
            self.lbl_mode_hint.configure(text="👉 Kéo chuột trên hình để vẽ vùng làm mờ phụ đề gốc")
            self.canvas.configure(cursor="crosshair")
        self._draw_canvas()

    def _on_margin_slider_changed(self, val: float):
        px = int(val)
        self.sub_style.margin_v = px
        self.lbl_margin_val.configure(text=f"{px}px")
        self._draw_canvas()

    def _on_alignment_changed(self, val: str):
        if "Giữa" in val:
            self.sub_style.alignment = 5
        elif "Trên" in val:
            self.sub_style.alignment = 8
        else:
            self.sub_style.alignment = 2
        self._draw_canvas()

    def _on_font_changed(self, val: str):
        self.sub_style.font_name = val
        self._draw_canvas()

    def _on_font_size_changed(self, val: str):
        try:
            self.sub_style.font_size = int(val)
            self._draw_canvas()
        except ValueError:
            pass

    def _on_sample_text_changed(self, event):
        self.sample_text = self.entry_sample_text.get()
        self._draw_canvas()

    def _select_preset(self, preset_id: str):
        if preset_id not in SUBTITLE_PRESETS:
            return
        p_info = SUBTITLE_PRESETS[preset_id]
        p_style = p_info["style"]
        self.sub_style.preset_id = preset_id
        self.sub_style.name = p_info["name"]
        self.sub_style.primary_color = p_style.primary_color
        self.sub_style.outline_color = p_style.outline_color
        self.sub_style.back_color = p_style.back_color
        self.sub_style.outline_width = p_style.outline_width
        self.sub_style.shadow = p_style.shadow
        self.sub_style.border_style = p_style.border_style
        self.sub_style.bold = p_style.bold

        # Highlight nút preset
        for pid, btn in self.preset_buttons.items():
            if pid == preset_id:
                btn.configure(border_color="#06b6d4", border_width=3)
            else:
                orig_bc = SUBTITLE_PRESETS[pid]["border_color"]
                btn.configure(border_color=orig_bc if orig_bc != "transparent" else "#3f3f46", border_width=1)

        self.lbl_selected_preset.configure(text=f"Mẫu: {p_info['name']}")
        self._draw_canvas()

    def _seek_relative(self, offset_sec: float):
        new_t = min(max(0.0, self.current_time_sec + offset_sec), self.video_duration)
        self.slider_timeline.set(new_t)
        self._on_timeline_slider_changed(new_t)

    def _on_timeline_slider_changed(self, val: float):
        self.current_time_sec = float(val)
        self.lbl_time.configure(
            text=f"⏱️ {self._format_time(self.current_time_sec)} / {self._format_time(self.video_duration)}"
        )

        cache_key = int(self.current_time_sec * 2)
        if cache_key in self.frame_cache:
            self.orig_image = self.frame_cache[cache_key]
            self._draw_canvas()
            return

        self.pending_seek_sec = self.current_time_sec
        if self._seek_timer:
            self.after_cancel(self._seek_timer)
        self._seek_timer = self.after(80, self._do_async_frame_seek)

    def _do_async_frame_seek(self):
        if self.pending_seek_sec is None or self.is_fetching_frame:
            return

        target_sec = self.pending_seek_sec
        self.pending_seek_sec = None
        self.is_fetching_frame = True

        def _worker():
            try:
                img = self._extract_video_frame(target_sec)
                if img:
                    cache_key = int(target_sec * 2)
                    self.frame_cache[cache_key] = img

                    def _update_ui():
                        self.orig_image = img
                        self._draw_canvas()
                        self.is_fetching_frame = False
                        if self.pending_seek_sec is not None:
                            self._do_async_frame_seek()

                    self.after(0, _update_ui)
                else:
                    self.is_fetching_frame = False
            except Exception:
                self.is_fetching_frame = False

        threading.Thread(target=_worker, daemon=True).start()

    def _on_mouse_down(self, event):
        self.is_dragging = True
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def _on_mouse_drag(self, event):
        if not self.is_dragging or not self.orig_image:
            return

        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        orig_w, orig_h = self.orig_image.size

        img_disp_w = int(orig_w * self.scale_factor)
        img_disp_h = int(orig_h * self.scale_factor)
        offset_x = (c_w - img_disp_w) // 2
        offset_y = (c_h - img_disp_h) // 2

        if self.active_mode == "blur":
            # Kéo vẽ vùng làm mờ
            x1_disp = min(max(self.drag_start_x, offset_x), offset_x + img_disp_w)
            y1_disp = min(max(self.drag_start_y, offset_y), offset_y + img_disp_h)
            x2_disp = min(max(event.x, offset_x), offset_x + img_disp_w)
            y2_disp = min(max(event.y, offset_y), offset_y + img_disp_h)

            left_disp = min(x1_disp, x2_disp)
            top_disp = min(y1_disp, y2_disp)
            w_disp = abs(x2_disp - x1_disp)
            h_disp = abs(y2_disp - y1_disp)

            self.roi_x = int((left_disp - offset_x) / self.scale_factor)
            self.roi_y = int((top_disp - offset_y) / self.scale_factor)
            self.roi_w = int(w_disp / self.scale_factor)
            self.roi_h = int(h_disp / self.scale_factor)
            self._sync_blur_entries_from_roi()

        else:
            # CHỈNH TAY PHỤ ĐỀ: Di chuyển vị trí phụ đề bằng chuột
            dy_disp = event.y - offset_y
            target_orig_y = int(dy_disp / self.scale_factor)
            target_orig_y = max(10, min(target_orig_y, orig_h - 10))

            if self.sub_style.alignment == 8:
                # Top alignment
                new_margin = max(10, min(target_orig_y, orig_h - 20))
            elif self.sub_style.alignment == 5:
                # Middle alignment
                new_margin = 0
            else:
                # Bottom alignment (mặc định)
                new_margin = max(10, min(orig_h - target_orig_y, orig_h - 20))

            self.sub_style.margin_v = new_margin
            self.slider_margin_v.set(new_margin)
            self.lbl_margin_val.configure(text=f"{new_margin}px")

        self._draw_canvas(update_entries=False)

    def _on_mouse_up(self, event):
        self.is_dragging = False
        if self.active_mode == "blur":
            if (self.roi_w or 0) < 10 or (self.roi_h or 0) < 10:
                self._apply_douyin_custom_preset()

    def _draw_canvas(self, update_entries: bool = True):
        """Vẽ lại hình ảnh preview, vùng làm mờ và hộp phụ đề trực quan lên Canvas"""
        if not self.orig_image:
            return

        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        if c_w < 50 or c_h < 50:
            return

        orig_w, orig_h = self.orig_image.size
        scale_w = (c_w - 20) / orig_w
        scale_h = (c_h - 20) / orig_h
        self.scale_factor = min(scale_w, scale_h, 1.0)

        disp_w = int(orig_w * self.scale_factor)
        disp_h = int(orig_h * self.scale_factor)
        offset_x = (c_w - disp_w) // 2
        offset_y = (c_h - disp_h) // 2

        if update_entries:
            self._sync_blur_entries_from_roi()

        preview_img = self.orig_image.copy()

        # 1. Làm mờ vùng ROI
        if self.roi_x is not None and self.roi_y is not None and self.roi_w and self.roi_h:
            rx = max(0, min(self.roi_x, orig_w - 1))
            ry = max(0, min(self.roi_y, orig_h - 1))
            rw = max(1, min(self.roi_w, orig_w - rx))
            rh = max(1, min(self.roi_h, orig_h - ry))

            roi_crop = preview_img.crop((rx, ry, rx + rw, ry + rh))
            roi_blurred = roi_crop.filter(ImageFilter.BoxBlur(radius=15))
            preview_img.paste(roi_blurred, (rx, ry))

        resized_img = preview_img.resize((disp_w, disp_h), Image.Resampling.BILINEAR)
        self.photo_img = ImageTk.PhotoImage(resized_img)

        self.canvas.delete("all")
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.photo_img)

        # 2. Vẽ viền Bounding Box cho Vùng Làm Mờ (Màu đỏ)
        if self.roi_x is not None and self.roi_y is not None and self.roi_w and self.roi_h:
            bx1 = offset_x + int(self.roi_x * self.scale_factor)
            by1 = offset_y + int(self.roi_y * self.scale_factor)
            bx2 = bx1 + int(self.roi_w * self.scale_factor)
            by2 = by1 + int(self.roi_h * self.scale_factor)

            is_blur_active = (self.active_mode == "blur")
            border_col = "#ef4444" if is_blur_active else "#991b1b"
            width_val = 2 if is_blur_active else 1

            self.canvas.create_rectangle(bx1 - 1, by1 - 1, bx2 + 1, by2 + 1, outline="#000000", width=width_val + 1)
            self.canvas.create_rectangle(bx1, by1, bx2, by2, outline=border_col, width=width_val, dash=(4, 2) if not is_blur_active else ())

            # Label tag vùng mờ
            self.canvas.create_rectangle(bx1, by1 - 20, bx1 + 130, by1, fill=border_col, outline="")
            self.canvas.create_text(bx1 + 65, by1 - 10, text="VÙNG LÀM MỜ GỐC", fill="#ffffff", font=("Arial", 8, "bold"))

            # Cập nhật Label thông số
            self.lbl_blur_info.configure(
                text=f"Tọa độ: X={self.roi_x}, Y={self.roi_y}, W={self.roi_w}, H={self.roi_h} (Y={self.roi_y/orig_h*100:.1f}%)"
            )

        # 3. Vẽ HỘP PHỤ ĐỀ TIẾNG VIỆT ĐƯỢC ĐỊNH VỊ CHÍNH XÁC (Màu Cyan / Kiểu Chữ Thật)
        # Tính kích thước hiệu dụng và tọa độ Y của phụ đề trên video gốc
        sub_font_size = self.sub_style.font_size
        sub_margin_v = self.sub_style.margin_v

        is_landscape = (orig_w >= orig_h)
        base_h = 720.0 if is_landscape else 1280.0
        font_multiplier = 1.45 if is_landscape else 1.75
        effective_font_size = max(14, int(round(sub_font_size * (orig_h / base_h) * font_multiplier)))

        if self.sub_style.alignment == 8:
            # Top
            sub_orig_y = sub_margin_v + effective_font_size // 2
        elif self.sub_style.alignment == 5:
            # Middle
            sub_orig_y = orig_h // 2
        else:
            # Bottom (mặc định)
            sub_orig_y = orig_h - sub_margin_v - effective_font_size // 2

        sub_disp_y = offset_y + int(sub_orig_y * self.scale_factor)
        sub_disp_x = offset_x + disp_w // 2

        # Lấy màu và kiểu dáng thật từ SubtitleStyle
        fg_hex = ass_to_hex(self.sub_style.primary_color, "#ffffff")
        outline_hex = ass_to_hex(self.sub_style.outline_color, "#000000")
        bg_badge_hex = ass_to_hex(self.sub_style.back_color, "#000000")
        is_badge = (getattr(self.sub_style, "border_style", 1) == 3)
        font_size_disp = max(12, min(48, int(effective_font_size * self.scale_factor)))

        text_to_draw = self.sample_text if self.sample_text.strip() else "[ Phụ đề Tiếng Việt ]"
        font_family = self.sub_style.font_name or "Georgia"

        # Ước lượng kích thước hộp chữ
        char_count = len(text_to_draw)
        approx_w = int(char_count * font_size_disp * 0.58) + 24
        approx_h = int(font_size_disp * 1.5) + 8

        sub_box_x1 = max(offset_x + 4, sub_disp_x - approx_w // 2)
        sub_box_y1 = sub_disp_y - approx_h // 2
        sub_box_x2 = min(offset_x + disp_w - 4, sub_disp_x + approx_w // 2)
        sub_box_y2 = sub_disp_y + approx_h // 2

        is_sub_active = (self.active_mode == "subtitle")

        # Vẽ nền Badge nếu có
        if is_badge:
            self.canvas.create_rectangle(
                sub_box_x1, sub_box_y1, sub_box_x2, sub_box_y2,
                fill=bg_badge_hex, outline=""
            )

        # Vẽ bóng / viền chữ mô phỏng
        if not is_badge and self.sub_style.outline_width > 0:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)]:
                self.canvas.create_text(
                    sub_disp_x + dx, sub_disp_y + dy,
                    text=text_to_draw,
                    fill=outline_hex,
                    font=(font_family, font_size_disp, "bold" if self.sub_style.bold else "normal")
                )

        # Vẽ văn bản phụ đề chính
        self.canvas.create_text(
            sub_disp_x, sub_disp_y,
            text=text_to_draw,
            fill=fg_hex,
            font=(font_family, font_size_disp, "bold" if self.sub_style.bold else "normal")
        )

        # Vẽ khung chọn tương tác cho Phụ Đề
        sub_border_col = "#38bdf8" if is_sub_active else "#0284c7"
        self.canvas.create_rectangle(
            sub_box_x1 - 2, sub_box_y1 - 2, sub_box_x2 + 2, sub_box_y2 + 2,
            outline=sub_border_col,
            width=2 if is_sub_active else 1,
            dash=(3, 2) if not is_sub_active else ()
        )

        # Tag nhãn phụ đề
        if is_sub_active:
            tag_text = "✋ VỊ TRÍ PHỤ ĐỀ (KÉO CHUỘT ĐỂ DI CHUYỂN)"
            tag_w = 230
            self.canvas.create_rectangle(sub_box_x1 - 2, sub_box_y1 - 20, sub_box_x1 + tag_w, sub_box_y1 - 2, fill="#0284c7", outline="")
            self.canvas.create_text(sub_box_x1 + tag_w // 2, sub_box_y1 - 11, text=tag_text, fill="#ffffff", font=("Arial", 8, "bold"))

    def _save_and_close(self):
        """Lưu cấu hình vùng làm mờ và kiểu dáng phụ đề đã chỉnh tay"""
        orig_w, orig_h = self.orig_image.size
        y_ratio = float(self.roi_y / orig_h) if orig_h > 0 else 0.72
        height_ratio = float(self.roi_h / orig_h) if orig_h > 0 else 0.18

        saved_region = BlurRegion(
            x=self.roi_x,
            y=self.roi_y,
            width=self.roi_w,
            height=self.roi_h,
            y_ratio=y_ratio,
            height_ratio=height_ratio,
            blur_power=15,
            enabled=True,
            smart_blur=getattr(self.blur_region, "smart_blur", True),
            pad_before=getattr(self.blur_region, "pad_before", 0.15),
            pad_after=getattr(self.blur_region, "pad_after", 0.20),
            min_gap_merge=getattr(self.blur_region, "min_gap_merge", 0.50)
        )

        saved_style = copy.copy(self.sub_style)

        if self.on_save_callback:
            # Hỗ trợ cả 2 dạng callback: nhận (region, style) hoặc chỉ nhận (region)
            try:
                self.on_save_callback(saved_region, saved_style)
            except TypeError:
                self.on_save_callback(saved_region)

        self.destroy()
