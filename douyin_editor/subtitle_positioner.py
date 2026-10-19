"""Place translated subtitles on a video frame, using the export renderer for preview."""
import copy
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from config import PipelineConfig
from subtitle_burner import SubtitleBurner
from subtitle_layout import positioned_subtitles
from translator import parse_srt_string


class SubtitlePositionDialog(ctk.CTkToplevel):
    def __init__(self, parent, video_path, srt_path, style, speed_factor=1.0,
                 on_apply=None, on_skip=None):
        super().__init__(parent)
        self.title("Đặt vị trí chữ phụ đề trên video")
        self.geometry("1000x760")
        self.minsize(840, 640)
        self.configure(fg_color="#0b101b")
        self.transient(parent)
        self.style = copy.copy(style)
        self.video_path = Path(video_path)
        self.speed_factor = speed_factor
        self.on_apply, self.on_skip = on_apply, on_skip
        self._temporary = tempfile.TemporaryDirectory(prefix="subtitle_position_")
        self.directory = Path(self._temporary.name)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self._photo = None
        self._preview = None
        self._bounds = (0, 0, 1, 1)
        self._frame_index = None
        self._dragging = False
        self.items = parse_srt_string(Path(srt_path).read_text(encoding="utf-8"))
        if not self.items:
            self.destroy()
            raise ValueError("Không có câu phụ đề để xem trước.")
        if self.style.position_x is None:
            self.style.position_x = 0.5
        if self.style.position_y is None:
            self.style.position_y = max(0.1, min(0.9, 1 - (self.style.margin_v + self.style.font_size / 2) / 288))

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(self, fg_color="#172235", corner_radius=12)
        toolbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkLabel(toolbar, text="Kéo / nhấp để đặt tâm phụ đề. Nhả chuột để cập nhật xem trước.",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(toolbar, text="Chữ mẫu để đặt vị trí trước khi nhận diện / dịch. Áp dụng cho toàn bộ phụ đề video.",
                     font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w", padx=12, pady=(0, 6))
        row = ctk.CTkFrame(toolbar, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))
        for title, y in (("Trên", 0.15), ("Giữa", 0.5), ("Dưới", 0.83)):
            ctk.CTkButton(row, text=title, width=70, command=lambda value=y: self._preset(value)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text="Cỡ chữ:").pack(side="left", padx=(8, 6))
        self.font_size = ctk.CTkComboBox(row, values=[str(i) for i in (14, 18, 20, 22, 24, 28, 32, 36, 42, 48)],
                                       width=75, state="readonly", command=self._change_size)
        self.font_size.set(str(self.style.font_size))
        self.font_size.pack(side="left")
        self.cue_values = [f"{i+1}. {item.text.replace(chr(10), ' ')[:30]}" for i, item in enumerate(self.items[:50])]
        self.cue = ctk.CTkComboBox(row, values=self.cue_values, width=290, state="readonly",
                                 command=lambda _: self._render_preview())
        self.cue.set(self.cue_values[0])
        self.cue.pack(side="right")

        self.canvas = tk.Canvas(self, bg="#070d16", highlightthickness=0, cursor="fleur")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)
        self.canvas.bind("<Configure>", lambda _: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._mouse_down)
        self.canvas.bind("<B1-Motion>", self._mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)

        footer = ctk.CTkFrame(self, fg_color="#172235", corner_radius=12)
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.status = ctk.CTkLabel(footer, text="Đang tạo xem trước…", anchor="w")
        self.status.pack(fill="x", padx=12, pady=(8, 2))
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkButton(actions, text="Giữ cài đặt cũ & tiếp tục", width=205, fg_color="#334155",
                      command=self._skip).pack(side="left")
        self.btn_apply = ctk.CTkButton(actions, text="Áp dụng & tiếp tục", width=180, command=self._apply)
        self.btn_apply.pack(side="right")
        self._render_preview()

    def _read_frame(self, item):
        for timestamp in dict.fromkeys((item.start_seconds * self.speed_factor, 0)):
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-ss", str(timestamp),
                 "-i", str(self.video_path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                capture_output=True, check=True, timeout=20,
            )
            if result.stdout:
                with Image.open(io.BytesIO(result.stdout)) as image:
                    image.convert("RGB").save(self.directory / "frame.png")
                return
        raise ValueError("Không trích xuất được khung hình video.")

    def _render_preview(self):
        try:
            index = self.cue_values.index(self.cue.get())
            item = self.items[index]
            if self._frame_index != index:
                self._read_frame(item)
                self._frame_index = index
            sample = self.directory / "sample.srt"
            sample.write_text(f"1\n00:00:00,000 --> 00:00:10,000\n{item.text}\n", encoding="utf-8")
            subtitle_file = positioned_subtitles(sample, self.style, self.directory / "sample.ass")
            burner = SubtitleBurner(PipelineConfig(subtitle_style=self.style))
            subtitle_filter = f"subtitles='{burner._escape_ffmpeg_path(subtitle_file)}':force_style='{burner.build_force_style_string()}'"
            subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(self.directory / "frame.png"),
                 "-vf", subtitle_filter, "-frames:v", "1", str(self.directory / "preview.png")],
                capture_output=True, check=True, timeout=20,
            )
            with Image.open(self.directory / "preview.png") as image:
                self._preview = image.convert("RGB")
            self.status.configure(text=f"X: {self.style.position_x:.0%}  ·  Y: {self.style.position_y:.0%}  ·  Áp dụng vị trí này cho toàn bộ phụ đề", text_color="#93c5fd")
            self.btn_apply.configure(state="normal")
            self._draw()
        except Exception:
            self.status.configure(text="Không tạo được xem trước. Chọn câu khác hoặc giữ cài đặt cũ để tiếp tục.", text_color="#fda4af")
            self.btn_apply.configure(state="disabled")

    def _draw(self):
        if self._preview is None:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 2 or height < 2:
            return
        scale = min(width / self._preview.width, height / self._preview.height)
        w, h = max(1, int(self._preview.width * scale)), max(1, int(self._preview.height * scale))
        left, top = (width - w) // 2, (height - h) // 2
        self._bounds = (left, top, w, h)
        self._photo = ImageTk.PhotoImage(self._preview.resize((w, h), Image.Resampling.LANCZOS), master=self)
        self.canvas.delete("all")
        self.canvas.create_image(left, top, image=self._photo, anchor="nw")

    def _mouse_down(self, event):
        left, top, width, height = self._bounds
        self._dragging = left <= event.x <= left + width and top <= event.y <= top + height
        if self._dragging:
            self._mouse_move(event)

    def _mouse_move(self, event):
        if not self._dragging:
            return
        left, top, width, height = self._bounds
        self.style.position_x = max(0.05, min(0.95, (event.x - left) / width))
        self.style.position_y = max(0.05, min(0.95, (event.y - top) / height))
        x, y = left + width * self.style.position_x, top + height * self.style.position_y
        self.canvas.delete("target")
        self.canvas.create_line(x-12, y, x+12, y, fill="#38bdf8", width=2, tags="target")
        self.canvas.create_line(x, y-12, x, y+12, fill="#38bdf8", width=2, tags="target")

    def _mouse_up(self, event):
        if self._dragging:
            self._mouse_move(event)
            self._dragging = False
            self._render_preview()

    def _preset(self, y):
        self.style.position_x, self.style.position_y = 0.5, y
        self._render_preview()

    def _change_size(self, value):
        self.style.font_size = int(value)
        self._render_preview()

    def _apply(self):
        if self.on_apply:
            self.on_apply(copy.copy(self.style))
        self.destroy()

    def _skip(self):
        if self.on_skip:
            self.on_skip()
        self.destroy()

    def destroy(self):
        super().destroy()
        if hasattr(self, "_temporary"):
            self._temporary.cleanup()
