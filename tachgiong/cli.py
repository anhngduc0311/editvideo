"""
Command-Line Interface (CLI) for AI Vocal & Instrumental Separator.
Enhanced with Multi-Threading, Batch Processing & Concurrent File Workers.
"""

import os
import sys
import argparse
import time
from typing import List

# Fix UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from engine import (
    process_files_concurrent,
    get_optimal_cpu_threads,
    MODELS_DATA,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS
)


def get_all_media_files(path: str) -> List[str]:
    """Recursively or directly collect media files from path."""
    valid_exts = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
    if os.path.isfile(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in valid_exts:
            return [os.path.abspath(path)]
        else:
            return []

    media_files = []
    for root, _, files in os.walk(path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                media_files.append(os.path.abspath(os.path.join(root, f)))
    return sorted(media_files)


def main():
    cpu_cores = os.cpu_count() or 4
    parser = argparse.ArgumentParser(
        description="🎵 Công cụ AI Tách Giọng Nói & Tách Nhạc Nền Đa Luồng (UVR MDX-Net Engine Turbo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Ví dụ sử dụng:
  python cli.py -i baihat.mp3 -o output/ --speed turbo --mode instrumental
  python cli.py -i C:/music_folder/ -o output/ --mode both -t 2 --speed fast
  python cli.py -i video.mp4 -o output/ --mode video_replace
        """
    )

    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Đường dẫn file âm thanh/video nguồn hoặc thư mục chứa các file"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Thư mục lưu kết quả xuất ra (mặc định: ./output)"
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["instrumental", "vocals", "both", "video_replace"],
        default="both",
        help="Chế độ tách: 'instrumental' (nhạc nền), 'vocals' (giọng nói), 'both' (cả hai), 'video_replace' (video không lời)"
    )
    parser.add_argument(
        "--model",
        choices=list(MODELS_DATA.keys()),
        default="UVR-MDX-NET-Inst_HQ_3",
        help="Mô hình AI sử dụng (mặc định: UVR-MDX-NET-Inst_HQ_3)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["mp3", "wav", "flac", "m4a"],
        default="mp3",
        help="Định dạng âm thanh xuất ra (mặc định: mp3)"
    )
    parser.add_argument(
        "-b", "--bitrate",
        default="320k",
        help="Chất lượng bitrate cho MP3/M4A (mặc định: 320k)"
    )
    parser.add_argument(
        "-s", "--speed",
        choices=["turbo", "fast", "balanced", "hq"],
        default=None,
        help="Chế độ tốc độ: 'turbo' (nhanh nhất 0%% overlap), 'fast' (25%% overlap), 'balanced' (50%% overlap), 'hq' (75%% overlap)"
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=None,
        choices=[0.0, 0.25, 0.5, 0.75],
        help="Tỉ lệ gối đầu Overlap (0.0: Siêu tốc 2.5x, 0.25: rất nhanh, 0.5: chuẩn, 0.75: chất lượng cao)"
    )
    parser.add_argument(
        "-t", "--threads", "--workers",
        dest="workers",
        type=int,
        default=2,
        help=f"Số luồng xử lý song song nhiều file cùng lúc (mặc định: 2, tối đa: {cpu_cores})"
    )
    parser.add_argument(
        "-B", "--batch-size",
        dest="batch_size",
        type=int,
        default=1,
        choices=[1, 2, 4],
        help="Kích thước batch chunk cho AI inference (1: tối ưu tốc độ CPU, 2: nhanh, 4: rất nhanh)"
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=None,
        help="Số luồng CPU gán cho mỗi session AI (mặc định: tự động tối ưu hóa)"
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Lỗi: Không tìm thấy đường dẫn đầu vào: {args.input}")
        sys.exit(1)

    files_to_process = get_all_media_files(args.input)
    if not files_to_process:
        print(f"❌ Không tìm thấy file âm thanh hoặc video nào hợp lệ trong: {args.input}")
        sys.exit(1)

    # Determine overlap from speed preset or overlap argument
    if args.overlap is not None:
        overlap = args.overlap
    elif args.speed == "turbo":
        overlap = 0.0
    elif args.speed == "fast":
        overlap = 0.25
    elif args.speed == "hq":
        overlap = 0.75
    elif args.speed == "balanced":
        overlap = 0.5
    else:
        overlap = 0.0  # Default to Turbo mode for instant high-speed performance

    workers = max(1, min(args.workers, len(files_to_process)))
    cpu_threads = args.cpu_threads or get_optimal_cpu_threads(workers=workers)

    speed_desc = {0.0: "Siêu Tốc (Turbo 0% Overlap)", 0.25: "Nhanh (Fast 25% Overlap)", 0.5: "Cân Bằng (50% Overlap)", 0.75: "Chất Lượng Cao (75% Overlap)"}.get(overlap, f"{overlap*100}%")

    print("=" * 68)
    print("🎵 CÔNG CỤ TÁCH GIỌNG NÓI VÀ NHẠC NỀN AI (MDX-NET TURBO ENGINE)")
    print("=" * 68)
    print(f"📁 Tổng số file cần xử lý: {len(files_to_process)}")
    print(f"🚀 Chế độ Tốc độ: {speed_desc}")
    print(f"⚡ Số file xử lý đồng thời (Workers): {workers}")
    print(f"📦 Kích thước Batch AI: {args.batch_size}")
    print(f"💻 Luồng CPU mỗi Worker: {cpu_threads} (Đã tối ưu)")
    print(f"🎯 Chế độ: {args.mode.upper()}")
    print(f"🧠 Mô hình AI: {args.model}")
    print(f"💾 Định dạng xuất: {args.format.upper()} ({args.bitrate})")
    print(f"📂 Thư mục xuất: {os.path.abspath(args.output)}")
    print("=" * 68)

    total_start = time.time()

    def print_log(msg: str):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")

    success_count, results, errors = process_files_concurrent(
        files=files_to_process,
        output_dir=args.output,
        mode=args.mode,
        model_key=args.model,
        audio_format=args.format,
        bitrate=args.bitrate,
        overlap=overlap,
        batch_size=args.batch_size,
        max_workers=workers,
        cpu_threads_per_worker=cpu_threads,
        log_callback=print_log
    )

    total_time = time.time() - total_start
    print("\n" + "=" * 68)
    print(f"🎉 HOÀN THÀNH TẤT CẢ! Thành công: {success_count}/{len(files_to_process)} file trong {total_time:.1f} giây.")
    if errors:
        print(f"⚠️ Có {len(errors)} file gặp lỗi:")
        for err_file, err_msg in errors:
            print(f"   - {os.path.basename(err_file)}: {err_msg}")
    print(f"📂 Thư mục kết quả: {os.path.abspath(args.output)}")
    print("=" * 68)


if __name__ == "__main__":
    main()
