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
    font_size: int = 18
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


TRANSLATION_TOPIC_PRESETS = {
    "minecraft_kids": {
        "id": "minecraft_kids",
        "name": "🎮 Minecraft cho Trẻ Em (Vui nhộn, chuẩn gamer nhí)",
        "description": "Tối ưu ngữ cảnh Minecraft thiếu nhi, xưng hô 'mình/các bạn', từ vựng chuẩn gamer Việt, ngắn gọn, giàu cảm xúc.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: Video về game MINECRAFT dành cho TRẺ EM / THIẾU NHI / GAME THỦ NHÍ xem.\n\n"
            "1. PHONG CÁCH & VĂN PHONG DÀNH CHO TRẺ EM:\n"
            "- Giọng điệu: Hào hứng, vui tươi, nhí nhảnh, hồi hộp, kịch tính, cuốn hút và dễ thương.\n"
            "- Xưng hô thân mật, gần gũi: Dùng 'mình', 'tớ', 'tụi mình' và gọi người xem là 'các bạn ơi', 'mọi người ơi', 'các bạn'.\n"
            "- TUYỆT ĐỐI KHÔNG dùng đại từ cứng nhắc/người lớn như 'tôi - bạn', 'chúng tôi', 'quý vị', 'ngươi - ta'.\n"
            "- Câu từ trong sáng, giàu cảm xúc cảm thán ('Trời ơi!', 'Cứu mình với!', 'U là trời!', 'Xem này các bạn ơi!', 'Đỉnh chóp quá!', 'Chạy mau thôi!').\n\n"
            "2. BỘ TỪ ĐIỂN THUẬT NGỮ MINECRAFT CHUẨN GAMER VIỆT (BẮT BUỘC SỬ DỤNG ĐÚNG):\n"
            "  • Quái vật & Sinh vật:\n"
            "    - 苦力怕 / 爬行者 -> Creeper (hoặc quái nổ)\n"
            "    - 僵尸 / 丧尸 -> Zombie (xác sống)\n"
            "    - 骷髅 / 骷髅弓箭手 -> Skeleton (bộ xương bắn cung)\n"
            "    - 末影人 / 小黑 -> Enderman\n"
            "    - 末影龙 -> Rồng Ender (Ender Dragon)\n"
            "    - 村民 -> Dân làng / bác dân làng\n"
            "    - 铁傀儡 -> Golem sắt (Người sắt bảo vệ)\n"
            "    - 监守者 / 潜声守卫 -> Quái vật Warden (Quái bóng tối)\n"
            "    - 凋灵 -> Quái Wither (Trùm Wither 3 đầu)\n"
            "    - 猪灵 -> Piglin (Heo địa ngục)\n"
            "    - 史莱姆 -> Slime (Cục thạch)\n"
            "    - 烈焰人 -> Quái lửa Blaze\n"
            "    - 恶魂 -> Ma địa ngục Ghast\n"
            "    - 溺尸 -> Zombie đuối nước (Drowned)\n"
            "    - 掠夺者 -> Kẻ cướp dân làng (Pillager)\n\n"
            "  • Khối, Trang bị & Vật phẩm:\n"
            "    - 钻石 / 钻石套 -> Kim cương / Bộ giáp kim cương\n"
            "    - 下界合金 / 狱髓 -> Netherite / Giáp Netherite xịn nhất\n"
            "    - 黑曜石 -> Đá Obsidian (Hắc diện thạch)\n"
            "    - 基岩 -> Đá nền (Bedrock - không thể phá hủy)\n"
            "    - 红石 -> Đá đỏ (Mạch đá đỏ)\n"
            "    - 附魔金苹果 -> Táo vàng phù phép (Táo Enchant / Táo Notch)\n"
            "    - 不死图腾 -> Bùa bất tử (Totem bất tử cứu mạng)\n"
            "    - 鞘翅 -> Cánh cứng Elytra (Cánh lượn)\n"
            "    - 镐子 / 斧头 / 剑 / 弓 -> Cúp đào đá / Rìu / Kiếm / Cung tên\n"
            "    - 工作台 / 熔炉 / 箱子 -> Bàn chế tạo / Lò nung / Rương đồ\n"
            "    - 潜影盒 -> Hộp Shulker (Hộp ma thuật)\n"
            "    - 药水 / 隐身药水 -> Thuốc phù thủy / Thuốc tàng hình\n"
            "    - TNT -> Thuốc nổ TNT\n\n"
            "  • Hành động & Cơ chế chơi:\n"
            "    - 挖矿 / 下矿 -> Đi đào mỏ / Đào khoáng sản\n"
            "    - 合成 / 打造 -> Chế tạo đồ (Craft đồ)\n"
            "    - 附魔 -> Phù phép (Ép ngọc tăng sức mạnh)\n"
            "    - 极限生存 / 极限模式 -> Sinh tồn Hardcore (Chỉ có đúng 1 mạng duy nhất)\n"
            "    - 生存模式 / 创造模式 -> Chế độ Sinh tồn / Sáng tạo\n"
            "    - 落地水 -> Pha cứu mạng bằng xô nước (MLG Water drop clutch)\n"
            "    - 跑酷 -> Nhảy Parkour điêu luyện\n"
            "    - 陷阱 -> Bẫy / Cạm bẫy troll\n"
            "    - 刷怪笼 / 刷怪塔 -> Lồng quái / Tháp farm đồ tự động\n"
            "    - 模组 -> Bản Mod mở rộng\n\n"
            "3. YÊU CẦU ĐỘ DÀI CÂU DỊCH:\n"
            "- Câu dịch phải súc tích, ngắt câu nhịp nhàng, không quá dài dòng để giọng đọc AI CapCut TTS đọc kịp video và trẻ em đọc phụ đề dễ dàng."
        )
    },
    "gaming_general": {
        "id": "gaming_general",
        "name": "🕹️ Game & Esports Tổng Hợp (Kịch tính, hài hước)",
        "description": "Dành cho video game tổng hợp, liên quân, roblox, free fire, esports.",
        "prompt_context": (
            "CHỦ ĐỀ: Video Game / Trò chơi điện tử. Giọng điệu hào hứng, kịch tính, dùng thuật ngữ game quen thuộc (combat, gank, leo rank, gánh team, outplay, boss, farm đồ). Xưng hô 'mình/các bạn'."
        )
    },
    "comedy_entertainment": {
        "id": "comedy_entertainment",
        "name": "✨ Hài Hước / Giải Trí Đời Sống (Tự nhiên, dí dỏm)",
        "description": "Dành cho video hài Douyin, đời sống thường ngày, bắt trend.",
        "prompt_context": (
            "CHỦ ĐỀ: Giải trí, hài hước đời sống. Văn phong gần gũi, dí dỏm, bắt trend tự nhiên, mượt mà, thuần phong mỹ tục tiếng Việt."
        )
    },
    "general": {
        "id": "general",
        "name": "🌐 Đa Dụng / Tiêu Chuẩn (Chuẩn mực, súc tích)",
        "description": "Dịch thuật tổng quát, chuẩn xác và trung thực với nội dung gốc.",
        "prompt_context": (
            "CHỦ ĐỀ: Video đa dụng ngắn. Văn phong tự nhiên, súc tích, chuẩn tiếng Việt hiện đại."
        )
    }
}


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
    
    # Translation Context & Topic (Chủ đề dịch thuật)
    topic_preset: str = "minecraft_kids" # Mặc định chủ đề Minecraft cho trẻ em
    custom_translation_prompt: Optional[str] = None
    
    # Video Processing
    speed_factor: float = 0.70           # Tốc độ làm chậm để AI dịch & đọc tiếng Việt khớp timeline
    final_speed: float = 1.20            # Tốc độ tăng tốc khi render video thành phẩm ở Bước 8 (mặc định 1.2x)
    video_crf: int = 18
    video_preset: str = "medium"
    
    # Audio Settings (AI Vocal Separation & BGM Preservation)
    keep_bgm: bool = True                # Mặc định BẬT tách giọng AI & bảo tồn nhạc nền video gốc
    bgm_volume: float = 1.00             # Giữ nguyên 100% âm lượng nhạc nền gốc
    tts_volume: float = 1.00
    audio_ducking: bool = False
    vocal_model_name: str = "UVR-MDX-NET-Inst_HQ_3"
    separation_speed: str = "turbo"      # "turbo" (0%), "fast" (25%), "balanced" (50%), "hq" (75%)
    
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
