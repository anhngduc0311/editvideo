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
    x: Optional[int] = 293       # Tọa độ X (pixel) - mặc định: 293
    y: Optional[int] = 517       # Tọa độ Y (pixel) - mặc định: 517
    width: Optional[int] = 683   # Chiều rộng vùng mờ - mặc định: 683
    height: Optional[int] = 50   # Chiều cao vùng mờ - mặc định: 50
    
    # Tỷ lệ mặc định theo kích thước video (nếu không set pixel cứng)
    y_ratio: float = 0.718        # Vị trí bắt đầu mờ từ 71.8% chiều cao video
    height_ratio: float = 0.0694  # Chiều cao vùng mờ chiếm 6.94% (~50/720)
    blur_power: int = 15          # Độ mờ của filter boxblur (lpower:rpower)
    enabled: bool = True
    smart_blur: bool = True       # Làm mờ thông minh: chỉ mờ khi có phụ đề tiếng Trung, tự ẩn khi không có
    pad_before: float = 0.15      # Đệm thời gian trước câu nói (giây) để đảm bảo không lọt phụ đề tiếng Trung
    pad_after: float = 0.20       # Đệm thời gian sau câu nói (giây) để đảm bảo không lọt phụ đề tiếng Trung
    min_gap_merge: float = 0.50   # Nối liền 2 khoảng mờ nếu cách nhau dưới 0.5s để chống nhấp nháy



