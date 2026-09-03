"""
main.py - Entrypoint for Douyin Video AI Automation Tool (CLI / GUI)
"""

import argparse
import logging
import os
from pathlib import Path
import sys

# Hỗ trợ hiển thị Tiếng Việt trên Windows Terminal / CMD
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.prompt import Prompt

from config import BlurRegion, CookieConfig, PipelineConfig, SubtitleStyle, TTSConfig
from pipeline import DouyinAutoPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
console = Console()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tool tu dong hoa Re-up & Dich thuat Video Douyin sang Tieng Viet bang AI."
    )
    parser.add_argument("-u", "--url", type=str, help="Link video Douyin hoac chuoi chia se.")
    parser.add_argument("--provider", type=str, default="deepseek", choices=["deepseek", "gemini"], help="AI Provider dich thuat (deepseek hoac gemini).")
    parser.add_argument("--topic", type=str, default="minecraft_kids", choices=["minecraft_kids", "gaming_general", "comedy_entertainment", "general"], help="Chu de dich thuat (mac dinh: minecraft_kids).")
    parser.add_argument("-k", "--deepseek-key", type=str, default=os.getenv("DEEPSEEK_API_KEY", "sk-7731fa779b8a46fda7e9e48c46bce715"), help="API Key DeepSeek.")
    parser.add_argument("-m", "--deepseek-model", type=str, default="deepseek-v4-flash", help="Model DeepSeek (mac dinh: deepseek-v4-flash).")
    parser.add_argument("--gui", action="store_true", help="Khoi chay giao dien do hoa (GUI).")
    parser.add_argument("--cookie-str", type=str, help="Chuoi cookie Douyin.")
    parser.add_argument("--cookie-file", type=str, help="Duong dan file cookies.txt.")
    parser.add_argument("--browser", type=str, choices=["edge", "chrome", "brave", "firefox"], help="Lay cookie truc tiep tu trinh duyet.")
    parser.add_argument(
        "--voice",
        type=str,
        default="co-gai-hoat-ngon",
        choices=["co-gai-hoat-ngon", "thanh-nien-tu-tin", "nho-ngot-ngao", "mai-truyen-cam", "nu-pho-thong", "kenny-dai-de", "BV074_streaming", "BV075_streaming"],
        help="Giong doc CapCut (co-gai-hoat-ngon, thanh-nien-tu-tin, nho-ngot-ngao, mai-truyen-cam, nu-pho-thong, kenny-dai-de)."
    )
    parser.add_argument("--speed", type=float, default=0.70, help="Toc do phat lai de AI doc phu de (mac dinh: 0.70x).")
    parser.add_argument("--final-speed", type=float, default=1.20, help="Toc do xuat video hoan thien o Buoc 8 (mac dinh: 1.20x).")
    parser.add_argument("--whisper-model", type=str, default="small", choices=["tiny", "base", "small", "medium", "large-v3"], help="Mo hinh Whisper STT.")
    parser.add_argument(
        "--sub-style",
        type=str,
        default="badge_white_on_black",
        choices=["none", "capcut_default", "white_thick_black", "white_soft_shadow", "tiktok_yellow_black", "red_white_outline", "orange_white_outline", "blue_white_outline", "green_black_outline", "badge_black_on_white", "badge_white_on_black", "badge_black_on_yellow", "badge_white_on_purple", "cyan_neon_outline", "glitch_3d_shadow", "neon_glow_pink", "neon_glow_yellow", "neon_glow_green"],
        help="Mau chu phu de CapCut (badge_white_on_black, capcut_default, tiktok_yellow_black, badge_black_on_yellow, neon_glow_pink, ...)."
    )
    parser.add_argument("--font-size", type=int, default=18, help="Kich thuoc chu phu de.")
    parser.add_argument("--font-name", type=str, default="Montserrat", help="Ten font chu.")
    parser.add_argument("--margin-v", type=int, default=45, help="Khoang cach phu de tu mep duoi (pixel, mac dinh: 45).")
    parser.add_argument("--alignment", type=int, default=2, choices=[1, 2, 3, 4, 5, 6, 7, 8, 9], help="Vi tri can le phu de ASS (2 = Bottom-Center, 5 = Mid-Center, 8 = Top-Center).")
    parser.add_argument("--no-bgm", action="store_true", help="Tat nhac nen (chi giu lai giong doc TTS).")
    parser.add_argument("--bgm-volume", type=float, default=1.0, help="Am luong nhac nen BGM goc (mac dinh: 1.0 = 100%%).")
    parser.add_argument("--separation-speed", type=str, default="turbo", choices=["turbo", "fast", "balanced", "hq"], help="Toc do tach AI MDX-Net (mac dinh: turbo).")
    parser.add_argument("--check-api", action="store_true", help="Kiem tra trang thai va Rate Limit cua AI API Key.")
    parser.add_argument("--blur-y-ratio", type=float, default=0.72, help="Toa do Y bat dau lam mo (ty le 0.0-1.0).")
    parser.add_argument("--blur-height-ratio", type=float, default=0.18, help="Chieu cao vung lam mo (ty le 0.0-1.0).")
    parser.add_argument("--no-smart-blur", action="store_true", help="Tat lam mo thong minh (luon lam mo toan bo video).")
    parser.add_argument("--blur-pad-before", type=float, default=0.15, help="Dem thoi gian truoc cau thoai (giay, mac dinh: 0.15).")
    parser.add_argument("--blur-pad-after", type=float, default=0.20, help="Dem thoi gian sau cau thoai (giay, mac dinh: 0.20).")
    parser.add_argument("--blur-gap-merge", type=float, default=0.50, help="Gop khoang cach nho hon nguong nay de chong nhap nhay (giay, mac dinh: 0.50).")
    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.check_api:
        key = args.deepseek_key
        if not key:
            key = Prompt.ask("[bold cyan]👉 Nhập DeepSeek API Key để kiểm tra[/bold cyan]", password=True)
        from translator import check_deepseek_api_status
        console.print("[bold cyan]🔍 Đang kiểm tra trạng thái và Rate Limit từng model DeepSeek...[/bold cyan]")
        res = check_deepseek_api_status(key, args.deepseek_model)

        console.print(f"\n[bold]{res.get('message')}[/bold]\n")
        for m, info in res.get("model_results", {}).items():
            color = "green" if info.get("code") == 200 else ("yellow" if info.get("code") == 429 else "red")
            console.print(f"  • [{color}]{m}[/{color}]: {info.get('msg')} (Latency: {info.get('latency_ms', 0)}ms)")
        return

    if args.gui or len(sys.argv) == 1:
        try:
            from app_gui import DouyinEditorApp
            app = DouyinEditorApp()
            app.mainloop()
            return
        except Exception as e:
            console.print(f"[bold red]Không thể mở GUI ({e}), chuyển sang chế độ dòng lệnh...[/bold red]")

    url = args.url
    if not url:
        console.print("[bold yellow]🎬 Chào mừng bạn đến với Douyin Video AI Automation Tool![/bold yellow]\n")
        url = Prompt.ask("[bold cyan]👉 Vui lòng dán link video Douyin (hoặc chuỗi chia sẻ)[/bold cyan]")

    if not url:
        console.print("[bold red]Lỗi: Bạn chưa cung cấp link video![/bold red]")
        sys.exit(1)

    deepseek_key = args.deepseek_key
    if not deepseek_key:
        deepseek_key = Prompt.ask("[bold cyan]👉 Nhập DeepSeek API Key[/bold cyan]", password=True)
        if not deepseek_key:
            console.print("[bold red]Lỗi: Bắt buộc phải có DeepSeek API Key![/bold red]")
            sys.exit(1)

    cookie_cfg = CookieConfig(
        cookie_str=args.cookie_str,
        cookie_file=Path(args.cookie_file) if args.cookie_file else None,
        browser_name=args.browser
    )

    import copy
    from config import SUBTITLE_PRESETS
    sub_preset = SUBTITLE_PRESETS.get(args.sub_style, SUBTITLE_PRESETS["badge_white_on_black"])
    sub_style = copy.copy(sub_preset["style"])
    sub_style.font_name = args.font_name
    sub_style.font_size = args.font_size
    sub_style.margin_v = args.margin_v
    sub_style.alignment = args.alignment

    config = PipelineConfig(
        llm_provider="deepseek",
        deepseek_api_key=deepseek_key,
        deepseek_model_name=args.deepseek_model,
        whisper_model_size=args.whisper_model,
        topic_preset=args.topic,
        speed_factor=args.speed,
        final_speed=args.final_speed,
        keep_bgm=not args.no_bgm,
        bgm_volume=args.bgm_volume,
        separation_speed=args.separation_speed,
        cookie_config=cookie_cfg,
        blur_region=BlurRegion(
            y_ratio=args.blur_y_ratio,
            height_ratio=args.blur_height_ratio,
            blur_power=15,
            enabled=True,
            smart_blur=not args.no_smart_blur,
            pad_before=args.blur_pad_before,
            pad_after=args.blur_pad_after,
            min_gap_merge=args.blur_gap_merge
        ),
        subtitle_style=sub_style,
        tts_config=TTSConfig(
            voice="BV075_streaming" if args.voice in ("thanh-nien-tu-tin", "BV075_streaming") else (
                "BV421_vivn_streaming" if args.voice == "nho-ngot-ngao" else (
                    "BV562_streaming" if args.voice == "mai-truyen-cam" else (
                        "vi_female_huong" if args.voice == "nu-pho-thong" else (
                            "BV075_streaming_demon_dsp" if args.voice == "kenny-dai-de" else "BV074_streaming"
                        )
                    )
                )
            ),
            resource_id="7102355709945188866" if args.voice in ("thanh-nien-tu-tin", "BV075_streaming") else (
                "7252594014782755330" if args.voice == "nho-ngot-ngao" else (
                    "7483736254694035984" if args.voice == "mai-truyen-cam" else (
                        "7264854897953083905" if args.voice == "nu-pho-thong" else (
                            "7569442422665661712" if args.voice == "kenny-dai-de" else "7102355709945188865"
                        )
                    )
                )
            ),
            rate="1.0",
            preset_name=args.voice
        )
    )

    pipeline = DouyinAutoPipeline(config=config)
    try:
        final_video_path = pipeline.run(url)
        console.print(f"\n[bold green]✨ Video đã được lưu tại:[/bold green] [underline]{final_video_path}[/underline]\n")
    except Exception as e:
        console.print(f"\n[bold red]Quy trình kết thúc với lỗi: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
