"""
config.py - Centralized Configuration for Douyin Video Automation Pipeline
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional

# Tự động nạp FFmpeg vào PATH nếu có static_ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass


@dataclass
class BlurRegion:
    """
    Khu vực làm mờ phụ đề gốc (Bounding box).
    Có thể tự chỉnh tọa độ hoặc dùng tỷ lệ tự động (% chiều cao video).
    """
    x: Optional[int] = None       # Tọa độ X (pixel) - None để tự động căn giữa
    y: Optional[int] = None       # Tọa độ Y (pixel) - None để tự tính theo tỷ lệ
    width: Optional[int] = None   # Chiều rộng vùng mờ - None để full width
    height: Optional[int] = None  # Chiều cao vùng mờ - None để tính theo tỷ lệ
    
    # Tỷ lệ mặc định theo kích thước video (nếu không set pixel cứng)
    y_ratio: float = 0.72         # Vị trí bắt đầu mờ từ 72% chiều cao video
    height_ratio: float = 0.18    # Chiều cao vùng mờ chiếm 18% chiều cao video
    blur_power: int = 15          # Độ mờ của filter boxblur (lpower:rpower)
    enabled: bool = True


@dataclass
class SubtitleStyle:
    """
    Cấu hình hiển thị phụ đề tiếng Việt khi Hardcode (Burn-in) vào video.
    Màu sắc theo định dạng ASS (&H<Alpha><Blue><Green><Red> hoặc Hex).
    """
    preset_id: str = "capcut_default"
    name: str = "Trắng viền đen (CapCut)"
    font_name: str = "Arial"
    font_size: int = 22
    primary_color: str = "&H00FFFFFF"    # Chữ trắng (ABGR)
    outline_color: str = "&H00000000"    # Viền đen
    back_color: str = "&H80000000"       # Nền bóng mờ (50% opacity)
    outline_width: float = 2.5           # Độ dày viền chữ
    shadow: float = 1.2                  # Đổ bóng
    margin_v: int = 35                   # Khoảng cách từ mép dưới màn hình (pixel)
    bold: int = 1                        # In đậm (1 = True, 0 = False)
    alignment: int = 2                   # Căn giữa dưới cùng (ASS standard = 2)
    border_style: int = 1                # 1 = Viền & Đổ bóng, 3 = Hộp chữ nhật (Badge)


SUBTITLE_PRESETS = {
    "none": {
        "id": "none",
        "name": "Chữ mộc (Không viền)",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#262626",
        "border_color": "#404040",
        "style": SubtitleStyle(
            preset_id="none",
            name="Chữ mộc (Không viền)",
            primary_color="&H00FFFFFF",
            outline_color="&H00000000",
            outline_width=0,
            shadow=0,
            border_style=1
        )
    },
    "capcut_default": {
        "id": "capcut_default",
        "name": "Trắng viền đen (CapCut)",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#262626",
        "border_color": "#000000",
        "style": SubtitleStyle(
            preset_id="capcut_default",
            name="Trắng viền đen (CapCut)",
            primary_color="&H00FFFFFF",
            outline_color="&H00000000",
            outline_width=2.5,
            shadow=1.2,
            border_style=1
        )
    },
    "white_thick_black": {
        "id": "white_thick_black",
        "name": "Trắng viền đen đậm",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#1f2937",
        "border_color": "#000000",
        "style": SubtitleStyle(
            preset_id="white_thick_black",
            name="Trắng viền đen đậm",
            primary_color="&H00FFFFFF",
            outline_color="&H00000000",
            outline_width=4.0,
            shadow=0,
            border_style=1
        )
    },
    "white_soft_shadow": {
        "id": "white_soft_shadow",
        "name": "Trắng bóng mờ",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#262626",
        "border_color": "transparent",
        "style": SubtitleStyle(
            preset_id="white_soft_shadow",
            name="Trắng bóng mờ",
            primary_color="&H00FFFFFF",
            outline_color="&H00000000",
            back_color="&HA0000000",
            outline_width=0.5,
            shadow=3.0,
            border_style=1
        )
    },
    "tiktok_yellow_black": {
        "id": "tiktok_yellow_black",
        "name": "Vàng viền đen (TikTok)",
        "preview_text": "Aa",
        "fg_color": "#facc15",
        "bg_color": "#262626",
        "border_color": "#000000",
        "style": SubtitleStyle(
            preset_id="tiktok_yellow_black",
            name="Vàng viền đen (TikTok)",
            primary_color="&H0000E5FF",  # Vàng
            outline_color="&H00000000",
            outline_width=3.0,
            shadow=1.0,
            border_style=1
        )
    },
    "red_white_outline": {
        "id": "red_white_outline",
        "name": "Đỏ viền trắng",
        "preview_text": "Aa",
        "fg_color": "#ef4444",
        "bg_color": "#262626",
        "border_color": "#ffffff",
        "style": SubtitleStyle(
            preset_id="red_white_outline",
            name="Đỏ viền trắng",
            primary_color="&H002020E5",  # Đỏ
            outline_color="&H00FFFFFF",  # Trắng
            outline_width=2.5,
            shadow=1.0,
            border_style=1
        )
    },
    "orange_white_outline": {
        "id": "orange_white_outline",
        "name": "Cam viền trắng",
        "preview_text": "Aa",
        "fg_color": "#f97316",
        "bg_color": "#262626",
        "border_color": "#ffffff",
        "style": SubtitleStyle(
            preset_id="orange_white_outline",
            name="Cam viền trắng",
            primary_color="&H000080FF",  # Cam
            outline_color="&H00FFFFFF",  # Trắng
            outline_width=2.5,
            shadow=1.0,
            border_style=1
        )
    },
    "blue_white_outline": {
        "id": "blue_white_outline",
        "name": "Xanh dương viền trắng",
        "preview_text": "Aa",
        "fg_color": "#0ea5e9",
        "bg_color": "#262626",
        "border_color": "#ffffff",
        "style": SubtitleStyle(
            preset_id="blue_white_outline",
            name="Xanh dương viền trắng",
            primary_color="&H00FF9900",  # Xanh dương
            outline_color="&H00FFFFFF",  # Trắng
            outline_width=2.5,
            shadow=1.0,
            border_style=1
        )
    },
    "green_black_outline": {
        "id": "green_black_outline",
        "name": "Xanh lá viền đen",
        "preview_text": "Aa",
        "fg_color": "#22c55e",
        "bg_color": "#262626",
        "border_color": "#000000",
        "style": SubtitleStyle(
            preset_id="green_black_outline",
            name="Xanh lá viền đen",
            primary_color="&H0000FF00",  # Xanh lá
            outline_color="&H00000000",  # Đen
            outline_width=2.5,
            shadow=1.0,
            border_style=1
        )
    },
    "badge_black_on_white": {
        "id": "badge_black_on_white",
        "name": "Chữ đen nền hộp trắng (Badge)",
        "preview_text": "Aa",
        "fg_color": "#000000",
        "bg_color": "#ffffff",
        "border_color": "#e5e7eb",
        "style": SubtitleStyle(
            preset_id="badge_black_on_white",
            name="Chữ đen nền hộp trắng (Badge)",
            primary_color="&H00000000",  # Đen
            outline_color="&H00FFFFFF",
            back_color="&H00FFFFFF",     # Hộp trắng
            outline_width=4.0,
            shadow=0,
            border_style=3
        )
    },
    "badge_white_on_black": {
        "id": "badge_white_on_black",
        "name": "Chữ trắng nền hộp đen (Badge)",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#000000",
        "border_color": "#374151",
        "style": SubtitleStyle(
            preset_id="badge_white_on_black",
            name="Chữ trắng nền hộp đen (Badge)",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H00000000",
            back_color="&H00000000",     # Hộp đen
            outline_width=4.0,
            shadow=0,
            border_style=3
        )
    },
    "badge_black_on_yellow": {
        "id": "badge_black_on_yellow",
        "name": "Chữ đen nền hộp vàng (Badge)",
        "preview_text": "Aa",
        "fg_color": "#000000",
        "bg_color": "#eab308",
        "border_color": "#ca8a04",
        "style": SubtitleStyle(
            preset_id="badge_black_on_yellow",
            name="Chữ đen nền hộp vàng (Badge)",
            primary_color="&H00000000",  # Đen
            outline_color="&H0000D7FF",
            back_color="&H0000D7FF",     # Hộp vàng
            outline_width=4.0,
            shadow=0,
            border_style=3
        )
    },
    "badge_white_on_purple": {
        "id": "badge_white_on_purple",
        "name": "Chữ trắng nền hộp tím (Badge)",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#8b5cf6",
        "border_color": "#7c3aed",
        "style": SubtitleStyle(
            preset_id="badge_white_on_purple",
            name="Chữ trắng nền hộp tím (Badge)",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H00D00070",
            back_color="&H00D00070",     # Hộp tím
            outline_width=4.0,
            shadow=0,
            border_style=3
        )
    },
    "cyan_neon_outline": {
        "id": "cyan_neon_outline",
        "name": "Chữ đen viền xanh Neon",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#0f172a",
        "border_color": "#06b6d4",
        "style": SubtitleStyle(
            preset_id="cyan_neon_outline",
            name="Chữ đen viền xanh Neon",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H00FFFF00",  # Cyan Neon
            outline_width=3.0,
            shadow=1.0,
            border_style=1
        )
    },
    "glitch_3d_shadow": {
        "id": "glitch_3d_shadow",
        "name": "Vàng đổ bóng 3D Đỏ",
        "preview_text": "Aa",
        "fg_color": "#facc15",
        "bg_color": "#262626",
        "border_color": "#b91c1c",
        "style": SubtitleStyle(
            preset_id="glitch_3d_shadow",
            name="Vàng đổ bóng 3D Đỏ",
            primary_color="&H0000E5FF",  # Vàng
            outline_color="&H0000008B",
            back_color="&H000000FF",     # Bóng đỏ 3D
            outline_width=1.5,
            shadow=3.5,
            border_style=1
        )
    },
    "neon_glow_pink": {
        "id": "neon_glow_pink",
        "name": "Phát sáng Neon Hồng",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#262626",
        "border_color": "#ec4899",
        "style": SubtitleStyle(
            preset_id="neon_glow_pink",
            name="Phát sáng Neon Hồng",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H008020FF",  # Hồng Neon
            back_color="&H008020FF",
            outline_width=3.5,
            shadow=2.0,
            border_style=1
        )
    },
    "neon_glow_yellow": {
        "id": "neon_glow_yellow",
        "name": "Phát sáng Neon Vàng",
        "preview_text": "Aa",
        "fg_color": "#fef08a",
        "bg_color": "#262626",
        "border_color": "#eab308",
        "style": SubtitleStyle(
            preset_id="neon_glow_yellow",
            name="Phát sáng Neon Vàng",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H0000FFFF",  # Vàng Neon
            back_color="&H0000FFFF",
            outline_width=3.5,
            shadow=2.0,
            border_style=1
        )
    },
    "neon_glow_green": {
        "id": "neon_glow_green",
        "name": "Phát sáng Neon Xanh",
        "preview_text": "Aa",
        "fg_color": "#86efac",
        "bg_color": "#262626",
        "border_color": "#22c55e",
        "style": SubtitleStyle(
            preset_id="neon_glow_green",
            name="Phát sáng Neon Xanh",
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H0000FF00",  # Xanh Neon
            back_color="&H0000FF00",
            outline_width=3.5,
            shadow=2.0,
            border_style=1
        )
    }
}



VOICE_PRESETS = {
    "co_gai_hoat_ngon": {
        "name": "🔥 Cô Gái Hoạt Ngôn (CapCut Chính Chủ)",
        "voice": "BV074_streaming",
        "resource_id": "7102355709945188865",
        "rate": "1.0"
    },
    "thanh_nien_tu_tin": {
        "name": "🔥 Thanh Niên Tự Tin (CapCut Chính Chủ)",
        "voice": "BV075_streaming",
        "resource_id": "7102355709945188866",
        "rate": "1.0"
    },
    "nho_ngot_ngao": {
        "name": "🌸 Nhỏ Ngọt Ngào (CapCut Nữ Dễ Thương)",
        "voice": "BV421_vivn_streaming",
        "resource_id": "7252594014782755330",
        "rate": "1.0"
    },
    "mai_truyen_cam": {
        "name": "✨ Mai (CapCut Nữ Truyền Cảm)",
        "voice": "BV562_streaming",
        "resource_id": "7483736254694035984",
        "rate": "1.0"
    },
    "nu_pho_thong": {
        "name": "🎙️ Giọng Nữ Phổ Thông (CapCut Chuẩn)",
        "voice": "vi_female_huong",
        "resource_id": "7264854897953083905",
        "rate": "1.0"
    },
    "kenny_dai_de": {
        "name": "⚡ Kenny Đại Đế (CapCut Giọng Ngầu)",
        "voice": "BV075_streaming_demon_dsp",
        "resource_id": "7569442422665661712",
        "rate": "1.0"
    }
}


@dataclass
class TTSConfig:
    """
    Cấu hình Text-to-Speech tiếng Việt (CapCut Native TTS)
    """
    voice: str = "BV074_streaming"
    resource_id: str = "7102355709945188865"
    rate: str = "1.0"                    # Tốc độ đọc CapCut (1.0 = chuẩn)
    preset_name: str = "Cô Gái Hoạt Ngôn (CapCut Chính Chủ)"


@dataclass
class CookieConfig:
    """
    Cấu hình Cookie Douyin (Tránh lỗi: Fresh cookies needed)
    """
    cookie_str: Optional[str] = None     # Chuỗi cookie dạng: "name=value; name2=value2..."
    cookie_file: Optional[Path] = None   # Đường dẫn file cookies.txt (Netscape format)
    browser_name: Optional[str] = None   # Lấy trực tiếp từ browser: "chrome", "edge", "brave", "firefox"


@dataclass
class PipelineConfig:
    """
    Cấu hình toàn bộ quy trình tự động hóa
    """
    # API & AI Models (DeepSeek / Gemini)
    llm_provider: str = "deepseek"  # "deepseek" hoặc "gemini"
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "sk-7731fa779b8a46fda7e9e48c46bce715"))
    deepseek_model_name: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model_name: str = "gemini-3.6-flash"
    whisper_model_size: str = "small"
    whisper_language: str = "zh"
    
    # Video Processing
    speed_factor: float = 0.70           # Tốc độ làm chậm để AI dịch & đọc tiếng Việt khớp timeline
    final_speed: float = 1.20            # Tốc độ tăng tốc khi render video thành phẩm ở Bước 8 (mặc định 1.2x)
    video_crf: int = 18
    video_preset: str = "medium"
    
    # Audio Settings
    keep_bgm: bool = False               # Mặc định Mute giọng Trung cũ để thay thế hoàn toàn bằng giọng Tiếng Việt
    bgm_volume: float = 0.25
    tts_volume: float = 1.00
    audio_ducking: bool = True
    
    # Cookies & Downloader Settings
    cookie_config: CookieConfig = field(default_factory=CookieConfig)
    
    # Subtitle Styling & Blur
    blur_region: BlurRegion = field(default_factory=BlurRegion)
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)
    tts_config: TTSConfig = field(default_factory=TTSConfig)
    
    # Paths & Directories
    work_dir: Path = field(default_factory=lambda: Path("workspace_temp"))
    download_dir: Path = field(default_factory=lambda: Path("downloads"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    
    def setup_directories(self) -> None:
        """Tạo các thư mục cần thiết nếu chưa tồn tại"""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