@dataclass
class SubtitleStyle:
    """
    Cấu hình hiển thị phụ đề tiếng Việt khi Hardcode (Burn-in) vào video.
    Màu sắc theo định dạng ASS (&H<Alpha><Blue><Green><Red> hoặc Hex).
    """
    preset_id: str = "badge_white_on_black"
    name: str = "Chữ trắng hộp đen"
    font_name: str = "Montserrat"
    font_size: int = 22
    primary_color: str = "&H00FFFFFF"    # Chữ trắng (ABGR)
    outline_color: str = "&H00000000"    # Viền đen
    back_color: str = "&H00000000"       # Hộp đen (100% opacity)
    outline_width: float = 4.5           # Độ dày hộp badge
    shadow: float = 0                    # Đổ bóng
    margin_v: int = 161                  # Khoảng cách từ mép dưới màn hình (pixel, mặc định: 160)
    bold: int = 1                        # In đậm (1 = True, 0 = False)
    alignment: int = 2                   # Căn giữa dưới cùng (ASS standard = 2)
    border_style: int = 3                # 1 = Viền & Đổ bóng, 3 = Hộp chữ nhật (Badge)


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
        "name": "Chữ trắng hộp đen (Georgia Serif)",
        "preview_text": "Aa",
        "fg_color": "#ffffff",
        "bg_color": "#000000",
        "border_color": "#e5e7eb",
        "style": SubtitleStyle(
            preset_id="badge_white_on_black",
            name="Chữ trắng hộp đen (Georgia Serif)",
            font_name="Georgia",
            font_size=26,
            primary_color="&H00FFFFFF",  # Trắng
            outline_color="&H00000000",
            back_color="&H00000000",     # Hộp đen
            outline_width=4.5,
            shadow=0,
            bold=1,
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
    "minecraft_100_days_hardcore": {
        "id": "minecraft_100_days_hardcore",
        "name": "🔥 Minecraft 100 Ngày Hardcore (Cực kịch tính, 1 mạng duy nhất)",
        "description": "Chuyên biệt cho series Thử Thách 100 Ngày Hardcore. Nhấn mạnh sự sống còn, nhịp độ dồn dập, thuật ngữ timeline 100 ngày, kịch tính từng giây.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: THỬ THÁCH SINH TỒN 100 NGÀY HARDCORE TRONG MINECRAFT (100 DAYS HARDCORE MINECRAFT CHALLENGE).\n\n"
            "1. TÍNH CHẤT BỐI CẢNH & NGHỆ THUẬT BIÊN KỊCH CỐT TRUYỆN:\n"
            "- Chế độ Hardcore chỉ có DUY NHẤT 1 MẠNG. Chết là thế giới bị xóa vĩnh viễn, mất trắng toàn bộ công sức.\n"
            "- Giọng điệu: Hồi hộp, kịch tính, dồn dập, căng thẳng, tràn đầy năng lượng, cuốn hút như một bộ phim sinh tồn nghẹt thở.\n"
            "- Hook mở màn (3s đầu): Phải kích thích tò mò và đẩy cao trào ngay lập tức ('Liệu mình có thể sống sót qua 100 ngày địa ngục này không? Hãy cùng xem nhé!').\n"
            "- Xưng hô chuẩn streamer sinh tồn: 'mình / các bạn' hoặc 'tôi / anh em', tạo cảm giác phiêu lưu và gắn kết.\n"
            "- Nhấn mạnh các mốc thời gian sống còn: 'Ngày 1...', 'Ngày thứ 10...', 'Ngày 50...', 'Đến ngày 100...'.\n\n"
            "2. BỘ TỪ ĐIỂN THUẬT NGỮ CHUYÊN SÂU CHO MINECRAFT 100 NGÀY HARDCORE:\n"
            "  • Mốc thời gian & Chế độ chơi:\n"
            "    - 第1天 / 第X天 / 第100天 -> Ngày 1 / Ngày thứ X / Ngày thứ 100\n"
            "    - 极限模式 / 极限生存 / 硬核模式 -> Chế độ Hardcore / Sinh tồn Hardcore (1 mạng duy nhất)\n"
            "    - 一命通关 -> Phá đảo 1 mạng duy nhất\n"
            "    - 毕业 / 毕业套 -> Tốt nghiệp / Đạt full bộ trang bị cuối (Max Option)\n"
            "    - 锁血 / 残血 / 丝血 -> Hút chết / Còn đúng nửa tim / Máu đỏ nguy kịch\n"
            "    - 暴毙 / 翻车 -> Bay màu / Toang đời / Hẹo lãng xẹt\n"
            "    - 落地水 -> Pha tiếp đất bằng xô nước cứu mạng (MLG Water drop clutch)\n\n"
            "  • Quái vật, Trùm & Mối đe dọa sinh tử:\n"
            "    - 监守者 / 潜声守卫 -> Quái vật Warden (Quái bóng tối one-hit)\n"
            "    - 凋灵 -> Trùm Wither (Wither 3 đầu)\n"
            "    - 末影龙 -> Rồng Ender (Ender Dragon - Boss cuối The End)\n"
            "    - 苦力怕 / 爬行者 / 高压苦力怕 -> Creeper (Quái nổ) / Creeper tích điện (Siêu quái nổ)\n"
            "    - 末影人 / 小黑 -> Enderman\n"
            "    - 烈焰人 -> Quái lửa Blaze\n"
            "    - 凋灵骷髅 -> Skeleton Wither (Bộ xương đen địa ngục)\n"
            "    - 猪灵 / 猪灵蛮兵 -> Piglin / Piglin Brute (Chiến binh heo cực trâu)\n"
            "    - 劫掠 / 突袭 / 灾厄村民 -> Cuộc đột kích Raid / Kẻ cướp Pillager\n"
            "    - 潜影贝 -> Quái Shulker (Bắn bay lên trời)\n"
            "    - 溺尸 (带三叉戟) -> Drowned cầm Đinh ba (Zombie phóng lao)\n\n"
            "  • Trang bị, Bùa hộ mệnh & Vật phẩm tối thượng:\n"
            "    - 不死图腾 / 图腾 -> Totem bất tử (Bùa hộ mệnh cứu sống)\n"
            "    - 附魔金苹果 / 附魔金头 -> Táo vàng phù phép / Táo Notch thần thánh\n"
            "    - 下界合金 / 狱髓 -> Netherite / Hợp kim Netherite\n"
            "    - 鞘翅 -> Cánh cứng Elytra\n"
            "    - 潜影盒 / 潜影箱 -> Hộp Shulker (Túi thần kỳ mang cả thế giới)\n"
            "    - 信标 -> Đèn Hải đăng Beacon (Tăng tốc độ đào và hồi máu)\n"
            "    - 经验修补 -> Bùa Tu sửa Mending (Dùng EXP sửa đồ)\n"
            "    - 保护IV / 锋利V / 效率V -> Bảo vệ 4 / Sắc bén 5 / Hiệu suất 5\n"
            "    - 药水 / 抗火药水 / 力量药水 -> Thuốc kháng lửa / Thuốc tăng lực\n"
            "    - 末影珍珠 / 瞬移 -> Ngọc Ender (Dịch chuyển tức thời thoát chết)\n\n"
            "  • Công trình, Chiều không gian & Hệ thống Farm:\n"
            "    - 主世界 / 下界 (地狱) / 末地 -> Overworld (Thế giới thực) / Nether (Địa ngục) / The End (Vùng đất Ender)\n"
            "    - 堡垒遗迹 / 猪灵堡垒 -> Pháo đài Bastion (Căn cứ Piglin)\n"
            "    - 下界要塞 -> Pháo đài Nether\n"
            "    - 末地城 / 末地船 -> Thành phố Ender / Tàu Ender\n"
            "    - 古代城市 / 深暗之域 -> Thành phố cổ Ancient City (Lãnh địa Warden)\n"
            "    - 刷怪塔 / 刷铁机 / 刷金塔 / 突袭塔 -> Tháp farm quái / Máy farm sắt / Farm vàng / Tháp farm Raid\n"
            "    - 庇护所 / 基地 -> Căn cứ trú ẩn / Siêu căn cứ Mega Base"
        )
    },
    "minecraft_kids": {
        "id": "minecraft_kids",
        "name": "🎮 Minecraft Phiêu Lưu & Troll Bựa Thiếu Nhi (Vui nhộn, chuẩn gamer nhí)",
        "description": "Tối ưu ngữ cảnh Minecraft thiếu nhi, xưng hô 'mình/các bạn', từ vựng chuẩn gamer Việt, hài hước, giàu cảm xúc.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: Video Minecraft giải trí, phiêu lưu, troll bựa dành cho THIẾU NHI & GAME THỦ TRẺ TUỔI.\n\n"
            "1. PHONG CÁCH KỂ CHUYỆN & DẪN DẮT:\n"
            "- Giọng điệu: Hào hứng, vui tươi, nhí nhảnh, giàu cảm xúc, troll hài hước ('Ui là trời!', 'Xem chuyện gì xảy ra này!', 'Phen này toang thật rồi!').\n"
            "- Xưng hô thân thiện: 'mình / các bạn' hoặc 'anh / các em', tạo không khí gần gũi như một người bạn đồng hành.\n"
            "- Câu từ trong sáng, dễ hiểu, nhịp điệu rộn ràng, kích thích trí tò mò của trẻ em.\n\n"
            "2. BỘ TỪ ĐIỂN THUẬT NGỮ CHUẨN GAMER VIỆT:\n"
            "  • Quái vật: 苦力怕 -> Creeper (quái nổ), 僵尸 -> Zombie, 骷髅 -> Skeleton, 末影人 -> Enderman, 监守者 -> Quái Warden, 铁傀儡 -> Golem sắt, 凋灵 -> Boss Wither, 史莱姆 -> Cục Slime dính.\n"
            "  • Vật phẩm: 钻石 -> Kim cương, 下界合金 -> Netherite xịn nhất, 黑曜石 -> Đá Obsidian, 红石 -> Đá đỏ, 不死图腾 -> Bùa bất tử, 鞘翅 -> Cánh Elytra, 附魔金苹果 -> Táo Notch thần thánh.\n"
            "  • Hành động: 挖矿 -> Đi đào khoáng sản, 合成 -> Chế tạo đồ (Craft), 附魔 -> Phù phép nâng cấp, 落地水 -> Pha xô nước cứu mạng MLG, 跑酷 -> Nhảy Parkour đỉnh cao, 模组 -> Bản Mod siêu vui."
        )
    },
    "movie_anime_recap": {
        "id": "movie_anime_recap",
        "name": "🎬 Tóm Tắt & Review Phim / Hoạt Hình / Anime (Cuốn hút, giữ chân người xem)",
        "description": "Chuyên biệt cho video tóm tắt phim, review anime, truyện tranh manga/manhwa. Kể chuyện kịch tính, dẫn dắt cao trào và cú twist bất ngờ.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: REVIEW PHIM, TÓM TẮT PHIM ĐIỆN ẢNH, ANIME & TRUYỆN TRANH (MOVIE / ANIME RECAP).\n\n"
            "1. NGHỆ THUẬT BIÊN KỊCH REVIEW PHIM VIRAL GIỮ CHÂN NGƯỜI XEM:\n"
            "- Giọng điệu: Hấp dẫn, bí ẩn, lôi cuốn, giọng kể chuyện truyền cảm (Storytelling Voiceover) như các kênh Review Phim triệu view.\n"
            "- Hook 3 giây đầu: Đặt ra tình huống nghẹt thở hoặc câu hỏi bí ẩn ('Người đàn ông này không ngờ rằng...', 'Chỉ vì một quyết định sai lầm, cả gia đình đã...', 'Một thế giới nơi kẻ yếu bị đào thải...').\n"
            "- Xưng hô ngôi thứ 3 khách quan nhưng lôi cuốn: 'Anh ta / Cô ấy / Hắn / Cậu bé / Ông lão / Nhân vật chính / Tên trùm', người kể ẩn hoặc dùng 'chúng ta'.\n"
            "- Mạch kể liền mạch & chuyển cảnh mượt mà: Dùng liên từ tự nhiên ('Ngay sau đó...', 'Đúng lúc này...', 'Không ngờ rằng...', 'Hóa ra là...', 'Một sự thật kinh hoàng dần hé lộ...').\n"
            "- Đẩy cao trào (Climax) & Cú twist (Plot Twist): Tăng cường các tính từ và động từ biểu cảm mạnh mẽ khi nhân vật phản đòn hoặc gặp biến cố ('lật kèo ngoạn mục', 'sụp đổ hoàn toàn', 'bừng tỉnh sức mạnh').\n\n"
            "2. BỘ TỪ ĐIỂN CHUYỂN NGỮ ĐIỆN ẢNH & ANIME:\n"
            "  • 逆袭 / 绝地反击 -> Màn lội ngược dòng ngoạn mục / Màn trả thù mãn nhãn\n"
            "  • 反转 / 大反转 -> Cú twist bất ngờ / Pha quay xe không ai lường trước\n"
            "  • 开挂 / 主角光环 -> Hào quang nhân vật chính / Bật mode sức mạnh bá đạo\n"
            "  • 幕后黑手 -> Kẻ giật dây trong bóng tối / Trùm cuối giấu mặt\n"
            "  • 危机时刻 / 命悬一线 -> Thời khắc ngàn cân treo sợi tóc / Giữa ranh giới sinh tử\n"
            "  • 打脸 -> Màn vả mặt thích đáng / Khiến đối thủ bẽ bàng"
        )
    },
    "comedy_drama_trend": {
        "id": "comedy_drama_trend",
        "name": "🎭 Drama / Kể Chuyện Cuộc Sống / Bắt Trend Douyin (Dí dỏm, viral cực mạnh)",
        "description": "Dành cho video hài Douyin, đời sống thường ngày, drama bóc phốt, tình huống oái oăm, bắt trend giới trẻ cực mượt.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: HÀI HƯỚC, DRAMA ĐỜI SỐNG, TÌNH HUỐNG HÀI HƯỚC DOUYIN & BẮT TREND TIKTOK.\n\n"
            "1. PHONG CÁCH DIỄN ĐẠT DÍ DỎM & VIRAL:\n"
            "- Giọng điệu: Hài hước, châm biếm nhẹ nhàng, cà khịa duyên dáng, tràn đầy năng lượng tươi vui.\n"
            "- Ngôn từ bắt trend: Chuyển hóa sáng tạo ngôn ngữ mạng Trung Quốc sang các câu nói trend cực chất của giới trẻ Việt Nam ('quay xe cực gắt', 'bất ngờ chưa bà già', 'pha xử lý đi vào lòng đất', 'cười xỉu', 'cay cú', 'đúng là không thể tin nổi').\n"
            "- Xưng hô gần gũi: 'anh chàng này / cô nàng này / anh bạn thân / thánh này' hoặc 'tôi / anh em'.\n\n"
            "2. BỘ TỪ ĐIỂN TIẾNG LÓNG DOUYIN -> VIỆT NAM CHUẨN TREND:\n"
            "  • 绝了 / 离谱 / 逆天 -> Ảo thật đấy / Quá là vô lý / Khó đỡ thật sự\n"
            "  • 翻车 / 打脸 -> Pha xử lý đi vào lòng đất / Tự vả cực đau / Toang toàn tập\n"
            "  • 大冤种 -> Kẻ chịu trận cay đắng / Nạn nhân xấu số\n"
            "  • 塑料姐妹花 / 损友 -> Bạn thân chí cốt chuyên hãm hại / Tình anh em cây khế\n"
            "  • 社死 / 尴尬 -> Tình huống quê độ muốn đào lỗ chui xuống / Quê xệ\n"
            "  • 秀操作 -> Thể hiện kỹ năng đỉnh cao / Màn flexing siêu đẳng\n"
            "  • 老铁 / 家人们 -> Anh em ơi / Cả nhà ơi"
        )
    },
    "gaming_esports": {
        "id": "gaming_esports",
        "name": "🕹️ Game & Esports Tổng Hợp (Liên Quân, Roblox, Free Fire, Highlight đỉnh cao)",
        "description": "Dành cho video game tổng hợp, liên quân, roblox, free fire, highlight, montage. Sôi động, nhiệt huyết, thuật ngữ gaming chuẩn.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: GAME HIGHLIGHT, ESPORTS & TRÒ CHƠI ĐIỆN TỬ TỔNG HỢP (LIÊN QUÂN, ROBLOX, FREE FIRE, LMHT).\n\n"
            "1. PHONG CÁCH BÌNH LUẬN VIÊN & STREAMER NHIỆT HUYẾT:\n"
            "- Giọng điệu: Dồn dập, bùng nổ, hưng phấn, kịch tính theo từng pha combat và tình huống xử lý.\n"
            "- Xưng hô: 'mình / các bạn' hoặc 'tôi / anh em', mang tính đồng hành và cổ vũ.\n"
            "- Nhịp điệu ngắn gọn, sắc sảo, dùng từ ngữ hành động trực diện để giọng đọc AI bắt kịp tốc độ giao tranh trong video.\n\n"
            "2. BỘ TỪ ĐIỂN GAMING CHUẨN ESPORTS VIỆT:\n"
            "  • 秀操作 / 神操作 -> Pha xử lý 200 IQ / Highlight outplay cực đỉnh\n"
            "  • 逆风翻盘 -> Lật kèo phút chót / Cú lội ngược dòng không tưởng\n"
            "  • 偷家 / 偷塔 -> Đẩy lén trộm nhà chính / Cú backdoor thần sầu\n"
            "  • 秒杀 / 瞬秒 -> Bốc hơi trong một nốt nhạc / One-shot đối thủ\n"
            "  • 团灭 -> Quét sạch toàn bộ đội hình (Ace / Wipe out)\n"
            "  • 抓人 / 游走 -> Đi gank bắt lẻ / Đảo đường hỗ trợ đồng đội\n"
            "  • 坑队友 / 搞心态 -> Bóp đồng đội / Pha xử lý tấu hài"
        )
    },
    "horror_mystery_investigation": {
        "id": "horror_mystery_investigation",
        "name": "🕵️ Kinh Dị / Trinh Thám / Bí Ẩn Rùng Rợn / Kỳ Án (Hồi hộp, nghẹt thở)",
        "description": "Dành cho video kể chuyện kinh dị, trinh thám phá án, creepypasta, hiện tượng siêu nhiên. U ám, hồi hộp, giật gân, cuốn hút từng chi tiết.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: KỂ CHUYỆN KINH DỊ, TRINH THÁM PHÁ ÁN, GIẢI MÃ BÍ ẨN & KỲ ÁN (HORROR / MYSTERY STORYTELLING).\n\n"
            "1. NGHỆ THUẬT KỂ CHUYỆN BÍ ẨN NGHẸT THỞ:\n"
            "- Giọng điệu: Trầm lắng, u ám, hồi hộp, lạnh gáy, kích thích tò mò tột độ của người xem.\n"
            "- Hook mở màn: Khơi gợi nỗi sợ hãi hoặc sự bí ẩn không lời giải ('Địa điểm bị nguyền rủa này ẩn chứa điều gì?', 'Căn phòng số 404 và vụ biến mất bí ẩn...').\n"
            "- Xưng hô: Khách quan, dẫn dắt góc nhìn thứ 3 ('nạn nhân / thám tử / người chứng kiến / kẻ tình nghi').\n"
            "- Ngắt câu có chủ đích: Tạo ra các khoảng lặng hồi hộp để giọng đọc AI tạo cảm giác rùng rợn nghẹt thở.\n\n"
            "2. BỘ TỪ ĐIỂN TRINH THÁM & KINH DỊ:\n"
            "  • 悬案 / 诡异事件 -> Kỳ án chưa có lời giải / Hiện tượng kỳ bí rùng mình\n"
            "  • 细思极恐 -> Càng ngẫm càng thấy sợ hãi / Rợn tóc gáy khi nhận ra sự thật\n"
            "  • 蛛丝马迹 -> Những manh mối nhỏ nhất / Dấu vết then chốt\n"
            "  • 真相大白 -> Sự thật kinh hoàng cuối cùng cũng được phơi bày"
        )
    },
    "science_discovery_facts": {
        "id": "science_discovery_facts",
        "name": "💡 Khoa Học / Fact Thú Vị / Khám Phá Kỳ Thú (Tò mò, hấp dẫn)",
        "description": "Dành cho video kiến thức thú vị, giải mã hiện tượng khoa học, thế giới tự nhiên, facts bất ngờ. Lôi cuốn, kích thích tò mò và giàu kiến thức.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: KHÁM PHÁ KHOA HỌC, FACTS KỲ THÚ & THẾ GIỚI TỰ NHIÊN (SCIENCE & CURIOUS FACTS).\n\n"
            "1. PHONG CÁCH DẪN DẮT LÔI CUỐN & KHƠI GỢI TRÍ TÒ MÒ:\n"
            "- Giọng điệu: Hấp dẫn, hào hứng, thuyết phục, dẫn dắt người xem từ bất ngờ này sang kinh ngạc khác.\n"
            "- Hook 3s đầu: Dùng câu hỏi gợi mở hoặc sự thật gây sốc ('Bạn có biết rằng...', 'Tại sao điều này lại xảy ra?', 'Sự thật đằng sau sẽ khiến bạn kinh ngạc!').\n"
            "- Xưng hô: 'chúng ta / các bạn', ngôn ngữ chuẩn mực, khoa học nhưng dễ hiểu, không dùng từ ngữ quá hàn lâm phức tạp.\n\n"
            "2. BỘ TỪ ĐIỂN KHÁM PHÁ TRI THỨC:\n"
            "  • 令人震惊 / 不可思议 -> Sự thật khó tin / Hiện tượng vô cùng kinh ngạc\n"
            "  • 揭秘 / 解密 -> Giải mã bí ẩn / Hé lộ nguyên lý khoa học đằng sau\n"
            "  • 颠覆认知 -> Thay đổi hoàn toàn suy nghĩ của bạn / Phá vỡ mọi định kiến"
        )
    },
    "historical_cultivation": {
        "id": "historical_cultivation",
        "name": "👑 Cổ Trang / Tu Tiên / Kiếm Hiệp Huyền Huyễn (Hào sảng, khí chất)",
        "description": "Dành cho video dã sử, cổ trang, hoạt hình 3D Trung Quốc tu tiên, kiếm hiệp, huyền huyễn. Hào sảng, khí thế, thuật ngữ tu chân chuẩn mực.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH ĐẶC BIỆT: HOẠT HÌNH 3D TU TIÊN, CỔ TRANG, KIẾM HIỆP & HUYỀN HUYỄN TRUNG QUỐC.\n\n"
            "1. PHONG CÁCH HÀO SẢNG & KHÍ THẾ VÕ HIỆP:\n"
            "- Giọng điệu: Hùng hồn, trang trọng, khí chất phi phàm, đậm chất truyện tiên hiệp/kiếm hiệp.\n"
            "- Xưng hô chuẩn mực: 'hắn / nàng / tông chủ / lão tổ / sư phụ / đệ tử / tiểu tử này'.\n"
            "- Dùng các thuật ngữ Hán-Việt quen thuộc của dòng truyện tu tiên để tạo sự quen thuộc và cuốn hút với khán giả mê truyện.\n\n"
            "2. BỘ TỪ ĐIỂN TIÊN HIỆP & CỔ TRANG CHUẨN MỰC:\n"
            "  • 突破境界 / 渡劫 -> Đột phá cảnh giới / Vượt qua lôi kiếp\n"
            "  • 逆天改命 -> Nghịch thiên cải mệnh / Đảo ngược số phận\n"
            "  • 绝世神兵 / 法宝 -> Thần binh tuyệt thế / Pháp bảo thượng cổ\n"
            "  • 宗门大比 -> Đại hội tỷ thí tông môn / Trận chiến đỉnh cao"
        )
    },
    "general_storytelling": {
        "id": "general_storytelling",
        "name": "🌐 Kể Chuyện & Thuyết Minh Viral Tổng Hợp (Dẫn dắt cảm xúc, chuẩn TikTok/Reels)",
        "description": "Văn phong kể chuyện điện ảnh mượt mà, thoát ý, giàu cảm xúc, phù hợp cho mọi thể loại video viral trên mạng xã hội.",
        "prompt_context": (
            "CHỦ ĐỀ & BỐI CẢNH: KỂ CHUYỆN & THUYẾT MINH VIDEO NGẮN VIRAL (TIKTOK / DOUYIN / SHORTS).\n\n"
            "1. PHONG CÁCH BIÊN DỊCH VIRAL NARRATIVE:\n"
            "- Giọng điệu: Truyền cảm, sống động, cuốn hút từ câu đầu tiên đến câu cuối cùng.\n"
            "- Nguyên tắc dịch thoát ý: Không dịch thô từng chữ (word-by-word) mà dịch theo mạch cảm xúc và cốt truyện của người nói.\n"
            "- Câu văn ngắn gọn, giàu hình ảnh, nhịp điệu ngắt nghỉ hoàn hảo cho giọng đọc AI lồng tiếng."
        )
    },
    # Backward compatibility aliases
    "gaming_general": {
        "id": "gaming_general",
        "name": "🕹️ Game & Esports Tổng Hợp (Liên Quân, Roblox, Free Fire, Highlight đỉnh cao)",
        "description": "Dành cho video game tổng hợp, liên quân, roblox, free fire, esports.",
        "prompt_context": "CHỦ ĐỀ: Video Game / Trò chơi điện tử. Giọng điệu hào hứng, kịch tính, dùng thuật ngữ game quen thuộc. Xưng hô 'mình/các bạn'."
    },
    "comedy_entertainment": {
        "id": "comedy_entertainment",
        "name": "🎭 Drama / Kể Chuyện Cuộc Sống / Bắt Trend Douyin (Dí dỏm, viral cực mạnh)",
        "description": "Dành cho video hài Douyin, đời sống thường ngày, bắt trend.",
        "prompt_context": "CHỦ ĐỀ: Giải trí, hài hước đời sống. Văn phong gần gũi, dí dỏm, bắt trend tự nhiên, mượt mà, thuần phong mỹ tục tiếng Việt."
    },
    "general": {
        "id": "general",
        "name": "🌐 Kể Chuyện & Thuyết Minh Viral Tổng Hợp (Dẫn dắt cảm xúc, chuẩn TikTok/Reels)",
        "description": "Dịch thuật tổng quát, chuẩn xác và trung thực với nội dung gốc.",
        "prompt_context": "CHỦ ĐỀ: Video đa dụng ngắn. Văn phong tự nhiên, súc tích, chuẩn tiếng Việt hiện đại."
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
    # API & AI Models (DeepSeek / ChatGPT Cookie / Gemini)
    llm_provider: str = "deepseek"  # "deepseek", "chatgpt_cookie", hoặc "gemini"
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "sk-7731fa779b8a46fda7e9e48c46bce715"))
    deepseek_model_name: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    chatgpt_cookie: str = field(default_factory=lambda: os.getenv("CHATGPT_COOKIE", ""))
    chatgpt_model_name: str = "auto"
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model_name: str = "gemini-3.6-flash"
    whisper_model_size: str = "small"
    whisper_language: str = "zh"
    whisper_server_url: str = field(default_factory=lambda: os.getenv("WHISPER_SERVER_URL", "http://localhost:8888"))
    
    # Batch Chunking & Translation Settings
    chatgpt_batch_size: int = 12         # Kích thước đoạn SRT chia nhỏ tối ưu cho ChatGPT (10-12 câu/đoạn chống lỗi, chuẩn 100%)
    deepseek_batch_size: int = 30        # Kích thước đoạn SRT chia nhỏ cho DeepSeek API (25-30 câu/đoạn)
    
    # Translation Context & Topic (Chủ đề dịch thuật)
    topic_preset: str = "minecraft_kids" # Mặc định chủ đề Minecraft cho trẻ em
    custom_translation_prompt: Optional[str] = None
    
    # Video Processing
    speed_factor: float = 0.70           # Tốc độ làm chậm để AI dịch & đọc tiếng Việt khớp timeline
    final_speed: float = 1.20            # Tốc độ tăng tốc khi render video thành phẩm ở Bước 8 (mặc định 1.2x)
    export_resolution: str = "1080p"     # Độ phân giải xuất: "1080p" (Full HD), "original" (gốc), "720p" (HD), "2k" (2K QHD)
    video_crf: int = 18
    video_preset: str = "ultrafast"
    
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
