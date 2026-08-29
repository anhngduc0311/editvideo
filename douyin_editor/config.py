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
    font_name: str = "Arial"
    font_size: int = 22
    primary_color: str = "&H00FFFFFF"    # Chữ trắng (ABGR)
    outline_color: str = "&H00000000"    # Viền đen
    back_color: str = "&H80000000"       # Nền bóng mờ (50% opacity)
    outline_width: int = 2               # Độ dày viền chữ
    shadow: int = 1                      # Đổ bóng
    margin_v: int = 35                   # Khoảng cách từ mép dưới màn hình (pixel)
    bold: int = 1                        # In đậm (1 = True, 0 = False)
    alignment: int = 2                   # Căn giữa dưới cùng (ASS standard = 2)


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
    speed_factor: float = 0.70
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
