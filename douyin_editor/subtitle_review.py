"""Review translated SRT on the UI thread before synthesizing speech."""
import threading
from tkinter import messagebox
import customtkinter as ctk
from translator import parse_srt_string
from job_state import check_cancelled


def validate_translation(original_text, translated_text):
    original = parse_srt_string(original_text)
    translated = parse_srt_string(translated_text)
    identity = lambda items: [(s.index, s.start_seconds, s.end_seconds) for s in items]
    if (not original or identity(original) != identity(translated) or
            any(not s.text.strip() or s.end_seconds <= s.start_seconds or s.start_seconds < 0
                for s in translated)):
        raise ValueError("Giữ nguyên số câu, số thứ tự và mốc thời gian. Chỉ sửa nội dung lời dịch.")
    return translated


class SubtitleReviewDialog(ctk.CTkToplevel):
    def __init__(self, parent, original_path, translated_path, cancel_event, done):
        super().__init__(parent)
        self.title("Duyệt bản dịch trước khi tạo giọng")
        self.geometry("950x700")
        self.original_path = original_path
        self.translated_path = translated_path
        self.cancel_event = cancel_event
        self.done = done
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        ctk.CTkLabel(self, text="Đối chiếu bản gốc, sửa lời dịch ngắn gọn. Giữ nguyên số câu và mốc thời gian.",
                     wraplength=880).pack(padx=16, pady=12)
        panes = ctk.CTkFrame(self)
        panes.pack(fill="both", expand=True, padx=16)
        self.source = ctk.CTkTextbox(panes, width=400)
        self.source.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.source.insert("1.0", original_path.read_text(encoding="utf-8"))
        self.source.configure(state="disabled")
        self.editor = ctk.CTkTextbox(panes, width=450)
        self.editor.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.editor.insert("1.0", translated_path.read_text(encoding="utf-8"))
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(controls, text="Lưu & tạo giọng", command=self.approve).pack(side="right")
        ctk.CTkButton(controls, text="Hủy tác vụ", command=self.cancel).pack(side="left")
        self.after(200, self.poll_cancel)

    def approve(self):
        text = self.editor.get("1.0", "end").strip() + "\n"
        try:
            items = validate_translation(self.original_path.read_text(encoding="utf-8"), text)
            temporary = self.translated_path.with_suffix(".tmp")
            temporary.write_text("\n".join(s.to_srt_block() for s in items) + "\n", encoding="utf-8")
            temporary.replace(self.translated_path)
        except (ValueError, OSError) as error:
            messagebox.showerror("Chưa lưu bản dịch", str(error), parent=self)
            return
        self.done.set()
        self.destroy()

    def cancel(self):
        self.cancel_event.set()
        self.done.set()
        self.destroy()

    def poll_cancel(self):
        if self.cancel_event.is_set():
            self.done.set()
            self.destroy()
        else:
            self.after(200, self.poll_cancel)


def wait_for_translation_review(parent, directory, translated_path, cancel_event):
    done = threading.Event()
    errors = []

    def open_dialog():
        if cancel_event.is_set():
            done.set()
            return
        try:
            SubtitleReviewDialog(parent, directory / "original_subtitles.srt",
                                 translated_path, cancel_event, done)
        except Exception as error:
            errors.append(error)
            done.set()

    parent.after(0, open_dialog)
    while not done.wait(0.1):
        check_cancelled(cancel_event)
    check_cancelled(cancel_event)
    if errors:
        raise errors[0]
