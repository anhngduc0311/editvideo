"""
roi_selector.py - Interactive Visual Subtitle Blur Region Selector (ROI Cropper)
"""

import logging
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable, Optional, Tuple
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image, ImageFilter, ImageTk

from config import BlurRegion

logger = logging.getLogger(__name__)


class VisualROISelectorDialog(ctk.CTkToplevel):
    """
    Cửa sổ đồ họa cho phép người dùng kéo chuột trực tiếp trên khung hình video
    để khoanh vùng phụ đề / logo cần làm mờ (Interactive Bounding Box Selector).
    """

    def __init__(
        self,
        parent,
        video_path: Optional[Path] = None,
        initial_blur_region: Optional[BlurRegion] = None,
        on_save_callback: Optional[Callable[[BlurRegion], None]] = None
    ):
        super().__init__(parent)

        self.title("🎯 Khoanh Vùng Làm Mờ Phụ Đề Trực Quan (Interactive Subtitle Blur Selector)")
        self.geometry("960, 780")
        self.minsize(850, 680)

        # Đưa cửa sổ lên trên cùng
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

        self.video_path = Path(video_path) if video_path else None
        self.blur_region = initial_blur_region or BlurRegion()
        self.on_save_callback = on_save_callback

        # Dữ liệu ảnh
        self.orig_image: Optional[Image.Image] = None
        self.disp_image: Optional[Image.Image] = None
        self.photo_img = None
        self.scale_factor = 1.0

        # Tọa độ vùng chọn trên ảnh gốc (Pixel)
        self.roi_x = self.blur_region.x
        self.roi_y = self.blur_region.y
        self.roi_w = self.blur_region.width
        self.roi_h = self.blur_region.height

        # Trạng thái kéo chuột
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False

        self._load_frame()
        self._build_ui()
        self._draw_canvas()

    def _extract_video_frame(self, video_file: Path) -> Image.Image:
        """Trích xuất 1 khung hình từ video để làm preview"""
        tmp_img = Path(tempfile.gettempdir()) / f"douyin_frame_{int(time.time()*1000)}.jpg"
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", "00:00:02",
                "-i", str(video_file),
                "-vframes", "1",
                "-q:v", "2",
                str(tmp_img)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and tmp_img.exists():
                img = Image.open(tmp_img).convert("RGB")
                try:
                    tmp_img.unlink()
                except Exception:
                    pass
                return img
        except Exception as e:
            logger.warning(f"Không thể trích xuất frame bằng ffmpeg ({e}), dùng frame mặc định.")

        # Tạo ảnh mẫu mặc định 9:16 nếu trích xuất thất bại
        return self._create_placeholder_frame()

    def _create_placeholder_frame(self) -> Image.Image:
        """Tạo khung hình 1080x1920 mẫu giả lập video Douyin"""
        w, h = 1080, 1920
        img = Image.new("RGB", (w, h), color=(20, 24, 33))
        # Có thể vẽ watermark mẫu
        return img

    def _load_frame(self):
        if self.video_path and self.video_path.exists():
            self.orig_image = self._extract_video_frame(self.video_path)
        else:
            self.orig_image = self._create_placeholder_frame()

        orig_w, orig_h = self.orig_image.size

        # Khởi tạo tọa độ mặc định nếu chưa có
        if self.roi_w is None:
            self.roi_w = orig_w
        if self.roi_h is None:
            self.roi_h = int(orig_h * self.blur_region.height_ratio)
        if self.roi_x is None:
            self.roi_x = int((orig_w - self.roi_w) / 2)
        if self.roi_y is None:
            self.roi_y = int(orig_h * self.blur_region.y_ratio)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # -------------------------------------------------------------
        # TOP TOOLBAR: Hướng dẫn & Presets
        # -------------------------------------------------------------
        top_frame = ctk.CTkFrame(self, height=55, corner_radius=8, fg_color=("#1e293b", "#0f172a"))
        top_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            top_frame,
            text="👉 Kéo chuột trên khung hình để vẽ vùng làm mờ:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=(12, 10), pady=10)

        # Preset Buttons
        btn_preset_bottom = ctk.CTkButton(
            top_frame, text="📍 Đáy (Sub Mặc định)", width=130, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._apply_bottom_preset
        )
        btn_preset_bottom.pack(side="left", padx=4)

        btn_preset_top = ctk.CTkButton(
            top_frame, text="📍 Đỉnh / Logo", width=110, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._apply_top_preset
        )
        btn_preset_top.pack(side="left", padx=4)

        btn_preset_middle = ctk.CTkButton(
            top_frame, text="📍 Giữa màn hình", width=120, height=28,
            fg_color="#334155", hover_color="#475569",
            command=self._apply_middle_preset
        )
        btn_preset_middle.pack(side="left", padx=4)

        # -------------------------------------------------------------
        # CENTER CANVAS: Hiển thị Video Frame và Bounding Box
        # -------------------------------------------------------------
        canvas_container = ctk.CTkFrame(self, corner_radius=10)
        canvas_container.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        canvas_container.grid_columnconfigure(0, weight=1)
        canvas_container.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_container,
            bg="#0b0f19",
            highlightthickness=0,
            cursor="crosshair"
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        # Sự kiện chuột kéo vẽ Bounding Box
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())

        # -------------------------------------------------------------
        # BOTTOM CONTROLS & SAVE
        # -------------------------------------------------------------
        bottom_frame = ctk.CTkFrame(self, corner_radius=10)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 12))
        bottom_frame.grid_columnconfigure(0, weight=1)

        # Row 1: Thông số tọa độ chi tiết
        info_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        info_row.pack(fill="x", padx=12, pady=(8, 4))

        self.lbl_coords = ctk.CTkLabel(
            info_row,
            text="Tọa độ: X=0, Y=0, W=0, H=0",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_coords.pack(side="left")

        self.lbl_ratios = ctk.CTkLabel(
            info_row,
            text="Tỷ lệ: Y=72.0% | H=18.0%",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="gray70"
        )
        self.lbl_ratios.pack(side="right")

        # Row 2: Nút hành động
        btn_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 10))

        btn_cancel = ctk.CTkButton(
            btn_row, text="Hủy", width=90, height=36,
            fg_color="#4b5563", hover_color="#374151",
            command=self.destroy
        )
        btn_cancel.pack(side="left")

        self.btn_save = ctk.CTkButton(
            btn_row, text="✔ LƯU & ÁP DỤNG VÙNG NÀY", width=220, height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981", hover_color="#059669",
            command=self._save_and_close
        )
        self.btn_save.pack(side="right")

    def _apply_bottom_preset(self):
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.72)
        self.roi_w = w
        self.roi_h = int(h * 0.18)
        self._draw_canvas()

    def _apply_top_preset(self):
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.06)
        self.roi_w = w
        self.roi_h = int(h * 0.14)
        self._draw_canvas()

    def _apply_middle_preset(self):
        w, h = self.orig_image.size
        self.roi_x = 0
        self.roi_y = int(h * 0.44)
        self.roi_w = w
        self.roi_h = int(h * 0.16)
        self._draw_canvas()

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

        # Tính toán offset ảnh trên canvas
        img_disp_w = int(orig_w * self.scale_factor)
        img_disp_h = int(orig_h * self.scale_factor)
        offset_x = (c_w - img_disp_w) // 2
        offset_y = (c_h - img_disp_h) // 2

        # Tọa độ chuột quy đổi về pixel ảnh gốc
        x1_disp = min(max(self.drag_start_x, offset_x), offset_x + img_disp_w)
        y1_disp = min(max(self.drag_start_y, offset_y), offset_y + img_disp_h)
        x2_disp = min(max(event.x, offset_x), offset_x + img_disp_w)
        y2_disp = min(max(event.y, offset_y), offset_y + img_disp_h)

        left_disp = min(x1_disp, x2_disp)
        top_disp = min(y1_disp, y2_disp)
        w_disp = abs(x2_disp - x1_disp)
        h_disp = abs(y2_disp - y1_disp)

        # Chuyển sang tọa độ ảnh gốc
        self.roi_x = int((left_disp - offset_x) / self.scale_factor)
        self.roi_y = int((top_disp - offset_y) / self.scale_factor)
        self.roi_w = int(w_disp / self.scale_factor)
        self.roi_h = int(h_disp / self.scale_factor)

        self._draw_canvas()

    def _on_mouse_up(self, event):
        self.is_dragging = False
        # Đảm bảo kích thước tối thiểu
        if self.roi_w < 10 or self.roi_h < 10:
            self._apply_bottom_preset()

    def _draw_canvas(self):
        """Vẽ lại hình ảnh preview và Bounding box lên Canvas"""
        if not self.orig_image:
            return

        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        if c_w < 50 or c_h < 50:
            return

        orig_w, orig_h = self.orig_image.size
        # Tính tỷ lệ thu phóng vừa khít canvas
        scale_w = (c_w - 20) / orig_w
        scale_h = (c_h - 20) / orig_h
        self.scale_factor = min(scale_w, scale_h, 1.0)

        disp_w = int(orig_w * self.scale_factor)
        disp_h = int(orig_h * self.scale_factor)
        offset_x = (c_w - disp_w) // 2
        offset_y = (c_h - disp_h) // 2

        # Tạo ảnh preview với vùng làm mờ mô phỏng
        preview_img = self.orig_image.copy()

        if self.roi_x is not None and self.roi_y is not None and self.roi_w and self.roi_h:
            rx = max(0, min(self.roi_x, orig_w - 1))
            ry = max(0, min(self.roi_y, orig_h - 1))
            rw = max(1, min(self.roi_w, orig_w - rx))
            rh = max(1, min(self.roi_h, orig_h - ry))

            # Crop và làm mờ khu vực ROI
            roi_crop = preview_img.crop((rx, ry, rx + rw, ry + rh))
            roi_blurred = roi_crop.filter(ImageFilter.BoxBlur(radius=15))
            preview_img.paste(roi_blurred, (rx, ry))

        resized_img = preview_img.resize((disp_w, disp_h), Image.Resampling.BILINEAR)
        self.photo_img = ImageTk.PhotoImage(resized_img)

        self.canvas.delete("all")
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.photo_img)

        # Vẽ viền Bounding Box phát sáng
        if self.roi_x is not None and self.roi_y is not None and self.roi_w and self.roi_h:
            bx1 = offset_x + int(self.roi_x * self.scale_factor)
            by1 = offset_y + int(self.roi_y * self.scale_factor)
            bx2 = bx1 + int(self.roi_w * self.scale_factor)
            by2 = by1 + int(self.roi_h * self.scale_factor)

            # Viền ngoài màu đen mờ + viền trong màu đỏ/cyan nổi bật
            self.canvas.create_rectangle(bx1 - 1, by1 - 1, bx2 + 1, by2 + 1, outline="#000000", width=2)
            self.canvas.create_rectangle(bx1, by1, bx2, by2, outline="#ef4444", width=2)

            # Tag nhãn
            self.canvas.create_rectangle(bx1, by1 - 22, bx1 + 140, by1, fill="#ef4444", outline="")
            self.canvas.create_text(bx1 + 70, by1 - 11, text="VÙNG LÀM MỜ SUB", fill="#ffffff", font=("Arial", 9, "bold"))

            # Cập nhật Label thông số
            y_ratio = self.roi_y / orig_h if orig_h > 0 else 0.72
            h_ratio = self.roi_h / orig_h if orig_h > 0 else 0.18
            self.lbl_coords.configure(text=f"Tọa độ Pixel: X={self.roi_x}, Y={self.roi_y}, W={self.roi_w}, H={self.roi_h} (Gốc: {orig_w}x{orig_h})")
            self.lbl_ratios.configure(text=f"Tỷ lệ: Y={y_ratio*100:.1f}% | Height={h_ratio*100:.1f}%")

    def _save_and_close(self):
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
            enabled=True
        )

        if self.on_save_callback:
            self.on_save_callback(saved_region)

        self.destroy()
