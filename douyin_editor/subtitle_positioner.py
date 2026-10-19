"""Place translated subtitles on a video frame, using the export renderer for preview."""
import copy
import io
import math
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
        self.speed_factor = float(speed_factor)
        if not math.isfinite(self.speed_factor) or self.speed_factor <= 0:
            self.speed_factor = 1.0
        self.on_apply, self.on_skip = on_apply, on_skip
        self._temporary = tempfile.TemporaryDirectory(prefix="subtitle_position_")
        self.directory = Path(self._temporary.name)
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self._photo = None
        self._preview = None
        self._bounds = (0, 0, 1, 1)
        self._frame_time = None
        self._seek_after = None
        self._closed = False
        self.duration = self._video_duration()
        self._dragging = False
        self.items = parse_srt_string(Path(srt_path).read_text(encoding="utf-8"))
        if not self.items:
            self.destroy()
            raise ValueError("Không có câu phụ đề để xem trước.")
        self.seek_time = self._clamp_time(self.items[0].start_seconds * self.speed_factor)
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
        ctk.CTkLabel(toolbar, text="Phụ đề đã dịch và đồng bộ · Tua video để xem đúng câu theo thời gian.",
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
        self.cue_values = [f"{i+1}. {item.text.replace(chr(10), ' ')[:30]}" for i, item in enumerate(self.items)]
        self.cue = ctk.CTkComboBox(row, values=self.cue_values, width=290, state="readonly",
                                 command=self._on_cue_selected)
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
        seek_row = ctk.CTkFrame(footer, fg_color="transparent")
        seek_row.pack(fill="x", padx=12, pady=(8, 0))
        state = "normal" if self.duration > 0 else "disabled"
        self.btn_back = ctk.CTkButton(seek_row, text="−5s", width=55, height=28, state=state,
                                     command=lambda: self._seek_to(self.seek_time - 5))
        self.btn_back.pack(side="left", padx=(0, 6))
        self.btn_forward = ctk.CTkButton(seek_row, text="+5s", width=55, height=28, state=state,
                                        command=lambda: self._seek_to(self.seek_time + 5))
        self.btn_forward.pack(side="left", padx=(0, 10))
        self.seek_slider = ctk.CTkSlider(seek_row, from_=0, to=max(self.duration, 0.1), state=state,
                                        command=self._on_seek)
        self.seek_slider.set(self.seek_time)
        self.seek_slider.pack(side="left", fill="x", expand=True)
        self.time_label = ctk.CTkLabel(seek_row, text="", width=140, font=ctk.CTkFont(size=12))
        self.time_label.pack(side="right", padx=(8, 0))
        self._update_time_label()
        ctk.CTkLabel(footer, text="Kéo thanh tua: câu dịch đổi theo lời thoại · Chọn câu phía trên để nhảy đến câu đó.",
                     font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w", padx=12)
        self.status = ctk.CTkLabel(footer, text="Đang tạo xem trước…", anchor="w")
        self.status.pack(fill="x", padx=12, pady=(8, 2))
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkButton(actions, text="Giữ cài đặt cũ & tiếp tục", width=205, fg_color="#334155",
                      command=self._skip).pack(side="left")
        self.btn_apply = ctk.CTkButton(actions, text="Áp dụng & tiếp tục", width=180, command=self._apply)
        self.btn_apply.pack(side="right")
        self._render_preview()

    def _video_duration(self):
        try:
            result = subprocess.run(
                [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(self.video_path)],
                capture_output=True, text=True, check=True, timeout=15,
            )
            duration = float(result.stdout.strip())
            return duration if math.isfinite(duration) and duration > 0 else 0.0
        except Exception:
            return 0.0

    def _clamp_time(self, value):
        limit = max(0.0, self.duration - 0.05) if self.duration else max(0.0, float(value))
        return max(0.0, min(float(value), limit))

    @staticmethod
    def _time_text(seconds):
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"

    def _update_time_label(self):
        self.time_label.configure(text=f"{self._time_text(self.seek_time)} / {self._time_text(self.duration)}" if self.duration else "Không đọc được thời lượng")

    def _cancel_seek(self):
        if self._seek_after is not None:
            self.after_cancel(self._seek_after)
            self._seek_after = None

    def _on_seek(self, value):
        self.seek_time = self._clamp_time(value)
        self._update_time_label()
        self._cancel_seek()
        # Coalesce slider motion; don't start a decoder for every mouse event.
        self._seek_after = self.after(180, self._commit_seek)

    def _commit_seek(self):
        self._seek_after = None
        if not self._closed:
            self._render_preview()

    def _seek_to(self, value):
        self._cancel_seek()
        self.seek_time = self._clamp_time(value)
        self.seek_slider.set(self.seek_time)
        self._update_time_label()
        self._render_preview()

    def _on_cue_selected(self, value):
        if value in self.cue_values:
            item = self.items[self.cue_values.index(value)]
            self._seek_to(item.start_seconds * self.speed_factor)

    def _active_cues(self):
        # The slider seeks the original source video. SRT timings refer to the
        # slowed audio used for recognition/TTS, before final export speed-up.
        subtitle_time = round(self.seek_time / self.speed_factor, 6)
        return [(index, item) for index, item in enumerate(self.items)
                if item.start_seconds <= subtitle_time < item.end_seconds]

    def _read_frame(self, target):
        # A seek near EOF may fall after the last frame, especially in low-FPS videos.
        for timestamp in dict.fromkeys((target, max(0, target - 0.1), max(0, target - 0.5), max(0, target - 1), 0)):
            result = subprocess.run(
                [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-ss", str(timestamp),
                 "-i", str(self.video_path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                capture_output=True, check=True, timeout=20,
            )
            if result.stdout:
                with Image.open(io.BytesIO(result.stdout)) as image:
                    image.convert("RGB").save(self.directory / "frame.png")
                self.seek_time = timestamp
                self.seek_slider.set(timestamp)
                self._update_time_label()
                return
        raise ValueError("Không trích xuất được khung hình video.")

    def _render_preview(self):
        try:
            if self._frame_time != self.seek_time:
                self._read_frame(self.seek_time)
                self._frame_time = self.seek_time
            active = self._active_cues()
            self.current_subtitle_text = "\n".join(item.text for _, item in active)
            self.cue.set(self.cue_values[active[0][0]] if active else "Không có phụ đề tại thời điểm này")
            preview = self.directory / "frame.png"
            if active:
                sample = self.directory / "sample.srt"
                sample.write_text("\n".join(f"{i+1}\n00:00:00,000 --> 00:00:10,000\n{item.text}\n" for i, (_, item) in enumerate(active)), encoding="utf-8")
                subtitle_file = positioned_subtitles(sample, self.style, self.directory / "sample.ass")
                burner = SubtitleBurner(PipelineConfig(subtitle_style=self.style))
                subtitle_filter = f"subtitles='{burner._escape_ffmpeg_path(subtitle_file)}':force_style='{burner.build_force_style_string()}'"
                preview = self.directory / "preview.png"
                subprocess.run(
                    [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(self.directory / "frame.png"),
                     "-vf", subtitle_filter, "-frames:v", "1", str(preview)],
                    capture_output=True, check=True, timeout=20,
                )
            with Image.open(preview) as image:
                self._preview = image.convert("RGB")
            context = f"Câu {active[0][0]+1}/{len(self.items)}" if active else "Không có lời phụ đề tại đây"
            self.status.configure(text=f"{context}  ·  X: {self.style.position_x:.0%}  ·  Y: {self.style.position_y:.0%}  ·  Vị trí áp dụng cho toàn bộ phụ đề", text_color="#93c5fd")
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
        self._closed = True
        if hasattr(self, "_seek_after"):
            self._cancel_seek()
        super().destroy()
        if hasattr(self, "_temporary"):
            self._temporary.cleanup()
