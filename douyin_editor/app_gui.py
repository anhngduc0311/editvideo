"""
app_gui.py - Modern GUI for Douyin Video AI Automation Tool (CustomTkinter)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser
import customtkinter as ctk
import copy
from typing import Callable, Dict, List, Optional, Tuple

from config import BlurRegion, CookieConfig, PipelineConfig, SubtitleStyle, SUBTITLE_PRESETS, TTSConfig, VOICE_PRESETS, TRANSLATION_TOPIC_PRESETS
from pipeline import DouyinAutoPipeline
from roi_selector import VisualROISelectorDialog

# Thiết lập giao diện CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

CONFIG_FILE = Path.home() / ".douyin_editor_config.json"


class DouyinEditorApp(ctk.CTk):
    """
    Giao diện đồ họa hiện đại (Modern GUI) cho công cụ tự động hóa Edit Video Douyin bằng AI.
    Hỗ trợ tính năng tự chọn vùng làm mờ phụ đề trực quan (Visual ROI Drag & Drop Cropper).
    """

    def __init__(self):
        super().__init__()

        self.title("🎬 Douyin Video AI Auto Editor - Tự Động Hóa Re-up & Dịch Video AI 8 Bước")
        self.geometry("1180, 880")
        self.minsize(1020, 750)

        self.pipeline_thread: threading.Thread = None
        self.is_running = False
        self.last_output_video: Path = None

        self.saved_api_key = ""
        self.saved_cookie_str = ""
        self.saved_cookie_file = ""
        self.saved_browser_name = "Edge"
        self._load_saved_settings()

        # Dữ liệu phụ đề hiện tại phục vụ hiển thị & kiểm tra trên GUI
        self.current_subtitles_data: List[Dict[str, Any]] = []
        self.current_subtitles_stats: Dict[str, Any] = {}
        self.current_session_work_dir: Optional[Path] = None
        self.current_orig_srt_path: Optional[Path] = None
        self.current_synced_srt_path: Optional[Path] = None
        self.sub_entry_widgets: Dict[int, ctk.CTkEntry] = {}
        self.sub_resume_event: Optional[threading.Event] = None

        # Cấu hình Mẫu Phụ Đề CapCut hiện tại (Mặc định: Chữ trắng hộp đen Georgia)
        self.selected_sub_preset_id = getattr(self, "saved_sub_preset", "badge_white_on_black")
        self.sub_preset_buttons: Dict[str, ctk.CTkButton] = {}
        self.current_subtitle_style = copy.copy(SUBTITLE_PRESETS.get(self.selected_sub_preset_id, SUBTITLE_PRESETS["badge_white_on_black"])["style"])

        # Vùng làm mờ hiện tại
        self.current_blur_region = BlurRegion(
            y_ratio=0.72,
            height_ratio=0.18,
            blur_power=15,
            enabled=True
        )

        self._build_ui()

    def _load_saved_settings(self):
        """Đọc cài đặt đã lưu (API Key, Cookie, v.v.)"""
        self.saved_llm_provider = "deepseek"
        self.saved_deepseek_key = os.getenv("DEEPSEEK_API_KEY", "sk-7731fa779b8a46fda7e9e48c46bce715")
        self.saved_deepseek_model = "deepseek-v4-flash"
        self.saved_chatgpt_cookie = os.getenv("CHATGPT_COOKIE", "")
        self.saved_chatgpt_model = "auto"
        self.saved_font_size = "26"
        self.saved_margin_v = "45"
        self.saved_alignment = "2"
        self.saved_sub_preset = "badge_white_on_black"
        self.saved_export_res = "🔥 1080p Full HD (Chuẩn YouTube)"
        self.saved_smart_blur = True
        self.saved_auto_switch_sub = True
        self.saved_review_sub = False
        self.saved_topic_preset = "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)"
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.saved_llm_provider = data.get("llm_provider", "deepseek")
                self.saved_deepseek_key = data.get("deepseek_api_key", self.saved_deepseek_key)
                self.saved_deepseek_model = data.get("deepseek_model_name", "deepseek-v4-flash")
                self.saved_chatgpt_cookie = data.get("chatgpt_cookie", self.saved_chatgpt_cookie)
                self.saved_chatgpt_model = data.get("chatgpt_model_name", "auto")
                self.saved_cookie_str = data.get("douyin_cookie_str", "")
                self.saved_cookie_file = data.get("douyin_cookie_file", "")
                self.saved_browser_name = data.get("douyin_browser_name", "Edge")
                self.saved_font_size = data.get("subtitle_font_size", "26")
                self.saved_margin_v = data.get("subtitle_margin_v", "45")
                self.saved_alignment = data.get("subtitle_alignment", "2")
                self.saved_sub_preset = data.get("subtitle_preset_id", "badge_white_on_black")
                self.saved_export_res = data.get("export_resolution", "🔥 1080p Full HD (Chuẩn YouTube)")
                self.saved_smart_blur = data.get("smart_blur", True)
                self.saved_auto_switch_sub = data.get("auto_switch_sub", True)
                self.saved_review_sub = data.get("review_sub", False)
                self.saved_topic_preset = data.get("topic_preset", "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)")
            except Exception:
                pass

    def _save_settings(self):
        """Lưu cài đặt vào file JSON trong thư mục User"""
        try:
            self.saved_deepseek_key = self.key_entry.get().strip() if hasattr(self, "key_entry") else self.saved_deepseek_key
            self.saved_deepseek_model = self.cmb_ai_model.get().strip() if hasattr(self, "cmb_ai_model") else self.saved_deepseek_model
            self.saved_chatgpt_cookie = self.chatgpt_cookie_textbox.get("1.0", "end").strip() if hasattr(self, "chatgpt_cookie_textbox") else self.saved_chatgpt_cookie
            self.saved_chatgpt_model = self.cmb_chatgpt_model.get().strip() if hasattr(self, "cmb_chatgpt_model") else self.saved_chatgpt_model

            current_provider = "chatgpt_cookie" if hasattr(self, "ai_tabview") and "ChatGPT" in self.ai_tabview.get() else "deepseek"

            data = {
                "llm_provider": current_provider,
                "deepseek_api_key": self.saved_deepseek_key,
                "deepseek_model_name": self.saved_deepseek_model,
                "chatgpt_cookie": self.saved_chatgpt_cookie,
                "chatgpt_model_name": self.saved_chatgpt_model,
                "douyin_cookie_str": self.cookie_textbox.get("1.0", "end").strip() if hasattr(self, "cookie_textbox") else "",
                "douyin_cookie_file": getattr(self, "selected_cookie_file_path", ""),
                "douyin_browser_name": self.cmb_browser.get() if hasattr(self, "cmb_browser") else "Edge",
                "subtitle_font_size": self.cmb_font_size.get() if hasattr(self, "cmb_font_size") else "18",
                "subtitle_margin_v": str(int(self.slider_margin_v.get())) if hasattr(self, "slider_margin_v") else "45",
                "subtitle_alignment": str(self._get_alignment_code()) if hasattr(self, "seg_alignment") else "2",
                "subtitle_preset_id": getattr(self, "selected_sub_preset_id", "badge_white_on_black"),
                "export_resolution": self.cmb_export_res.get() if hasattr(self, "cmb_export_res") else "🔥 1080p Full HD (Chuẩn YouTube)",
                "smart_blur": bool(self.chk_smart_blur.get()) if hasattr(self, "chk_smart_blur") else True,
                "auto_switch_sub": bool(self.chk_auto_switch_sub.get()) if hasattr(self, "chk_auto_switch_sub") else True,
                "review_sub": bool(self.chk_review_sub.get()) if hasattr(self, "chk_review_sub") else False,
                "topic_preset": self.cmb_topic.get() if hasattr(self, "cmb_topic") else "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)",
            }
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=5)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(1, weight=1)

        # -------------------------------------------------------------
        # HEADER
        # -------------------------------------------------------------
        header_frame = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=("#1f2937", "#111827"))
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=(0, 8))
        header_frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="✨ DOUYIN VIDEO AI AUTO-EDITOR PRO (8 BƯỚC TỰ ĐỘNG)",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=("#60a5fa", "#38bdf8")
        )
        title_label.grid(row=0, column=0, padx=20, pady=12, sticky="w")

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="⚡ Local Multi-Engine STT • DeepSeek / ChatGPT AI • UVR MDX-Net • CapCut AI TTS (Siêu Tốc)",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        subtitle_label.grid(row=0, column=1, padx=20, pady=12, sticky="e")

        # -------------------------------------------------------------
        # CỘT TRÁI: CẤU HÌNH & THIẾT LẬP
        # -------------------------------------------------------------
        left_scroll = ctk.CTkScrollableFrame(self, corner_radius=10)
        left_scroll.grid(row=1, column=0, sticky="nsew", padx=(15, 8), pady=5)
        left_scroll.grid_columnconfigure(0, weight=1)

        # 1. Card Nhập link Douyin
        url_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        url_card.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkLabel(url_card, text="🔗 Link Video Douyin / Chuỗi Chia Sẻ:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        
        self.url_textbox = ctk.CTkTextbox(url_card, height=65, font=ctk.CTkFont(size=12))
        self.url_textbox.pack(fill="x", padx=12, pady=4)

        btn_url_row = ctk.CTkFrame(url_card, fg_color="transparent")
        btn_url_row.pack(fill="x", padx=12, pady=(4, 10))

        btn_paste = ctk.CTkButton(
            btn_url_row, text="📋 Dán từ Clipboard", width=140, height=28,
            command=self._paste_clipboard, fg_color="#2563eb", hover_color="#1d4ed8"
        )
        btn_paste.pack(side="left", padx=(0, 8))

        btn_clear = ctk.CTkButton(
            btn_url_row, text="🗑 Xóa", width=80, height=28,
            command=lambda: self.url_textbox.delete("1.0", "end"), fg_color="#4b5563", hover_color="#374151"
        )
        btn_clear.pack(side="left")

        # 2. Card Cookie Douyin
        cookie_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        cookie_card.pack(fill="x", padx=5, pady=5)

        cookie_header_row = ctk.CTkFrame(cookie_card, fg_color="transparent")
        cookie_header_row.pack(fill="x", padx=12, pady=(10, 4))
        
        ctk.CTkLabel(cookie_header_row, text="🍪 Cấu Hình Cookie Douyin (Tránh chặn tải):", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        
        btn_help_cookie = ctk.CTkButton(
            cookie_header_row, text="❓ Hướng dẫn", width=85, height=24,
            command=self._show_cookie_help, fg_color="#4b5563", hover_color="#374151"
        )
        btn_help_cookie.pack(side="right")

        self.cookie_tabview = ctk.CTkTabview(cookie_card, height=125)
        self.cookie_tabview.pack(fill="x", padx=12, pady=(0, 8))
        
        tab_str = self.cookie_tabview.add("Dán Cookie Text")
        tab_browser = self.cookie_tabview.add("Đọc từ Trình duyệt")
        tab_file = self.cookie_tabview.add("File cookies.txt")

        self.cookie_textbox = ctk.CTkTextbox(tab_str, height=50, font=ctk.CTkFont(family="Consolas", size=11))
        self.cookie_textbox.pack(fill="x", pady=(2, 4))
        if self.saved_cookie_str:
            self.cookie_textbox.insert("1.0", self.saved_cookie_str)
        else:
            self.cookie_textbox.insert("1.0", "passport_csrf_token=...; ttwid=... (Dán cookie từ F12 vào đây)")

        btn_paste_cookie = ctk.CTkButton(
            tab_str, text="📋 Dán Cookie từ Clipboard", height=24,
            command=self._paste_cookie_clipboard, fg_color="#059669", hover_color="#047857"
        )
        btn_paste_cookie.pack(anchor="w")

        browser_row = ctk.CTkFrame(tab_browser, fg_color="transparent")
        browser_row.pack(fill="x", pady=8)
        self.cmb_browser = ctk.CTkComboBox(browser_row, values=["Edge", "Chrome", "Brave", "Firefox", "Vivaldi"], width=180)
        self.cmb_browser.set(self.saved_browser_name)
        self.cmb_browser.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(browser_row, text="(Tự động đọc session trình duyệt)", text_color="gray70", font=ctk.CTkFont(size=11)).pack(side="left")

        file_row = ctk.CTkFrame(tab_file, fg_color="transparent")
        file_row.pack(fill="x", pady=8)
        file_row.grid_columnconfigure(0, weight=1)

        self.selected_cookie_file_path = self.saved_cookie_file
        self.lbl_cookie_file = ctk.CTkLabel(
            file_row,
            text=f"File: {Path(self.saved_cookie_file).name if self.saved_cookie_file else 'Chưa chọn file'}",
            anchor="w",
            text_color="#38bdf8" if self.saved_cookie_file else "gray70"
        )
        self.lbl_cookie_file.grid(row=0, column=0, sticky="ew")

        btn_browse_cookie = ctk.CTkButton(
            file_row, text="📂 Chọn file...", width=100, height=28,
            command=self._browse_cookie_file, fg_color="#2563eb"
        )
        btn_browse_cookie.grid(row=0, column=1, padx=(8, 0))

        # 3. Card AI Translation Provider (DeepSeek API & ChatGPT Web Cookie)
        key_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        key_card.pack(fill="x", padx=5, pady=5)

        provider_header_row = ctk.CTkFrame(key_card, fg_color="transparent")
        provider_header_row.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(provider_header_row, text="🤖 AI Dịch Thuật Phụ Đề (DeepSeek / ChatGPT Cookie):", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        self.ai_tabview = ctk.CTkTabview(key_card, height=160)
        self.ai_tabview.pack(fill="x", padx=12, pady=(0, 4))

        tab_deepseek = self.ai_tabview.add("🔹 DeepSeek API")
        tab_chatgpt = self.ai_tabview.add("🟢 ChatGPT Web (Cookie)")

        # ----- TAB 1: DEEPSEEK API -----
        key_row = ctk.CTkFrame(tab_deepseek, fg_color="transparent")
        key_row.pack(fill="x", pady=(2, 6))
        key_row.grid_columnconfigure(0, weight=1)

        self.key_entry = ctk.CTkEntry(key_row, show="•", font=ctk.CTkFont(size=12))
        self.key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        initial_key = getattr(self, "saved_deepseek_key", "sk-7731fa779b8a46fda7e9e48c46bce715")
        if initial_key:
            self.key_entry.insert(0, initial_key)

        self.btn_toggle_key = ctk.CTkButton(
            key_row, text="👁", width=36, height=28,
            command=self._toggle_key_visibility, fg_color="#374151"
        )
        self.btn_toggle_key.grid(row=0, column=1, padx=(0, 6))

        self.btn_get_key = ctk.CTkButton(
            key_row, text="Lấy Key", width=65, height=28,
            command=self._open_get_key_url,
            fg_color="#059669", hover_color="#047857"
        )
        self.btn_get_key.grid(row=0, column=2)

        model_row = ctk.CTkFrame(tab_deepseek, fg_color="transparent")
        model_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(model_row, text="Model:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))

        deepseek_models = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp", "deepseek-chat"]
        initial_model_val = getattr(self, "saved_deepseek_model", "deepseek-v4-flash")
        self.cmb_ai_model = ctk.CTkComboBox(model_row, values=deepseek_models, width=190)
        self.cmb_ai_model.set(initial_model_val)
        self.cmb_ai_model.pack(side="left", padx=(0, 8))

        self.btn_check_key = ctk.CTkButton(
            model_row, text="⚡ Test API", width=110, height=28,
            command=self._check_api_key_clicked,
            fg_color="#0284c7", hover_color="#0369a1"
        )
        self.btn_check_key.pack(side="left")

        self.lbl_api_status = ctk.CTkLabel(
            tab_deepseek,
            text="DeepSeek AI: Tốc độ siêu tốc, dịch chuẩn tự nhiên, chuẩn timeline SRT.",
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8",
            wraplength=470,
            justify="left"
        )
        self.lbl_api_status.pack(anchor="w", pady=(0, 2))

        # ----- TAB 2: CHATGPT WEB COOKIE -----
        gpt_header = ctk.CTkFrame(tab_chatgpt, fg_color="transparent")
        gpt_header.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(gpt_header, text="🍪 Dán Cookie hoặc __Secure-next-auth.session-token:", font=ctk.CTkFont(size=11)).pack(side="left")

        btn_gpt_help = ctk.CTkButton(
            gpt_header, text="❓ Hướng dẫn", width=80, height=22, font=ctk.CTkFont(size=11),
            command=self._show_chatgpt_cookie_help, fg_color="#4b5563", hover_color="#374151"
        )
        btn_gpt_help.pack(side="right")

        self.chatgpt_cookie_textbox = ctk.CTkTextbox(tab_chatgpt, height=46, font=ctk.CTkFont(family="Consolas", size=10))
        self.chatgpt_cookie_textbox.pack(fill="x", pady=(2, 4))
        if getattr(self, "saved_chatgpt_cookie", ""):
            self.chatgpt_cookie_textbox.insert("1.0", self.saved_chatgpt_cookie)
        else:
            self.chatgpt_cookie_textbox.insert("1.0", "__Secure-next-auth.session-token=eyJ... (hoặc dán toàn bộ cookie F12)")

        gpt_actions_row = ctk.CTkFrame(tab_chatgpt, fg_color="transparent")
        gpt_actions_row.pack(fill="x", pady=(2, 2))

        btn_paste_gpt = ctk.CTkButton(
            gpt_actions_row, text="📋 Dán Clipboard", width=120, height=26, font=ctk.CTkFont(size=11),
            command=self._paste_chatgpt_cookie_clipboard, fg_color="#059669", hover_color="#047857"
        )
        btn_paste_gpt.pack(side="left", padx=(0, 6))

        btn_clear_gpt = ctk.CTkButton(
            gpt_actions_row, text="🗑 Xóa", width=55, height=26, font=ctk.CTkFont(size=11),
            command=lambda: self.chatgpt_cookie_textbox.delete("1.0", "end"), fg_color="#4b5563", hover_color="#374151"
        )
        btn_clear_gpt.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(gpt_actions_row, text="Model:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(4, 4))
        self.cmb_chatgpt_model = ctk.CTkComboBox(
            gpt_actions_row,
            values=["Tự Động (Auto GPT-4o)", "GPT-4o Mini", "GPT-4o"],
            width=150, height=26, font=ctk.CTkFont(size=11)
        )
        self.cmb_chatgpt_model.set(getattr(self, "saved_chatgpt_model", "Tự Động (Auto GPT-4o)"))
        self.cmb_chatgpt_model.pack(side="left", padx=(0, 6))

        self.btn_check_chatgpt = ctk.CTkButton(
            gpt_actions_row, text="🔍 Test Cookie", width=95, height=26, font=ctk.CTkFont(size=11),
            command=self._check_chatgpt_cookie_clicked,
            fg_color="#0284c7", hover_color="#0369a1"
        )
        self.btn_check_chatgpt.pack(side="left")

        self.lbl_chatgpt_status = ctk.CTkLabel(
            tab_chatgpt,
            text="🟢 ChatGPT Web: Miễn phí 100%, dịch cực hay bằng GPT-4o qua tài khoản web của bạn.",
            font=ctk.CTkFont(size=11),
            text_color="#10b981",
            wraplength=470,
            justify="left"
        )
        self.lbl_chatgpt_status.pack(anchor="w", pady=(2, 2))

        # Chọn Tab mặc định theo cấu hình đã lưu
        if getattr(self, "saved_llm_provider", "deepseek") == "chatgpt_cookie":
            self.ai_tabview.set("🟢 ChatGPT Web (Cookie)")
        else:
            self.ai_tabview.set("🔹 DeepSeek API")

        # Translation Topic / Context Row
        topic_row = ctk.CTkFrame(key_card, fg_color="transparent")
        topic_row.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(topic_row, text="🎯 Chủ đề / Ngữ cảnh dịch:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))

        self.cmb_topic = ctk.CTkComboBox(
            topic_row,
            values=[
                "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)",
                "🎮 Minecraft cho Trẻ Em (Vui nhộn, chuẩn gamer nhí)",
                "🕹️ Game & Esports Tổng Hợp (Kịch tính, hài hước)",
                "✨ Hài Hước / Giải Trí Đời Sống (Tự nhiên, dí dỏm)",
                "🌐 Đa Dụng / Tiêu Chuẩn (Chuẩn mực, súc tích)"
            ],
            width=360
        )
        self.cmb_topic.set(getattr(self, "saved_topic_preset", "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)"))
        self.cmb_topic.pack(side="left")

        # 4. Card Tùy chọn Xử lý Video (Speed & Blur ROI)
        video_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        video_card.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(video_card, text="⚙️ Cài Đặt Tốc Độ & Vùng Làm Mờ Phụ Đề Gốc:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 6))

        # Speed Slider (Làm chậm cho TTS)
        speed_row = ctk.CTkFrame(video_card, fg_color="transparent")
        speed_row.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(speed_row, text="1. Tốc độ dịch & lồng tiếng (Bước 2):").pack(side="left")
        self.lbl_speed_val = ctk.CTkLabel(speed_row, text="0.70x (Chậm để đọc kịp)", font=ctk.CTkFont(weight="bold"), text_color="#38bdf8")
        self.lbl_speed_val.pack(side="right")

        self.slider_speed = ctk.CTkSlider(
            video_card, from_=0.50, to=1.0, number_of_steps=10,
            command=self._on_speed_changed
        )
        self.slider_speed.set(0.70)
        self.slider_speed.pack(fill="x", padx=12, pady=(0, 4))

        # Final Export Speed Slider (Tăng tốc ở Bước 8)
        final_speed_row = ctk.CTkFrame(video_card, fg_color="transparent")
        final_speed_row.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(final_speed_row, text="2. Tốc độ xuất video thành phẩm (Bước 8):").pack(side="left")
        self.lbl_final_speed_val = ctk.CTkLabel(final_speed_row, text="1.20x (Nhanh & cuốn hút)", font=ctk.CTkFont(weight="bold"), text_color="#10b981")
        self.lbl_final_speed_val.pack(side="right")

        self.slider_final_speed = ctk.CTkSlider(
            video_card, from_=1.0, to=1.60, number_of_steps=12,
            command=lambda v: self.lbl_final_speed_val.configure(text=f"{v:.2f}x (Nhanh & cuốn hút)" if v > 1.05 else f"{v:.2f}x (Chuẩn)")
        )
        self.slider_final_speed.set(1.20)
        self.slider_final_speed.pack(fill="x", padx=12, pady=(0, 6))

        # 3. Độ phân giải xuất video (Chuẩn 1080p Full HD tối ưu YouTube)
        res_row = ctk.CTkFrame(video_card, fg_color="transparent")
        res_row.pack(fill="x", padx=12, pady=(4, 6))
        ctk.CTkLabel(res_row, text="3. Độ phân giải xuất (Chuẩn YouTube):").pack(side="left")
        self.cmb_export_res = ctk.CTkComboBox(
            res_row,
            values=[
                "🔥 1080p Full HD (Chuẩn YouTube)",
                "🎬 Gốc (Original)",
                "⚡ 720p HD (Render nhanh)",
                "💎 2K QHD (1440p)"
            ],
            width=230,
            state="readonly"
        )
        saved_res_text = getattr(self, "saved_export_res", "🔥 1080p Full HD (Chuẩn YouTube)")
        if not any(saved_res_text in v for v in self.cmb_export_res._values):
            saved_res_text = "🔥 1080p Full HD (Chuẩn YouTube)"
        self.cmb_export_res.set(saved_res_text)
        self.cmb_export_res.pack(side="right")

        # Checkbox Blur
        self.chk_blur = ctk.CTkCheckBox(video_card, text="Làm mờ phụ đề tiếng Trung gốc (Boxblur)", font=ctk.CTkFont(weight="bold"))
        self.chk_blur.select()
        self.chk_blur.pack(anchor="w", padx=12, pady=(4, 2))

        # Checkbox Làm mờ thông minh (Chỉ mờ khi có phụ đề)
        self.chk_smart_blur = ctk.CTkCheckBox(
            video_card,
            text="✨ Làm mờ thông minh (Tự ẩn vùng mờ khi không có phụ đề)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        if getattr(self, "saved_smart_blur", True):
            self.chk_smart_blur.select()
        else:
            self.chk_smart_blur.deselect()
        self.chk_smart_blur.pack(anchor="w", padx=12, pady=(2, 4))

        # NÚT KHOANH VÙNG TRỰC TIẾP
        btn_roi_row = ctk.CTkFrame(video_card, fg_color="transparent")
        btn_roi_row.pack(fill="x", padx=12, pady=(4, 6))

        self.btn_open_roi_selector = ctk.CTkButton(
            btn_roi_row,
            text="🎯 KHOANH VÙNG PHỤ ĐỀ TRỰC QUAN (KÉO CHUỘT)",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            command=self._open_visual_roi_selector
        )
        self.btn_open_roi_selector.pack(fill="x")

        # Checkbox Tự động dừng lại ở Bước 2 để chọn vùng mờ trên video thực tế
        self.chk_interactive_roi = ctk.CTkCheckBox(
            video_card,
            text="⏸ Dừng lại sau khi tải để tôi khoanh vùng mờ trên video thực tế",
            font=ctk.CTkFont(size=12)
        )
        self.chk_interactive_roi.select()  # Mặc định bật để người dùng tự chọn
        self.chk_interactive_roi.pack(anchor="w", padx=12, pady=(2, 4))

        # Checkbox Tự động chuyển Tab Phụ Đề để kiểm tra
        self.chk_auto_switch_sub = ctk.CTkCheckBox(
            video_card,
            text="💬 Tự động mở Tab Phụ Đề sau khi nhận diện để kiểm tra câu thoại",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        if getattr(self, "saved_auto_switch_sub", True):
            self.chk_auto_switch_sub.select()
        else:
            self.chk_auto_switch_sub.deselect()
        self.chk_auto_switch_sub.pack(anchor="w", padx=12, pady=(2, 4))

        # Checkbox Dừng lại để duyệt phụ đề trước khi render
        self.chk_review_sub = ctk.CTkCheckBox(
            video_card,
            text="⏸ Dừng lại sau khi dịch & đọc TTS để tôi duyệt/sửa phụ đề trước khi xuất video",
            font=ctk.CTkFont(size=12)
        )
        if getattr(self, "saved_review_sub", False):
            self.chk_review_sub.select()
        else:
            self.chk_review_sub.deselect()
        self.chk_review_sub.pack(anchor="w", padx=12, pady=(2, 6))

        # Sliders chỉnh tọa độ thủ công
        blur_row = ctk.CTkFrame(video_card, fg_color="transparent")
        blur_row.pack(fill="x", padx=12, pady=(2, 10))
        blur_row.grid_columnconfigure((0, 1), weight=1)

        self.lbl_blur_y_title = ctk.CTkLabel(blur_row, text="Vị trí mờ (Y): 72%")
        self.lbl_blur_y_title.grid(row=0, column=0, sticky="w")
        self.slider_blur_y = ctk.CTkSlider(
            blur_row, from_=0.0, to=0.95, number_of_steps=95,
            command=self._on_blur_slider_changed
        )
        self.slider_blur_y.set(0.72)
        self.slider_blur_y.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        self.lbl_blur_h_title = ctk.CTkLabel(blur_row, text="Độ cao mờ (H): 18%")
        self.lbl_blur_h_title.grid(row=0, column=1, sticky="w")
        self.slider_blur_h = ctk.CTkSlider(
            blur_row, from_=0.05, to=0.40, number_of_steps=35,
            command=self._on_blur_slider_changed
        )
        self.slider_blur_h.set(0.18)
        self.slider_blur_h.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        # 5. Card TTS & BGM
        audio_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        audio_card.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(audio_card, text="🎙️ Giọng Đọc AI (TTS) & Nhạc Nền (BGM):", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 6))

        tts_row = ctk.CTkFrame(audio_card, fg_color="transparent")
        tts_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(tts_row, text="Giọng đọc:").pack(side="left", padx=(0, 4))

        voice_options = [
            "🔥 Cô Gái Hoạt Ngôn (CapCut Chính Chủ)",
            "🔥 Thanh Niên Tự Tin (CapCut Chính Chủ)",
            "🌸 Nhỏ Ngọt Ngào (CapCut Nữ Dễ Thương)",
            "✨ Mai (CapCut Nữ Truyền Cảm)",
            "🎙️ Giọng Nữ Phổ Thông (CapCut Chuẩn)",
            "⚡ Kenny Đại Đế (CapCut Giọng Ngầu)"
        ]

        self.cmb_voice = ctk.CTkComboBox(
            tts_row,
            values=voice_options,
            width=280
        )
        self.cmb_voice.set("🔥 Cô Gái Hoạt Ngôn (CapCut Chính Chủ)")
        self.cmb_voice.pack(side="left", padx=(0, 8))

        self.btn_preview_voice = ctk.CTkButton(
            tts_row,
            text="▶ Nghe thử",
            width=80,
            height=28,
            command=self._preview_voice_clicked,
            fg_color="#059669",
            hover_color="#047857"
        )
        self.btn_preview_voice.pack(side="left")

        self.chk_bgm = ctk.CTkCheckBox(
            audio_card,
            text="Tách giọng AI & Giữ nguyên nhạc nền BGM gốc (UVR MDX-Net)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.chk_bgm.select()  # Mặc định BẬT để tách giọng và giữ nhạc nền gốc
        self.chk_bgm.pack(anchor="w", padx=12, pady=(8, 2))

        # Tùy chọn tốc độ tách AI
        sep_speed_row = ctk.CTkFrame(audio_card, fg_color="transparent")
        sep_speed_row.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(sep_speed_row, text="Tốc độ tách AI:").pack(side="left", padx=(0, 6))

        self.cmb_sep_speed = ctk.CTkComboBox(
            sep_speed_row,
            values=[
                "⚡ Siêu Tốc (Turbo 0% Overlap)",
                "🚀 Rất Nhanh (Fast 25% Overlap)",
                "⚖ Cân Bằng (Balanced 50% Overlap)",
                "💎 Chất Lượng Cao (HQ 75% Overlap)"
            ],
            width=260
        )
        self.cmb_sep_speed.set("⚡ Siêu Tốc (Turbo 0% Overlap)")
        self.cmb_sep_speed.pack(side="left")

        bgm_vol_row = ctk.CTkFrame(audio_card, fg_color="transparent")
        bgm_vol_row.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(bgm_vol_row, text="Âm lượng nhạc nền BGM gốc:").pack(side="left")
        self.lbl_bgm_vol = ctk.CTkLabel(bgm_vol_row, text="100% (Giữ nguyên gốc)", font=ctk.CTkFont(weight="bold"), text_color="#10b981")
        self.lbl_bgm_vol.pack(side="right")

        self.slider_bgm_vol = ctk.CTkSlider(
            audio_card, from_=0.0, to=1.50, number_of_steps=15,
            command=lambda v: self.lbl_bgm_vol.configure(
                text=f"{int(v*100)}% (Giữ nguyên gốc)" if abs(v - 1.0) < 0.05 else f"{int(v*100)}%"
            )
        )
        self.slider_bgm_vol.set(1.00)  # Mặc định 100% giữ nguyên âm lượng gốc
        self.slider_bgm_vol.pack(fill="x", padx=12, pady=(0, 10))

        # 6. Card Phụ đề tiếng Việt (CapCut Subtitle Style Grid)
        sub_card = ctk.CTkFrame(left_scroll, corner_radius=8)
        sub_card.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(sub_card, text="✍️ Mẫu Chữ Phụ Đề (CapCut Text Presets):", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))

        # Grid mẫu chữ kiểu CapCut (6 cột)
        grid_frame = ctk.CTkFrame(sub_card, fg_color="#18181b", corner_radius=8)
        grid_frame.pack(fill="x", padx=12, pady=(4, 6))

        for col in range(6):
            grid_frame.grid_columnconfigure(col, weight=1)

        self.sub_preset_buttons = {}
        for idx, (p_id, p_val) in enumerate(SUBTITLE_PRESETS.items()):
            row = idx // 6
            col = idx % 6
            is_selected = (p_id == self.selected_sub_preset_id)
            btn = ctk.CTkButton(
                grid_frame,
                text=p_val.get("preview_text", "Aa"),
                font=ctk.CTkFont(size=15, weight="bold"),
                width=52,
                height=42,
                corner_radius=8,
                fg_color=p_val["bg_color"],
                text_color=p_val["fg_color"],
                border_color="#06b6d4" if is_selected else (p_val["border_color"] if p_val["border_color"] != "transparent" else "#3f3f46"),
                border_width=3 if is_selected else 2,
                hover_color=p_val["bg_color"],
                command=lambda pid=p_id: self._select_subtitle_preset(pid)
            )
            btn.grid(row=row, column=col, padx=3, pady=3, sticky="ew")
            self.sub_preset_buttons[p_id] = btn

        self.lbl_selected_sub_preset = ctk.CTkLabel(
            sub_card,
            text=f"Kiểu đang chọn: 🔥 {SUBTITLE_PRESETS[self.selected_sub_preset_id]['name']}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_selected_sub_preset.pack(anchor="w", padx=12, pady=(2, 6))

        # Font chữ & Cỡ chữ
        sub_row = ctk.CTkFrame(sub_card, fg_color="transparent")
        sub_row.pack(fill="x", padx=12, pady=(2, 4))
        sub_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(sub_row, text="Font chữ:").grid(row=0, column=0, sticky="w")
        self.cmb_font = ctk.CTkComboBox(
            sub_row,
            values=["Georgia", "Times New Roman", "Cambria", "Arial", "Montserrat", "Roboto", "Tahoma", "Verdana", "Segoe UI"],
            command=lambda _: self._update_sub_preview_banner()
        )
        self.cmb_font.set(getattr(self.current_subtitle_style, "font_name", "Georgia"))
        self.cmb_font.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkLabel(sub_row, text="Cỡ chữ (Size):").grid(row=0, column=1, sticky="w")
        self.cmb_font_size = ctk.CTkComboBox(
            sub_row,
            values=["16", "18", "20", "22", "24", "26", "28", "32", "36", "40", "44", "48", "54", "60"],
            command=lambda _: self._update_sub_preview_banner()
        )
        self.cmb_font_size.set(getattr(self, "saved_font_size", "26"))
        self.cmb_font_size.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        # Vùng Cấu hình Vị trí Hiển thị Phụ đề (Alignment & Margin V)
        pos_card = ctk.CTkFrame(sub_card, fg_color="#18181b", corner_radius=6, border_width=1, border_color="#27272a")
        pos_card.pack(fill="x", padx=12, pady=(4, 6))

        # 1. Căn lề dọc / vị trí tổng quan
        align_row = ctk.CTkFrame(pos_card, fg_color="transparent")
        align_row.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(align_row, text="📐 Căn lề:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))

        self.seg_alignment = ctk.CTkSegmentedButton(
            align_row,
            values=["⬇️ Dưới cùng (Mặc định)", "⏸️ Giữa màn hình", "⬆️ Trên cùng"],
            command=self._on_alignment_changed,
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8"
        )
        self.seg_alignment.pack(side="left", fill="x", expand=True)
        if getattr(self, "saved_alignment", "2") == "5":
            self.seg_alignment.set("⏸️ Giữa màn hình")
        elif getattr(self, "saved_alignment", "2") == "8":
            self.seg_alignment.set("⬆️ Trên cùng")
        else:
            self.seg_alignment.set("⬇️ Dưới cùng (Mặc định)")

        # 2. Thanh kéo khoảng cách mép (Margin V)
        margin_header = ctk.CTkFrame(pos_card, fg_color="transparent")
        margin_header.pack(fill="x", padx=8, pady=(4, 0))
        self.lbl_margin_title = ctk.CTkLabel(margin_header, text="📏 Vị trí độ cao / Khoảng cách mép:", font=ctk.CTkFont(size=12))
        self.lbl_margin_title.pack(side="left")
        
        saved_m_v = int(getattr(self, "saved_margin_v", 45))
        self.lbl_margin_v = ctk.CTkLabel(margin_header, text=f"{saved_m_v}px", font=ctk.CTkFont(weight="bold"), text_color="#38bdf8")
        self.lbl_margin_v.pack(side="right")

        self.slider_margin_v = ctk.CTkSlider(
            pos_card, from_=10, to=600, number_of_steps=118,
            command=self._on_margin_v_changed
        )
        self.slider_margin_v.set(saved_m_v)
        self.slider_margin_v.pack(fill="x", padx=8, pady=(2, 4))

        # 3. Các mốc chọn nhanh vị trí (Quick Presets)
        quick_row = ctk.CTkFrame(pos_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=8, pady=(0, 6))
        quick_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        btn_q1 = ctk.CTkButton(quick_row, text="Sát đáy (35px)", height=24, font=ctk.CTkFont(size=11), fg_color="#27272a", hover_color="#3f3f46", command=lambda: self._set_quick_margin(35))
        btn_q1.grid(row=0, column=0, padx=2, sticky="ew")

        btn_q2 = ctk.CTkButton(quick_row, text="Chuẩn (70px)", height=24, font=ctk.CTkFont(size=11), fg_color="#27272a", hover_color="#3f3f46", command=lambda: self._set_quick_margin(70))
        btn_q2.grid(row=0, column=1, padx=2, sticky="ew")

        btn_q3 = ctk.CTkButton(quick_row, text="Giữa dưới (160px)", height=24, font=ctk.CTkFont(size=11), fg_color="#27272a", hover_color="#3f3f46", command=lambda: self._set_quick_margin(160))
        btn_q3.grid(row=0, column=2, padx=2, sticky="ew")

        btn_q4 = ctk.CTkButton(quick_row, text="Cao (300px)", height=24, font=ctk.CTkFont(size=11), fg_color="#27272a", hover_color="#3f3f46", command=lambda: self._set_quick_margin(300))
        btn_q4.grid(row=0, column=3, padx=2, sticky="ew")

        # Tùy chọn in đậm chữ
        opt_row = ctk.CTkFrame(sub_card, fg_color="transparent")
        opt_row.pack(fill="x", padx=12, pady=(2, 4))
        self.chk_bold_sub = ctk.CTkCheckBox(
            opt_row,
            text="In đậm chữ (Bold)",
            font=ctk.CTkFont(size=12),
            command=self._update_sub_preview_banner
        )
        self.chk_bold_sub.select()
        self.chk_bold_sub.pack(side="left")

        # Live Subtitle Preview Banner
        self.preview_sub_frame = ctk.CTkFrame(sub_card, corner_radius=6, border_width=1, border_color="#3f3f46", fg_color="#18181b")
        self.preview_sub_frame.pack(fill="x", padx=12, pady=(6, 12))

        self.lbl_preview_sub_text = ctk.CTkLabel(
            self.preview_sub_frame,
            text="[Phụ đề mẫu tiếng Việt chuẩn CapCut]",
            font=ctk.CTkFont(family="Arial", size=14, weight="bold"),
            text_color="#ffffff",
            pady=8
        )
        self.lbl_preview_sub_text.pack()

        # -------------------------------------------------------------
        # CỘT PHẢI: TIẾN TRÌNH 8 BƯỚC & KIỂM TRA PHỤ ĐỀ / LOGS
        # -------------------------------------------------------------
        right_frame = ctk.CTkFrame(self, corner_radius=10)
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 15), pady=5)
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(2, weight=1)

        steps_card = ctk.CTkFrame(right_frame, corner_radius=8)
        steps_card.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        steps_card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(steps_card, text="📊 Quy Trình Xử Lý 8 Bước Tự Động:", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4)
        )

        self.step_labels = []
        step_names = [
            "1. Tải Video Douyin (Multi-Engine)",
            "2. Tách Giọng AI & BGM 0.70x (MDX-Net)",
            "3. Local STT (Track Vocals Sạch)",
            "4. Dịch thuật AI (DeepSeek / ChatGPT)",
            "5. Đọc CapCut TTS & Đồng bộ Timeline",
            "6. Single-Pass Master Render 0.70x",
            "7. Đóng Phụ Đề & Mix BGM 100%",
            "8. Xuất Video MP4 Thành Phẩm"
        ]

        for i, name in enumerate(step_names):
            r = 1 + (i // 2)
            c = i % 2
            lbl = ctk.CTkLabel(
                steps_card,
                text=f"⚪ {name}",
                font=ctk.CTkFont(size=12),
                anchor="w",
                text_color="gray70"
            )
            lbl.grid(row=r, column=c, sticky="w", padx=12, pady=2)
            self.step_labels.append(lbl)

        prog_card = ctk.CTkFrame(right_frame, corner_radius=8)
        prog_card.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        prog_card.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            prog_card,
            text="Trạng thái: Sẵn sàng thực hiện",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_status.pack(anchor="w", padx=12, pady=(6, 2))

        self.progress_bar = ctk.CTkProgressBar(prog_card, height=12)
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=12, pady=(2, 6))

        # TABVIEW CHO PHỤ ĐỀ & NHẬT KÝ
        self.right_tabview = ctk.CTkTabview(right_frame, corner_radius=8)
        self.right_tabview.grid(row=2, column=0, sticky="nsew", padx=10, pady=(2, 6))

        tab_sub = self.right_tabview.add("💬 Kiểm Tra Phụ Đề & Tình Trạng")
        tab_log = self.right_tabview.add("📜 Nhật Ký Xử Lý (Console)")

        # ----- TAB PHỤ ĐỀ -----
        tab_sub.grid_columnconfigure(0, weight=1)
        tab_sub.grid_rowconfigure(3, weight=1)

        # 1. Dashboard Thống Kê & Tình Trạng
        sub_metrics_frame = ctk.CTkFrame(tab_sub, fg_color="#18181b", corner_radius=6, border_width=1, border_color="#27272a")
        sub_metrics_frame.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 4))
        sub_metrics_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.lbl_sub_stat_count = ctk.CTkLabel(
            sub_metrics_frame, text="🔢 Tổng: 0 câu",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8"
        )
        self.lbl_sub_stat_count.grid(row=0, column=0, padx=8, pady=4, sticky="w")

        self.lbl_sub_stat_time = ctk.CTkLabel(
            sub_metrics_frame, text="⏱ Thoại: 0.0s / 0.0s",
            font=ctk.CTkFont(size=12), text_color="gray80"
        )
        self.lbl_sub_stat_time.grid(row=0, column=1, padx=4, pady=4)

        self.lbl_sub_stat_badge = ctk.CTkLabel(
            sub_metrics_frame, text="🔴 CHƯA CÓ DỮ LIỆU",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#ef4444"
        )
        self.lbl_sub_stat_badge.grid(row=0, column=2, padx=8, pady=4, sticky="e")

        # 2. Alert Bar
        self.lbl_sub_alert = ctk.CTkLabel(
            tab_sub,
            text="ℹ️ Sau khi tải và nhận diện giọng nói, toàn bộ danh sách phụ đề Trung - Việt và tình trạng sẽ hiển thị tại đây.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            wraplength=480,
            justify="left"
        )
        self.lbl_sub_alert.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))

        # 3. Toolbar thao tác
        sub_toolbar = ctk.CTkFrame(tab_sub, fg_color="transparent")
        sub_toolbar.grid(row=2, column=0, sticky="ew", padx=2, pady=(0, 4))
        sub_toolbar.grid_columnconfigure(0, weight=1)

        self.sub_search_entry = ctk.CTkEntry(
            sub_toolbar,
            placeholder_text="🔍 Tìm kiếm câu thoại...",
            height=28,
            font=ctk.CTkFont(size=11)
        )
        self.sub_search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.sub_search_entry.bind("<KeyRelease>", lambda e: self._filter_subtitles_list())

        btn_open_orig = ctk.CTkButton(
            sub_toolbar, text="📂 SRT Gốc", width=75, height=28, font=ctk.CTkFont(size=11),
            command=self._open_orig_srt_file, fg_color="#374151", hover_color="#4b5563"
        )
        btn_open_orig.grid(row=0, column=1, padx=2)

        btn_open_synced = ctk.CTkButton(
            sub_toolbar, text="📂 SRT Việt", width=75, height=28, font=ctk.CTkFont(size=11),
            command=self._open_synced_srt_file, fg_color="#2563eb", hover_color="#1d4ed8"
        )
        btn_open_synced.grid(row=0, column=2, padx=2)

        btn_copy_all = ctk.CTkButton(
            sub_toolbar, text="📋 Copy", width=65, height=28, font=ctk.CTkFont(size=11),
            command=self._copy_all_subtitles, fg_color="#059669", hover_color="#047857"
        )
        btn_copy_all.grid(row=0, column=3, padx=2)

        self.btn_save_subs = ctk.CTkButton(
            sub_toolbar, text="💾 Lưu Sửa", width=75, height=28, font=ctk.CTkFont(size=11),
            command=self._save_edited_subtitles, fg_color="#d97706", hover_color="#b45309"
        )
        self.btn_save_subs.grid(row=0, column=4, padx=(2, 0))

        # 4. Scrollable Container danh sách phụ đề
        self.sub_cards_scroll = ctk.CTkScrollableFrame(tab_sub, corner_radius=6, fg_color="#09090b")
        self.sub_cards_scroll.grid(row=3, column=0, sticky="nsew", padx=2, pady=(0, 2))
        self.sub_cards_scroll.grid_columnconfigure(0, weight=1)

        # Banner dừng lại duyệt phụ đề (ẩn mặc định)
        self.sub_review_resume_frame = ctk.CTkFrame(tab_sub, fg_color="#1e1b4b", corner_radius=6, border_width=1, border_color="#6366f1")
        self.btn_resume_pipeline = ctk.CTkButton(
            self.sub_review_resume_frame,
            text="▶ ĐÃ KIỂM TRA XONG - TIẾP TỤC RENDER VIDEO NGAY",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            fg_color="#10b981",
            hover_color="#059669",
            command=self._resume_pipeline_after_review
        )
        self.btn_resume_pipeline.pack(fill="x", padx=8, pady=6)

        self._render_empty_sub_placeholder()

        # ----- TAB NHẬT KÝ (LOGS) -----
        tab_log.grid_columnconfigure(0, weight=1)
        tab_log.grid_rowconfigure(0, weight=1)
        self.log_textbox = ctk.CTkTextbox(tab_log, font=ctk.CTkFont(family="Consolas", size=11), activate_scrollbars=True)
        self.log_textbox.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        # -------------------------------------------------------------
        # FOOTER / CONTROL BAR
        # -------------------------------------------------------------
        footer_frame = ctk.CTkFrame(self, height=65, corner_radius=10)
        footer_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=15, pady=(5, 15))
        footer_frame.grid_columnconfigure(0, weight=3)
        footer_frame.grid_columnconfigure((1, 2), weight=1)

        self.btn_run = ctk.CTkButton(
            footer_frame,
            text="🚀 BẮT ĐẦU XỬ LÝ VIDEO TỰ ĐỘNG",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=44,
            fg_color="#10b981",
            hover_color="#059669",
            command=self._start_pipeline
        )
        self.btn_run.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=10)

        self.btn_open_folder = ctk.CTkButton(
            footer_frame,
            text="📁 Mở Thư Mục Kết Quả",
            height=44,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self._open_output_folder
        )
        self.btn_open_folder.grid(row=0, column=1, sticky="ew", padx=8, pady=10)

        self.btn_play_video = ctk.CTkButton(
            footer_frame,
            text="🎬 Xem Video Thành Phẩm",
            height=44,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            command=self._play_output_video,
            state="disabled"
        )
        self.btn_play_video.grid(row=0, column=2, sticky="ew", padx=(8, 12), pady=10)

        # Cập nhật banner xem trước phụ đề ban đầu
        self._update_sub_preview_banner()

    # -----------------------------------------------------------------
    # UI HANDLERS & LOGIC
    # -----------------------------------------------------------------
    def _paste_clipboard(self):
        try:
            clip = self.clipboard_get()
            self.url_textbox.delete("1.0", "end")
            self.url_textbox.insert("1.0", clip.strip())
        except Exception:
            pass

    def _paste_cookie_clipboard(self):
        try:
            clip = self.clipboard_get()
            self.cookie_textbox.delete("1.0", "end")
            self.cookie_textbox.insert("1.0", clip.strip())
        except Exception:
            pass

    def _browse_cookie_file(self):
        f = filedialog.askopenfilename(
            title="Chọn file cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if f:
            self.selected_cookie_file_path = f
            self.lbl_cookie_file.configure(text=f"File: {Path(f).name}", text_color="#38bdf8")

    def _show_cookie_help(self):
        msg = (
            "Cách lấy Cookie Douyin nhanh nhất:\n\n"
            "1. Mở trình duyệt (Chrome/Edge), truy cập trang https://www.douyin.com và đăng nhập (hoặc lướt xem video).\n"
            "2. Nhấn phím F12 -> Chuyển sang tab 'Network' (Mạng) hoặc 'Application' -> 'Cookies'.\n"
            "3. Copy giá trị chuỗi Cookie.\n"
            "4. Dán vào ô 'Dán Cookie Text' hoặc chọn tab 'Đọc từ Trình duyệt' (chọn Edge/Chrome).\n\n"
            "💡 Mẹo: Hệ thống đã tích hợp sẵn Direct API thông minh để tự động tải video không logo ngay cả khi không có cookie!"
        )
        messagebox.showinfo("Hướng dẫn lấy Cookie Douyin", msg)

    def _toggle_key_visibility(self):
        if self.key_entry.cget("show") == "•":
            self.key_entry.configure(show="")
            self.btn_toggle_key.configure(text="🔒")
        else:
            self.key_entry.configure(show="•")
            self.btn_toggle_key.configure(text="👁")

    def _preview_voice_clicked(self):
        """Phát trực tiếp file mẫu giọng hoặc gọi CapCut TTS API sinh audio preview để người dùng nghe thử"""
        chosen = self.cmb_voice.get()
        self.btn_preview_voice.configure(text="⏳ Đang tải...", state="disabled")

        def _work():
            try:
                import io, tempfile, winsound, pathlib
                from pydub import AudioSegment
                from tts_synchronizer import CapCutTTSEngine

                tts_dir = pathlib.Path(__file__).parent.parent / "tts"
                sample_file = None

                if "Hoạt Ngôn" in chosen or "hoat_ngon" in chosen:
                    if (tts_dir / "thanhnientutin.mp3").exists():
                        sample_file = tts_dir / "thanhnientutin.mp3"
                    elif (tts_dir / "cogaihoatngon.mp3").exists():
                        sample_file = tts_dir / "cogaihoatngon.mp3"
                elif "Tự Tin" in chosen or "tu_tin" in chosen:
                    if (tts_dir / "cogaihoatngon.mp3").exists():
                        sample_file = tts_dir / "cogaihoatngon.mp3"
                    elif (tts_dir / "thanhnientutin.mp3").exists():
                        sample_file = tts_dir / "thanhnientutin.mp3"

                tmp_wav = pathlib.Path(tempfile.gettempdir()) / "sample_preview.wav"

                if sample_file and sample_file.exists():
                    seg = AudioSegment.from_file(str(sample_file))
                    seg.export(str(tmp_wav), format="wav")
                    winsound.PlaySound(str(tmp_wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    self._append_log(f"Đang phát mẫu giọng CapCut: {sample_file.name} ({chosen})", "AUDIO")
                else:
                    # Gọi trực tiếp CapCut TTS API
                    engine = CapCutTTSEngine()
                    voice_code = "BV074_streaming"
                    res_id = "7102355709945188865"
                    for p_val in VOICE_PRESETS.values():
                        if p_val["name"] == chosen:
                            voice_code = p_val["voice"]
                            res_id = p_val["resource_id"]
                            break

                    sample_text = "Xin chào các bạn, đây là bản nghe thử giọng đọc CapCut của bạn."
                    res_list = engine.synthesize_phrases([sample_text], voice=voice_code, resource_id=res_id)
                    if res_list and res_list[0][1]:
                        seg = AudioSegment.from_file(io.BytesIO(res_list[0][1]))
                        seg.export(str(tmp_wav), format="wav")
                        winsound.PlaySound(str(tmp_wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
                        self._append_log(f"Đang phát giọng đọc CapCut trực tiếp: {chosen}", "AUDIO")
                    else:
                        self._append_log(f"Không nhận được âm thanh từ CapCut API cho giọng {chosen}", "WARNING")
            except Exception as e:
                self._append_log(f"Lỗi nghe thử giọng: {e}", "ERROR")
            finally:
                self.after(0, lambda: self.btn_preview_voice.configure(text="▶ Nghe thử", state="normal"))

        threading.Thread(target=_work, daemon=True).start()

    def _open_get_key_url(self):
        """Mở trang quản lý DeepSeek API Key trên trình duyệt"""
        webbrowser.open("https://platform.deepseek.com/api_keys")

    def _check_api_key_clicked(self):
        """Xử lý kiểm tra DeepSeek API Key và hạn ngạch Rate Limit"""
        key = self.key_entry.get().strip()
        model = self.cmb_ai_model.get().strip()

        if not key:
            self.lbl_api_status.configure(
                text="⚠️ Vui lòng nhập DeepSeek API Key trước khi kiểm tra!",
                text_color="#fbbf24"
            )
            return

        self.btn_check_key.configure(state="disabled", text="⏳ Đang test...")
        self.lbl_api_status.configure(
            text="⏳ Đang kết nối tới DeepSeek API và kiểm tra hạn ngạch...",
            text_color="#38bdf8"
        )

        def _worker():
            try:
                from translator import check_deepseek_api_status
                res = check_deepseek_api_status(key, model)

                def _update_ui():
                    self.btn_check_key.configure(state="normal", text="⚡ Test API & Limit")
                    status = res.get("status", "")
                    msg = res.get("message", "")
                    rec_model = res.get("recommended_model", "")
                    rate_limited = res.get("rate_limited_models", [])

                    if status == "OK":
                        self.lbl_api_status.configure(text=msg, text_color="#34d399")
                        if rec_model and rec_model != model and model in rate_limited:
                            if rec_model in self.cmb_ai_model.cget("values"):
                                self.cmb_ai_model.set(rec_model)
                                self._append_log(f"Tự động chuyển Model sang '{rec_model}' (vì '{model}' bị rate limit 429).", "CONFIG")
                    elif status == "RATE_LIMITED":
                        self.lbl_api_status.configure(text=msg, text_color="#fbbf24")
                    else:
                        self.lbl_api_status.configure(text=msg, text_color="#f87171")

                    self._append_log(f"[DeepSeek Check] {msg}", "API")
                    for m_name, m_info in res.get("model_results", {}).items():
                        self._append_log(f"  • {m_name}: {m_info.get('msg', '')}", "API")

                self.after(0, _update_ui)
            except Exception as e:
                def _err():
                    self.btn_check_key.configure(state="normal", text="⚡ Test API")
                    self.lbl_api_status.configure(text=f"❌ Lỗi khi kiểm tra: {e}", text_color="#f87171")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_chatgpt_cookie_help(self):
        """Hiển thị hướng dẫn chi tiết 3 bước lấy Cookie từ chatgpt.com"""
        msg = (
            "👉 CÁCH LẤY COOKIE / SESSION TOKEN CHATGPT (CỰC DỄ TRONG 5 GIÂY):\n\n"
            "Cách 1: Lấy Token tự động (Khuyên dùng):\n"
            "1. Mở trình duyệt, truy cập và đăng nhập vào: https://chatgpt.com\n"
            "2. Mở tab mới, truy cập link: https://chatgpt.com/api/auth/session\n"
            "3. Copy toàn bộ chuỗi nằm trong ngoặc kép sau \"accessToken\": \"...\" (hoặc copy toàn bộ nội dung JSON) và dán vào đây.\n\n"
            "Cách 2: Lấy từ F12 DevTools:\n"
            "1. Tại trang https://chatgpt.com, nhấn phím F12 trên bàn phím.\n"
            "2. Chọn tab 'Application' (hoặc 'Bộ nhớ lưu trữ') -> chọn mục 'Cookies' -> 'https://chatgpt.com'.\n"
            "3. Tìm dòng có tên '__Secure-next-auth.session-token', copy toàn bộ giá trị (Value) của nó và dán vào đây.\n\n"
            "💡 Lưu ý: Cookie ChatGPT hoàn toàn miễn phí, hỗ trợ GPT-4o mượt mà và thường dùng được trong 2-4 tuần trước khi cần lấy lại!"
        )
        messagebox.showinfo("Hướng dẫn lấy Cookie ChatGPT Web", msg)

    def _paste_chatgpt_cookie_clipboard(self):
        """Dán cookie từ clipboard vào ô nhập ChatGPT Cookie"""
        try:
            cb_text = self.clipboard_get().strip()
            if cb_text:
                self.chatgpt_cookie_textbox.delete("1.0", "end")
                self.chatgpt_cookie_textbox.insert("1.0", cb_text)
                self._append_log("Đã dán Cookie ChatGPT từ Clipboard.", "CONFIG")
        except Exception:
            pass

    def _check_chatgpt_cookie_clicked(self):
        """Kiểm tra tính hợp lệ và thời hạn của Cookie ChatGPT"""
        cookie_text = self.chatgpt_cookie_textbox.get("1.0", "end").strip()
        if not cookie_text or "eyJ" not in cookie_text and "session-token" not in cookie_text and len(cookie_text) < 30:
            self.lbl_chatgpt_status.configure(
                text="⚠️ Vui lòng dán Cookie hoặc Session Token ChatGPT hợp lệ trước khi kiểm tra!",
                text_color="#fbbf24"
            )
            return

        self.btn_check_chatgpt.configure(state="disabled", text="⏳ Đang test...")
        self.lbl_chatgpt_status.configure(
            text="⏳ Đang kết nối tới máy chủ ChatGPT Web để xác thực...",
            text_color="#38bdf8"
        )

        def _worker():
            try:
                from translator import check_chatgpt_cookie_status
                res = check_chatgpt_cookie_status(cookie_text)

                def _update_ui():
                    self.btn_check_chatgpt.configure(state="normal", text="🔍 Test Cookie")
                    status = res.get("status", "")
                    msg = res.get("message", "")
                    if res.get("valid"):
                        self.lbl_chatgpt_status.configure(text=msg, text_color="#34d399")
                    else:
                        self.lbl_chatgpt_status.configure(text=msg, text_color="#f87171")
                    self._append_log(f"[ChatGPT Cookie Check] {msg}", "API")

                self.after(0, _update_ui)
            except Exception as e:
                def _err():
                    self.btn_check_chatgpt.configure(state="normal", text="🔍 Test Cookie")
                    self.lbl_chatgpt_status.configure(text=f"❌ Lỗi khi kiểm tra cookie: {e}", text_color="#f87171")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_speed_changed(self, val: float):
        self.lbl_speed_val.configure(text=f"{val:.2f}x (Chậm {int((1-val)*100)}%)")

    def _on_blur_slider_changed(self, _val):
        y_val = self.slider_blur_y.get()
        h_val = self.slider_blur_h.get()
        self.lbl_blur_y_title.configure(text=f"Vị trí mờ (Y): {y_val*100:.0f}%")
        self.lbl_blur_h_title.configure(text=f"Độ cao mờ (H): {h_val*100:.0f}%")
        self.current_blur_region.y_ratio = y_val
        self.current_blur_region.height_ratio = h_val
        self.current_blur_region.x = None
        self.current_blur_region.y = None
        self.current_blur_region.width = None
        self.current_blur_region.height = None

    def _open_visual_roi_selector(self, video_file: Optional[Path] = None):
        """Mở cửa sổ Studio đồ họa cho phép người dùng kéo chuột khoanh vùng mờ & chỉnh tay phụ đề"""
        def on_saved(region: BlurRegion, sub_style: Optional[SubtitleStyle] = None):
            self.current_blur_region = region
            self.slider_blur_y.set(region.y_ratio)
            self.slider_blur_h.set(region.height_ratio)
            self.lbl_blur_y_title.configure(text=f"Vị trí mờ (Y): {region.y_ratio*100:.0f}%")
            self.lbl_blur_h_title.configure(text=f"Độ cao mờ (H): {region.height_ratio*100:.0f}%")

            if sub_style:
                self.current_subtitle_style = copy.copy(sub_style)
                if hasattr(self, "slider_margin_v"):
                    self.slider_margin_v.set(sub_style.margin_v)
                if hasattr(self, "lbl_margin_v"):
                    self.lbl_margin_v.configure(text=f"{sub_style.margin_v}px")
                if hasattr(self, "cmb_font"):
                    self.cmb_font.set(sub_style.font_name)
                if hasattr(self, "cmb_font_size"):
                    self.cmb_font_size.set(str(sub_style.font_size))
                if hasattr(self, "seg_alignment"):
                    if sub_style.alignment == 5:
                        self.seg_alignment.set("⏸️ Giữa màn hình")
                    elif sub_style.alignment == 8:
                        self.seg_alignment.set("⬆️ Trên cùng")
                    else:
                        self.seg_alignment.set("⬇️ Dưới cùng (Mặc định)")
                if hasattr(self, "selected_sub_preset_id") and getattr(sub_style, "preset_id", None):
                    self.selected_sub_preset_id = sub_style.preset_id
                    for pid, btn in self.sub_preset_buttons.items():
                        if pid == self.selected_sub_preset_id:
                            btn.configure(border_color="#06b6d4", border_width=3)
                        else:
                            orig_bc = SUBTITLE_PRESETS.get(pid, {}).get("border_color", "transparent")
                            btn.configure(border_color=orig_bc if orig_bc != "transparent" else "#3f3f46", border_width=2)
                self._update_sub_preview_banner()

            self._append_log(f"Đã cập nhật vùng mờ: Y={region.y_ratio*100:.1f}%, H={region.height_ratio*100:.1f}% (Pixel: X={region.x}, Y={region.y}, W={region.width}, H={region.height})", "CONFIG")
            if sub_style:
                self._append_log(f"🎯 Phụ đề Tiếng Việt: {sub_style.name} (Margin V={sub_style.margin_v}px)", "CONFIG")

        dlg = VisualROISelectorDialog(
            parent=self,
            video_path=video_file,
            initial_blur_region=self.current_blur_region,
            initial_subtitle_style=self.current_subtitle_style,
            on_save_callback=on_saved
        )
        return dlg

    def _select_subtitle_preset(self, preset_id: str):
        """Xử lý khi người dùng click chọn một mẫu phụ đề CapCut trong Grid"""
        if preset_id not in SUBTITLE_PRESETS:
            return
        p_info = SUBTITLE_PRESETS[preset_id]
        self.selected_sub_preset_id = preset_id

        # Cập nhật style hiện tại
        self.current_subtitle_style = copy.copy(p_info["style"])
        if hasattr(self, "cmb_font") and getattr(p_info["style"], "font_name", None):
            self.cmb_font.set(p_info["style"].font_name)
        if hasattr(self, "cmb_font"):
            self.current_subtitle_style.font_name = self.cmb_font.get()
        if hasattr(self, "cmb_font_size"):
            self.current_subtitle_style.font_size = int(self.cmb_font_size.get())
        if hasattr(self, "slider_margin_v"):
            self.current_subtitle_style.margin_v = int(self.slider_margin_v.get())
        if hasattr(self, "seg_alignment"):
            self.current_subtitle_style.alignment = self._get_alignment_code()
        if hasattr(self, "chk_bold_sub"):
            self.current_subtitle_style.bold = 1 if self.chk_bold_sub.get() else 0

        # Cập nhật viền highlight cho các nút trong Grid (giống CapCut)
        for pid, btn in self.sub_preset_buttons.items():
            if pid == preset_id:
                btn.configure(border_color="#06b6d4", border_width=3)
            else:
                orig_bc = SUBTITLE_PRESETS[pid]["border_color"]
                btn.configure(border_color=orig_bc if orig_bc != "transparent" else "#3f3f46", border_width=2)

        self.lbl_selected_sub_preset.configure(text=f"Kiểu đang chọn: 🔥 {p_info['name']}")
        self._update_sub_preview_banner()

    def _on_margin_v_changed(self, val: float):
        px = int(val)
        self.lbl_margin_v.configure(text=f"{px}px")
        if hasattr(self, "current_subtitle_style"):
            self.current_subtitle_style.margin_v = px
        self._update_sub_preview_banner()

    def _set_quick_margin(self, px: int):
        if hasattr(self, "slider_margin_v"):
            self.slider_margin_v.set(px)
        if hasattr(self, "lbl_margin_v"):
            self.lbl_margin_v.configure(text=f"{px}px")
        if hasattr(self, "current_subtitle_style"):
            self.current_subtitle_style.margin_v = px
        self._update_sub_preview_banner()

    def _on_alignment_changed(self, _choice: str):
        align_code = self._get_alignment_code()
        if hasattr(self, "current_subtitle_style"):
            self.current_subtitle_style.alignment = align_code
        self._update_sub_preview_banner()

    def _get_alignment_code(self) -> int:
        if not hasattr(self, "seg_alignment"):
            return 2
        val = self.seg_alignment.get()
        if "Giữa" in val or "Trung" in val:
            return 5
        elif "Trên" in val or "Đỉnh" in val:
            return 8
        return 2

    def _update_sub_preview_banner(self):
        """Cập nhật banner xem trước phụ đề theo thời gian thực (Live Preview)"""
        if not hasattr(self, "lbl_preview_sub_text") or not hasattr(self, "preview_sub_frame"):
            return
        pid = getattr(self, "selected_sub_preset_id", "badge_white_on_black")
        p_info = SUBTITLE_PRESETS.get(pid, SUBTITLE_PRESETS["badge_white_on_black"])

        font_name = self.cmb_font.get() if hasattr(self, "cmb_font") else "Georgia"
        font_size = int(self.cmb_font_size.get()) if hasattr(self, "cmb_font_size") else 18
        is_bold = "bold" if (hasattr(self, "chk_bold_sub") and self.chk_bold_sub.get()) else "normal"

        is_badge = (p_info["style"].border_style == 3)
        self.preview_sub_frame.configure(
            fg_color=p_info["bg_color"] if is_badge else "#18181b",
            border_color=p_info["border_color"] if p_info["border_color"] != "transparent" else "#3f3f46"
        )
        self.lbl_preview_sub_text.configure(
            text_color=p_info["fg_color"],
            font=ctk.CTkFont(family=font_name, size=max(13, min(int(font_size * 0.7), 24)), weight=is_bold)
        )

    def _append_log(self, message: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        formatted_msg = f"[{ts}] [{level}] {message}\n"
        self.log_textbox.insert("end", formatted_msg)
        self.log_textbox.see("end")

    def _update_step_status(self, current_step: int, total_steps: int, title: str, msg: str):
        def gui_update():
            if current_step == -1:
                self.lbl_status.configure(text=f"❌ LỖI: {title}", text_color="#ef4444")
                self._append_log(f"{title}: {msg}", "ERROR")
                return

            fraction = min(max(current_step / total_steps, 0.0), 1.0)
            self.progress_bar.set(fraction)
            self.lbl_status.configure(
                text=f"Đang xử lý [{current_step}/{total_steps}]: {title}",
                text_color="#38bdf8"
            )
            self._append_log(f"{title} - {msg}", "INFO")

            for idx, lbl in enumerate(self.step_labels):
                step_idx = idx + 1
                if step_idx < current_step:
                    lbl.configure(text=f"✔ {lbl.cget('text')[2:]}", text_color="#10b981")
                elif step_idx == current_step:
                    lbl.configure(text=f"🔄 {lbl.cget('text')[2:]}", text_color="#38bdf8")
                else:
                    lbl.configure(text=f"⚪ {lbl.cget('text')[2:]}", text_color="gray70")

            if current_step == total_steps:
                for lbl in self.step_labels:
                    lbl.configure(text=f"✔ {lbl.cget('text')[2:]}", text_color="#10b981")
                self.lbl_status.configure(text="🎉 ĐÃ HOÀN THÀNH TOÀN BỘ QUY TRÌNH!", text_color="#10b981")

        self.after(0, gui_update)

    # -----------------------------------------------------------------
    # SUBTITLE INSPECTOR & STATUS CHECKER HANDLERS
    # -----------------------------------------------------------------
    def _render_empty_sub_placeholder(self):
        """Hiển thị trạng thái rỗng khi chưa có dữ liệu phụ đề"""
        for widget in self.sub_cards_scroll.winfo_children():
            widget.destroy()

        placeholder_frame = ctk.CTkFrame(self.sub_cards_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
        placeholder_frame.pack(fill="x", padx=10, pady=40)

        ctk.CTkLabel(
            placeholder_frame,
            text="💬 CHƯA CÓ DỮ LIỆU PHỤ ĐỀ",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#94a3b8"
        ).pack(pady=(18, 6))

        ctk.CTkLabel(
            placeholder_frame,
            text="Nhập link Douyin và bấm 'BẮT ĐẦU XỬ LÝ VIDEO TỰ ĐỘNG'.\nDanh sách phụ đề song ngữ (Trung - Việt) kèm phân tích độ phủ sẽ tự động cập nhật tại đây!",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            justify="center"
        ).pack(padx=16, pady=(0, 18))

    def _on_subtitles_callback(self, payload: dict):
        """Nhận dữ liệu phụ đề từ pipeline thời gian thực và cập nhật lên GUI"""
        def _update():
            stage = payload.get("stage", "stt")
            items = payload.get("items", [])
            stats = payload.get("stats", {})
            self.current_subtitles_data = items
            self.current_subtitles_stats = stats
            if payload.get("original_srt"):
                self.current_orig_srt_path = Path(payload["original_srt"])
            if payload.get("synced_srt"):
                self.current_synced_srt_path = Path(payload["synced_srt"])
            elif payload.get("translated_srt"):
                self.current_synced_srt_path = Path(payload["translated_srt"])

            # Cập nhật Thẻ Thống Kê (Dashboard Metrics)
            count = len(items)
            self.lbl_sub_stat_count.configure(text=f"🔢 Tổng: {count} câu thoại")
            spoken_dur = stats.get("spoken_duration", 0.0)
            total_dur = stats.get("total_duration", 0.0)
            cov_pct = stats.get("coverage_percent", "0.0%")
            self.lbl_sub_stat_time.configure(text=f"⏱ Thoại: {spoken_dur:.1f}s / {total_dur:.1f}s ({cov_pct})")

            # Huy hiệu tình trạng
            badge_text = stats.get("status_badge", "🟢 ĐẦY ĐỦ")
            badge_color = "#10b981" if "🟢" in badge_text else ("#f59e0b" if "🟡" in badge_text else "#ef4444")
            self.lbl_sub_stat_badge.configure(text=badge_text, text_color=badge_color)

            # Cập nhật Alert Bar
            warnings = stats.get("warnings", [])
            if warnings:
                warn_msg = f"⚠️ Lưu ý: {warnings[0]}" + (f" (+{len(warnings)-1} đoạn khác)" if len(warnings) > 1 else "")
                self.lbl_sub_alert.configure(text=warn_msg, text_color="#fbbf24")
            else:
                self.lbl_sub_alert.configure(
                    text=f"✅ Đã nhận diện đầy đủ {count} câu thoại. Tình trạng phủ âm thanh tốt ({cov_pct})!",
                    text_color="#34d399"
                )

            # Vẽ danh sách thẻ phụ đề
            self._render_subtitle_cards()

            # Tự động chuyển Tab nếu được bật
            if hasattr(self, "chk_auto_switch_sub") and self.chk_auto_switch_sub.get():
                self.right_tabview.set("💬 Kiểm Tra Phụ Đề & Tình Trạng")

            self._append_log(f"[PHỤ ĐỀ] Đã cập nhật {count} câu lên giao diện (Trạng thái: {stats.get('status_text', 'OK')})", "SUB")

        self.after(0, _update)

    def _render_subtitle_cards(self, filter_text: str = ""):
        """Hiển thị danh sách thẻ phụ đề trong Scrollable Frame"""
        for widget in self.sub_cards_scroll.winfo_children():
            widget.destroy()

        self.sub_entry_widgets.clear()

        if not self.current_subtitles_data:
            self._render_empty_sub_placeholder()
            return

        filter_lower = filter_text.strip().lower()
        rendered_count = 0

        for item in self.current_subtitles_data:
            idx = item.get("index", 1)
            orig_text = item.get("text", "")
            trans_text = item.get("translated_text", "")
            start_str = item.get("start_str", "")
            end_str = item.get("end_str", "")
            duration = item.get("duration", 0.0)

            # Lọc theo từ khóa
            if filter_lower:
                if filter_lower not in orig_text.lower() and filter_lower not in trans_text.lower() and filter_lower not in str(idx):
                    continue

            rendered_count += 1
            card = ctk.CTkFrame(self.sub_cards_scroll, fg_color="#18181b", corner_radius=6, border_width=1, border_color="#27272a")
            card.pack(fill="x", padx=4, pady=3)
            card.grid_columnconfigure(0, weight=1)

            # Header thẻ: Số thứ tự + Timeline + Duration
            header_row = ctk.CTkFrame(card, fg_color="transparent")
            header_row.pack(fill="x", padx=8, pady=(4, 2))

            lbl_idx = ctk.CTkLabel(
                header_row,
                text=f"#{idx:02d} • ⏱ {start_str} ➔ {end_str} ({duration:.1f}s)",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#38bdf8"
            )
            lbl_idx.pack(side="left")

            status_lbl = ctk.CTkLabel(
                header_row,
                text="✔ Khớp TTS" if trans_text else "⏳ Gốc",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#34d399" if trans_text else "#94a3b8"
            )
            status_lbl.pack(side="right")

            # Gốc (Tiếng Trung)
            orig_lbl = ctk.CTkLabel(
                card,
                text=f"🇨🇳 {orig_text}",
                font=ctk.CTkFont(size=12),
                text_color="#e2e8f0",
                anchor="w",
                justify="left",
                wraplength=470
            )
            orig_lbl.pack(fill="x", padx=8, pady=(0, 2))

            # Dịch (Tiếng Việt) - Cho phép sửa trực tiếp
            trans_frame = ctk.CTkFrame(card, fg_color="transparent")
            trans_frame.pack(fill="x", padx=8, pady=(0, 6))

            ctk.CTkLabel(trans_frame, text="🇻🇳", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
            
            entry_vn = ctk.CTkEntry(
                trans_frame,
                font=ctk.CTkFont(size=12),
                height=26,
                fg_color="#09090b",
                border_color="#3f3f46"
            )
            entry_vn.pack(side="left", fill="x", expand=True)
            if trans_text:
                entry_vn.insert(0, trans_text)
            else:
                entry_vn.configure(placeholder_text="(Đang chờ dịch...)")

            self.sub_entry_widgets[idx] = entry_vn

        if rendered_count == 0 and filter_lower:
            no_res = ctk.CTkLabel(
                self.sub_cards_scroll,
                text=f"Không tìm thấy câu thoại nào khớp với '{filter_text}'",
                font=ctk.CTkFont(size=12),
                text_color="gray60"
            )
            no_res.pack(pady=20)

    def _filter_subtitles_list(self):
        query = self.sub_search_entry.get().strip()
        self._render_subtitle_cards(query)

    def _save_edited_subtitles(self):
        """Lưu lại các chỉnh sửa phụ đề từ các ô nhập trên giao diện vào file SRT"""
        if not self.current_subtitles_data:
            messagebox.showinfo("Thông báo", "Chưa có dữ liệu phụ đề để lưu!")
            return

        updated_count = 0
        for item in self.current_subtitles_data:
            idx = item.get("index")
            if idx in self.sub_entry_widgets:
                new_val = self.sub_entry_widgets[idx].get().strip()
                if new_val:
                    item["translated_text"] = new_val
                    updated_count += 1

        # Ghi đè vào file SRT đồng bộ
        if self.current_synced_srt_path:
            try:
                blocks = []
                for item in self.current_subtitles_data:
                    txt = item.get("translated_text") or item.get("text", "")
                    blocks.append(f"{item['index']}\n{item['start_str']} --> {item['end_str']}\n{txt}\n")
                
                self.current_synced_srt_path.write_text("\n".join(blocks).strip() + "\n", encoding="utf-8")
                self._append_log(f"Đã lưu thành công {updated_count} câu phụ đề vào: {self.current_synced_srt_path.name}", "SUB")
                messagebox.showinfo("Thành công", f"Đã cập nhật và lưu {updated_count} câu phụ đề vào file SRT!")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể lưu file SRT: {e}")
        else:
            messagebox.showinfo("Thông báo", "Đã cập nhật dữ liệu trên bộ nhớ!")

    def _copy_all_subtitles(self):
        """Sao chép toàn bộ danh sách phụ đề song ngữ vào Clipboard"""
        if not self.current_subtitles_data:
            messagebox.showinfo("Thông báo", "Chưa có phụ đề để sao chép!")
            return

        lines = []
        for item in self.current_subtitles_data:
            idx = item.get("index", 1)
            t_range = f"{item.get('start_str')} --> {item.get('end_str')}"
            orig = item.get("text", "")
            trans = item.get("translated_text", "")
            lines.append(f"#{idx} [{t_range}]\n🇨🇳 {orig}\n🇻🇳 {trans}\n")

        full_text = "\n".join(lines).strip()
        try:
            self.clipboard_clear()
            self.clipboard_append(full_text)
            self._append_log(f"Đã copy toàn bộ {len(self.current_subtitles_data)} câu phụ đề vào Clipboard.", "SUB")
            messagebox.showinfo("Đã sao chép", f"Đã copy {len(self.current_subtitles_data)} câu phụ đề vào Clipboard!")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể copy: {e}")

    def _open_orig_srt_file(self):
        if self.current_orig_srt_path and self.current_orig_srt_path.exists():
            if sys.platform == "win32":
                os.startfile(str(self.current_orig_srt_path))
            else:
                subprocess.run(["xdg-open", str(self.current_orig_srt_path)])
        else:
            messagebox.showinfo("Thông báo", "Chưa có file SRT tiếng Trung gốc!")

    def _open_synced_srt_file(self):
        if self.current_synced_srt_path and self.current_synced_srt_path.exists():
            if sys.platform == "win32":
                os.startfile(str(self.current_synced_srt_path))
            else:
                subprocess.run(["xdg-open", str(self.current_synced_srt_path)])
        else:
            messagebox.showinfo("Thông báo", "Chưa có file SRT tiếng Việt!")

    def _interactive_sub_review_hook(self, session_work_dir: Path, srt_file: Path):
        """Hook dừng pipeline lại để người dùng duyệt và sửa phụ đề trên GUI trước khi render"""
        self.sub_resume_event = threading.Event()
        self.current_session_work_dir = session_work_dir
        self.current_synced_srt_path = srt_file

        def show_pause():
            self.right_tabview.set("💬 Kiểm Tra Phụ Đề & Tình Trạng")
            self.sub_review_resume_frame.grid(row=4, column=0, sticky="ew", padx=2, pady=(4, 2))
            self.lbl_sub_alert.configure(
                text="⏸ TẠM DỪNG ĐỂ DUYỆT: Vui lòng kiểm tra các câu phụ đề bên dưới. Sau khi hoàn tất, nhấn nút xanh để Render!",
                text_color="#fbbf24"
            )
            self._append_log("Đang tạm dừng để bạn kiểm tra & duyệt phụ đề trên GUI...", "PAUSE")

        self.after(0, show_pause)
        self.sub_resume_event.wait()

        def hide_pause():
            self.sub_review_resume_frame.grid_forget()

        self.after(0, hide_pause)

    def _resume_pipeline_after_review(self):
        """Tiếp tục render sau khi người dùng bấm nút xác nhận trên GUI"""
        self._save_edited_subtitles()
        if self.sub_resume_event:
            self.sub_resume_event.set()
            self._append_log("Đã xác nhận phụ đề! Tiếp tục quy trình Master Render...", "RESUME")

    def _start_pipeline(self):
        if self.is_running:
            return

        raw_url = self.url_textbox.get("1.0", "end").strip()
        if not raw_url:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đường link Video Douyin!")
            return

        # Xác định AI Provider được chọn
        is_chatgpt_tab = hasattr(self, "ai_tabview") and "ChatGPT" in self.ai_tabview.get()
        llm_provider = "chatgpt_cookie" if is_chatgpt_tab else "deepseek"

        chatgpt_cookie_val = self.chatgpt_cookie_textbox.get("1.0", "end").strip() if hasattr(self, "chatgpt_cookie_textbox") else ""
        chatgpt_model_val = self.cmb_chatgpt_model.get().strip() if hasattr(self, "cmb_chatgpt_model") else "auto"

        if is_chatgpt_tab:
            if not chatgpt_cookie_val or "__Secure-next-auth" not in chatgpt_cookie_val and not chatgpt_cookie_val.startswith("eyJ") and len(chatgpt_cookie_val) < 20:
                messagebox.showwarning("Cảnh báo", "Vui lòng dán Cookie hoặc Session Token ChatGPT vào ô nhập trong tab ChatGPT Web!")
                return
            api_key = ""
        else:
            api_key = self.key_entry.get().strip()
            if not api_key:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập DeepSeek API Key trong tab DeepSeek API!")
                return

        self._save_settings()

        cookie_tab = self.cookie_tabview.get()
        cookie_cfg = CookieConfig()

        if cookie_tab == "Nhập chuỗi Cookie":
            c_text = self.cookie_textbox.get("1.0", "end").strip()
            if c_text:
                cookie_cfg.cookie_str = c_text
        elif cookie_tab == "File cookies.txt":
            if getattr(self, "selected_cookie_file_path", ""):
                cookie_cfg.cookie_file = Path(self.selected_cookie_file_path)
        elif cookie_tab == "Đọc từ Trình duyệt":
            cookie_cfg.browser_name = self.cmb_browser.get().lower()

        voice_raw = self.cmb_voice.get()
        voice_code = "BV074_streaming"
        res_id = "7102355709945188865"
        rate_val = "1.0"

        for p_key, p_val in VOICE_PRESETS.items():
            if p_val["name"] == voice_raw or p_key in voice_raw.lower() or p_val["voice"] == voice_raw:
                voice_code = p_val["voice"]
                res_id = p_val["resource_id"]
                rate_val = p_val.get("rate", "1.0")
                break

        speed_factor = float(self.slider_speed.get())
        final_speed = float(self.slider_final_speed.get()) if hasattr(self, "slider_final_speed") else 1.20
        keep_bgm = bool(self.chk_bgm.get())
        bgm_vol = float(self.slider_bgm_vol.get())
        font_name = self.cmb_font.get()
        font_size = int(self.cmb_font_size.get())
        blur_enabled = bool(self.chk_blur.get())
        smart_blur_enabled = bool(self.chk_smart_blur.get()) if hasattr(self, "chk_smart_blur") else True
        is_interactive_roi = bool(self.chk_interactive_roi.get())
        is_review_sub = bool(self.chk_review_sub.get()) if hasattr(self, "chk_review_sub") else False

        self.current_blur_region.enabled = blur_enabled
        self.current_blur_region.smart_blur = smart_blur_enabled

        # Xây dựng SubtitleStyle hoàn chỉnh từ mẫu đang chọn và font/size/margin/alignment
        sub_style = copy.copy(getattr(self, "current_subtitle_style", SUBTITLE_PRESETS["badge_white_on_black"]["style"]))
        sub_style.font_name = font_name
        sub_style.font_size = font_size
        if hasattr(self, "slider_margin_v"):
            sub_style.margin_v = int(self.slider_margin_v.get())
        sub_style.alignment = self._get_alignment_code()
        if hasattr(self, "chk_bold_sub"):
            sub_style.bold = 1 if self.chk_bold_sub.get() else 0

        sep_speed_val = self.cmb_sep_speed.get() if hasattr(self, "cmb_sep_speed") else "turbo"
        sep_speed_code = "turbo"
        if "Fast" in sep_speed_val or "25%" in sep_speed_val:
            sep_speed_code = "fast"
        elif "Balanced" in sep_speed_val or "50%" in sep_speed_val:
            sep_speed_code = "balanced"
        elif "HQ" in sep_speed_val or "75%" in sep_speed_val:
            sep_speed_code = "hq"

        topic_val = self.cmb_topic.get() if hasattr(self, "cmb_topic") else "100"
        topic_code = "minecraft_100_days_hardcore"
        if "100" in topic_val or "Hardcore" in topic_val:
            topic_code = "minecraft_100_days_hardcore"
        elif "Trẻ Em" in topic_val or "nhí" in topic_val:
            topic_code = "minecraft_kids"
        elif "Game" in topic_val or "Esports" in topic_val:
            topic_code = "gaming_general"
        elif "Hài Hước" in topic_val:
            topic_code = "comedy_entertainment"
        else:
            topic_code = "general"

        res_val = self.cmb_export_res.get() if hasattr(self, "cmb_export_res") else "1080p"
        res_code = "1080p"
        if "1080p" in res_val:
            res_code = "1080p"
        elif "720p" in res_val:
            res_code = "720p"
        elif "2K" in res_val or "1440p" in res_val:
            res_code = "2k"
        elif "Gốc" in res_val or "Original" in res_val:
            res_code = "original"

        config = PipelineConfig(
            llm_provider=llm_provider,
            deepseek_api_key=api_key,
            deepseek_model_name=self.cmb_ai_model.get().strip() if hasattr(self, "cmb_ai_model") else "deepseek-v4-flash",
            chatgpt_cookie=chatgpt_cookie_val,
            chatgpt_model_name=chatgpt_model_val,
            topic_preset=topic_code,
            speed_factor=speed_factor,
            final_speed=final_speed,
            export_resolution=res_code,
            keep_bgm=keep_bgm,
            bgm_volume=bgm_vol,
            separation_speed=sep_speed_code,
            cookie_config=cookie_cfg,
            blur_region=self.current_blur_region,
            subtitle_style=sub_style,
            tts_config=TTSConfig(
                voice=voice_code,
                resource_id=res_id,
                rate=rate_val,
                preset_name=voice_raw
            )
        )

        self.is_running = True
        self.btn_run.configure(text="⏳ ĐANG XỬ LÝ VIDEO...", state="disabled", fg_color="#6b7280")
        self.btn_play_video.configure(state="disabled")
        self.progress_bar.set(0.0)
        self.log_textbox.delete("1.0", "end")

        for lbl in self.step_labels:
            lbl.configure(text=f"⚪ {lbl.cget('text')[2:]}", text_color="gray70")

        self._append_log("Bắt đầu khởi chạy quy trình tự động hóa...", "START")

        def interactive_roi_hook(raw_video_path: Path, current_region: BlurRegion, current_sub_style: Optional[SubtitleStyle] = None) -> Tuple[BlurRegion, Optional[SubtitleStyle]]:
            """Hàm hook chặn luồng xử lý để mở Studio chọn vùng mờ & chỉnh tay phụ đề trên video vừa tải"""
            event = threading.Event()
            chosen_container = {
                "region": current_region,
                "sub_style": current_sub_style or self.current_subtitle_style
            }

            def open_dialog():
                def on_save(r: BlurRegion, s: Optional[SubtitleStyle] = None):
                    chosen_container["region"] = r
                    self.current_blur_region = r
                    self.slider_blur_y.set(r.y_ratio)
                    self.slider_blur_h.set(r.height_ratio)

                    if s:
                        chosen_container["sub_style"] = s
                        self.current_subtitle_style = copy.copy(s)
                        if hasattr(self, "slider_margin_v"):
                            self.slider_margin_v.set(s.margin_v)
                        if hasattr(self, "lbl_margin_v"):
                            self.lbl_margin_v.configure(text=f"{s.margin_v}px")
                        if hasattr(self, "cmb_font_size"):
                            self.cmb_font_size.set(str(s.font_size))
                        if hasattr(self, "cmb_font"):
                            self.cmb_font.set(s.font_name)
                        self._update_sub_preview_banner()

                    self._append_log(f"Đã chọn vùng mờ: Pixel X={r.x}, Y={r.y}, W={r.width}, H={r.height} ({r.y_ratio*100:.1f}%)", "ROI")
                    if s:
                        self._append_log(f"🎯 Phụ đề Tiếng Việt: {s.name} (Margin V={s.margin_v}px)", "ROI")
                    event.set()

                dlg = VisualROISelectorDialog(
                    parent=self,
                    video_path=raw_video_path,
                    initial_blur_region=current_region,
                    initial_subtitle_style=current_sub_style or self.current_subtitle_style,
                    on_save_callback=on_save
                )
                # Nếu người dùng đóng cửa sổ mà không bấm Lưu -> dùng cấu hình hiện tại
                dlg.protocol("WM_DELETE_WINDOW", lambda: (event.set(), dlg.destroy()))

            self.after(0, open_dialog)
            event.wait()
            return chosen_container["region"], chosen_container["sub_style"]

        def worker():
            try:
                pipeline = DouyinAutoPipeline(config=config)
                final_video = pipeline.run(
                    douyin_url_or_text=raw_url,
                    progress_callback=self._update_step_status,
                    interactive_roi_callback=interactive_roi_hook if is_interactive_roi else None,
                    subtitles_callback=self._on_subtitles_callback,
                    review_subtitles_callback=self._interactive_sub_review_hook if is_review_sub else None
                )
                self.last_output_video = final_video

                def on_success():
                    self.is_running = False
                    self.btn_run.configure(text="🚀 BẮT ĐẦU XỬ LÝ VIDEO TỰ ĐỘNG", state="normal", fg_color="#10b981")
                    self.btn_play_video.configure(state="normal")
                    messagebox.showinfo("Thành công", f"Đã edit và dịch video thành công!\n\nFile lưu tại: {final_video.name}")

                self.after(0, on_success)

            except Exception as e:
                err_msg = str(e)
                def on_error(err=err_msg):
                    self.is_running = False
                    self.btn_run.configure(text="🚀 BẮT ĐẦU XỬ LÝ VIDEO TỰ ĐỘNG", state="normal", fg_color="#10b981")
                    messagebox.showerror("Lỗi xử lý", f"Đã xảy ra lỗi trong quá trình thực hiện:\n\n{err}")

                self.after(0, on_error)

        self.pipeline_thread = threading.Thread(target=worker, daemon=True)
        self.pipeline_thread.start()

    def _open_output_folder(self):
        out_dir = Path("output").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(out_dir))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(out_dir)])
        else:
            subprocess.run(["xdg-open", str(out_dir)])

    def _play_output_video(self):
        if self.last_output_video and self.last_output_video.exists():
            if sys.platform == "win32":
                os.startfile(str(self.last_output_video))
            else:
                subprocess.run(["xdg-open", str(self.last_output_video)])
        else:
            messagebox.showinfo("Thông báo", "Chưa có video thành phẩm nào được tạo!")


def main():
    app = DouyinEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
