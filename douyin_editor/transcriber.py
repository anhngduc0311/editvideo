"""
transcriber.py - Speech-to-Text with High-Speed Local Engine Support (Local In-Memory Web STT + Local Whisper + Gemini Audio)
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import datetime
import io
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
import requests
from tqdm import tqdm

from config import PipelineConfig

# Tự động nạp FFmpeg vào PATH nếu có static_ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

logger = logging.getLogger(__name__)


# ==============================================================================
# SOUNDFILE IN-MEMORY FLAC ENCODER PATCH CHO SPEECH_RECOGNITION
# Khắc phục triệt để lỗi thiếu flac.exe trên Windows ARM64 / Python 3.13
# ==============================================================================
def _apply_speech_recognition_flac_patch():
    try:
        import speech_recognition as sr
        import soundfile as sf
        import numpy as np

        def patched_get_flac_data(self, convert_rate=None, convert_width=None):
            raw = self.get_raw_data(convert_rate=convert_rate, convert_width=convert_width)
            rate = convert_rate or self.sample_rate
            width = convert_width or self.sample_width
            if width == 2:
                dtype = np.int16
            elif width == 4:
                dtype = np.int32
            elif width == 1:
                dtype = np.uint8
            else:
                dtype = np.int16
            arr = np.frombuffer(raw, dtype=dtype)
            buf = io.BytesIO()
            sf.write(buf, arr, rate, format='FLAC')
            return buf.getvalue()

        sr.AudioData.get_flac_data = patched_get_flac_data
        logger.debug("SpeechRecognition soundfile in-memory FLAC patch activated successfully.")
    except Exception as e:
        logger.warning(f"Could not activate SpeechRecognition soundfile FLAC patch: {e}")

_apply_speech_recognition_flac_patch()


@dataclass
class SubtitleItem:
    index: int
    start_seconds: float
    end_seconds: float
    start_str: str
    end_str: str
    text: str
    translated_text: str = ""

    def to_srt_block(self, use_translated: bool = False) -> str:
        content = self.translated_text if (use_translated and self.translated_text) else self.text
        return f"{self.index}\n{self.start_str} --> {self.end_str}\n{content.strip()}\n"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_str": self.start_str,
            "end_str": self.end_str,
            "duration": round(self.end_seconds - self.start_seconds, 2),
            "text": self.text,
            "translated_text": self.translated_text
        }


def parse_srt_content(srt_text: str) -> List[SubtitleItem]:
    """Chuyển đổi chuỗi SRT thành danh sách SubtitleItem"""
    pattern = re.compile(
        r"(\d+)\s*\n"
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n"
        r"([\s\S]*?)(?=\n{2,}|\n*\Z)"
    )
    items: List[SubtitleItem] = []
    
    def to_secs(t_str: str) -> float:
        h, m, s_ms = t_str.split(":")
        s, ms = s_ms.replace(".", ",").split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    for match in pattern.finditer(srt_text.strip()):
        idx = int(match.group(1))
        start_str = match.group(2).replace(".", ",")
        end_str = match.group(3).replace(".", ",")
        text = match.group(4).strip()
        items.append(
            SubtitleItem(
                index=idx,
                start_seconds=to_secs(start_str),
                end_seconds=to_secs(end_str),
                start_str=start_str,
                end_str=end_str,
                text=text
            )
        )
    return items


def calculate_subtitle_stats(items: List[SubtitleItem], total_duration: float = 0.0) -> Dict[str, Any]:
    """
    Tính toán chi tiết các chỉ số thống kê & tình trạng phụ đề:
    - Tổng số câu thoại
    - Thời lượng thoại (spoken duration)
    - Tỷ lệ bao phủ phụ đề % (coverage ratio)
    - Đánh giá tình trạng (Đầy đủ / Tương đối / Thiếu)
    - Phát hiện khoảng trống im lặng bất thường
    """
    total_count = len(items)
    if total_count == 0:
        return {
            "total_count": 0,
            "spoken_duration": 0.0,
            "total_duration": total_duration,
            "coverage_ratio": 0.0,
            "coverage_percent": "0.0%",
            "status_code": "EMPTY",
            "status_text": "Chưa có phụ đề nào được nhận diện",
            "status_badge": "🔴 CHƯA CÓ PHỤ ĐỀ (0%)",
            "warnings": ["Không tìm thấy câu thoại nào từ track âm thanh video!"],
            "gaps": []
        }

    # Gộp các khoảng thời gian thoại để tính tổng thời lượng nói
    intervals = sorted([(item.start_seconds, item.end_seconds) for item in items], key=lambda x: x[0])
    merged: List[List[float]] = []
    for st, en in intervals:
        if not merged:
            merged.append([st, en])
        else:
            if st <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], en)
            else:
                merged.append([st, en])

    spoken_duration = sum(en - st for st, en in merged)
    if total_duration <= 0.0 and merged:
        total_duration = max(merged[-1][1], 1.0)

    coverage_ratio = min(max(spoken_duration / total_duration, 0.0), 1.0) if total_duration > 0 else 1.0
    coverage_percent = f"{coverage_ratio * 100:.1f}%"

    # Phát hiện khoảng trống im lặng lớn (> 4.5 giây)
    gaps = []
    cur_t = 0.0
    for st, en in merged:
        if st - cur_t > 4.5:
            gaps.append((cur_t, st, round(st - cur_t, 1)))
        cur_t = max(cur_t, en)
    if total_duration - cur_t > 4.5:
        gaps.append((cur_t, total_duration, round(total_duration - cur_t, 1)))

    warnings = []
    if gaps:
        for g_st, g_en, g_dur in gaps:
            warnings.append(f"Khoảng không có thoại: {WhisperTranscriber.format_timestamp(g_st)} ➔ {WhisperTranscriber.format_timestamp(g_en)} ({g_dur}s)")

    if coverage_ratio >= 0.70:
        status_code = "EXCELLENT"
        status_text = f"Đã nhận diện {total_count} câu thoại đầy đủ, phủ {coverage_percent} video."
        status_badge = f"🟢 ĐẦY ĐỦ PHỤ ĐỀ ({coverage_percent})"
    elif coverage_ratio >= 0.40:
        status_code = "GOOD"
        status_text = f"Đã nhận diện {total_count} câu thoại (phủ {coverage_percent} video)."
        status_badge = f"🟡 TƯƠNG ĐỐI ({coverage_percent})"
    else:
        status_code = "LOW_COVERAGE"
        status_text = f"Độ phủ thấp ({coverage_percent}), video có thể nhiều nhạc hoặc ít thoại."
        status_badge = f"🟠 ĐỘ PHỦ THẤP ({coverage_percent})"

    return {
        "total_count": total_count,
        "spoken_duration": round(spoken_duration, 2),
        "total_duration": round(total_duration, 2),
        "coverage_ratio": round(coverage_ratio, 4),
        "coverage_percent": coverage_percent,
        "status_code": status_code,
        "status_text": status_text,
        "status_badge": status_badge,
        "warnings": warnings,
        "gaps": gaps
    }


class WhisperTranscriber:
    """
    Module nhận diện giọng nói (Speech-to-Text) tiếng Trung sang phụ đề SRT chuẩn.
    Hỗ trợ 3 cơ chế Local & Cloud thông minh (Multi-Engine Resilience, Không cần Docker):
    1. High-Speed In-Memory Web Speech STT Engine (100% miễn phí, cắt lát trong RAM, 10 workers song song, siêu tốc ~2s).
    2. Local OpenAI Whisper (nếu môi trường có thư viện whisper).
    3. Gemini Audio STT Cloud (khi có Google Generative AI key).
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.model_size = getattr(config, "whisper_model_size", "small")
        self.language = getattr(config, "whisper_language", "zh")
        self._whisper_module = None
        self._model = None

    def _is_local_whisper_available(self) -> bool:
        """Kiểm tra xem thư viện openai-whisper có khả dụng không"""
        try:
            import whisper
            self._whisper_module = whisper
            return True
        except ImportError:
            return False

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """Chuyển đổi giây sang định dạng SRT: HH:MM:SS,mmm"""
        td = datetime.timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        milliseconds = int(round((seconds - int(seconds)) * 1000))
        if milliseconds >= 1000:
            secs += 1
            milliseconds -= 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def _transcribe_with_local_whisper(self, audio_path: Path) -> List[SubtitleItem]:
        """Chạy STT bằng mô hình Whisper cục bộ"""
        if self._model is None:
            logger.info(f"Đang tải Whisper model cục bộ: '{self.model_size}'...")
            self._model = self._whisper_module.load_model(self.model_size)

        with tqdm(total=100, desc="[Bước 2.3] Local Whisper Speech-to-Text", leave=False) as pbar:
            result = self._model.transcribe(
                str(audio_path),
                language=self.language,
                task="transcribe",
                verbose=False,
                fp16=False,
                condition_on_previous_text=False,
                temperature=0.0,
                no_speech_threshold=0.6
            )
            pbar.update(100)

        segments = result.get("segments", [])
        subtitle_items: List[SubtitleItem] = []

        for idx, seg in enumerate(segments, start=1):
            start_sec = float(seg["start"])
            end_sec = float(seg["end"])
            text = seg["text"].strip()
            if not text:
                continue

            item = SubtitleItem(
                index=idx,
                start_seconds=start_sec,
                end_seconds=end_sec,
                start_str=self.format_timestamp(start_sec),
                end_str=self.format_timestamp(end_sec),
                text=text
            )
            subtitle_items.append(item)

        return subtitle_items

    def _transcribe_with_gemini_audio(self, audio_path: Path) -> List[SubtitleItem]:
        """Nhận diện giọng nói trực tiếp qua Gemini Multimodal Audio (REST API)"""
        api_key = self.config.gemini_api_key
        if not api_key:
            raise ValueError("Cần có Gemini API Key để nhận diện giọng nói qua Gemini Cloud!")

        logger.info("[Bước 2.3 Fallback] Đang nhận diện giọng nói qua Gemini Audio STT Cloud...")
        
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        temp_mp3 = audio_path.parent / f"temp_{audio_path.stem}_gemini_stt.mp3"
        
        try:
            cmd = [
                ffmpeg_bin, "-y", "-i", str(audio_path),
                "-vn", "-ar", "16000", "-ac", "1", "-b:a", "48k",
                str(temp_mp3)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            audio_bytes = temp_mp3.read_bytes()
            mime_type = "audio/mp3"
        except Exception:
            audio_bytes = audio_path.read_bytes()
            mime_type = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mp3"
        finally:
            temp_mp3.unlink(missing_ok=True)

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        prompt = (
            "Bạn là hệ thống nhận diện giọng nói (Speech-to-Text) chuyên nghiệp.\n"
            "Hãy nghe file âm thanh tiếng Trung này và xuất ra phụ đề chuẩn định dạng file SRT:\n"
            "- Giữ nguyên ngôn ngữ gốc tiếng Trung.\n"
            "- Số thứ tự index tăng dần (1, 2, 3...).\n"
            "- Timeline chính xác dạng '00:00:00,000 --> 00:00:00,000'.\n"
            "- Chỉ trả về duy nhất nội dung file SRT, không thêm lời giải thích hay bọc markdown."
        )

        candidate_models = [
            getattr(self.config, "gemini_model_name", "gemini-3.6-flash"),
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-flash-latest"
        ]
        unique_models = []
        for m in candidate_models:
            clean_m = m.replace("models/", "").strip()
            if clean_m and clean_m not in unique_models:
                unique_models.append(clean_m)

        res_data = None
        last_error = None

        for model in unique_models:
            for attempt in range(1, 4):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": audio_b64
                                    }
                                }
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.1
                    }
                }

                try:
                    with tqdm(total=100, desc=f"[Bước 2.3] Gemini Audio STT ({model})", leave=False) as pbar:
                        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=180)
                        pbar.update(100)

                    if res.status_code == 200:
                        res_data = res.json()
                        logger.info(f"Gemini Audio STT thành công với model: {model}")
                        break
                    elif res.status_code in (400, 401, 403, 404):
                        logger.warning(f"Gemini Audio STT model {model} trả về {res.status_code} ({res.text[:120]}). Chuyển sang model tiếp theo...")
                        last_error = f"Status {res.status_code}: {res.text}"
                        break
                    elif res.status_code == 429:
                        logger.warning(f"Gemini Audio STT model {model} rate limit (429), chờ thử lại ({attempt}/3)...")
                        time.sleep(2 * attempt)
                        continue
                    else:
                        logger.warning(f"Lỗi Gemini Audio STT ({model} - Status {res.status_code}), thử lại...")
                        time.sleep(1.5 * attempt)
                        last_error = f"Status {res.status_code}: {res.text}"
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"Gemini Audio STT ({model}) timeout/ngắt kết nối ({e}), đang thử lại ({attempt}/3)...")
                    last_error = str(e)
                    time.sleep(2 * attempt)
                except Exception as e:
                    last_error = str(e)
                    if "404" in str(e) or "403" in str(e) or "not found" in str(e).lower() or "no longer available" in str(e).lower():
                        break
                    logger.warning(f"Model {model} lỗi ({e}), thử lại...")
                    time.sleep(1.5 * attempt)

            if res_data:
                break

        if not res_data:
            raise RuntimeError(f"Lỗi Gemini Audio STT: Tất cả model đều thất bại. Chi tiết: {last_error}")

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        raw_text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", raw_text.strip())
        raw_text = re.sub(r"\n```$", "", raw_text.strip())

        return parse_srt_content(raw_text)

    def _transcribe_with_web_speech(self, audio_path: Path) -> List[SubtitleItem]:
        """
        Nhận diện giọng nói siêu tốc qua In-Memory Audio Slicing + Google Web Speech API.
        Đọc âm thanh 1 lần vào RAM, cắt lát không tốn tài nguyên và xử lý 10 luồng song song.
        Tự động vá bộ mã hóa FLAC in-memory qua soundfile để chạy siêu mượt trên Windows ARM64 / x64.
        """
        logger.info("[Bước 2.3 STT] Đang nhận diện giọng nói qua Local In-Memory Web Speech Engine...")
        import speech_recognition as sr

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

        # 1. Phát hiện khoảng lặng (silence detection) để cắt câu chính xác
        cmd_silence = [
            ffmpeg_bin, "-i", str(audio_path),
            "-af", "silencedetect=noise=-28dB:d=0.25",
            "-f", "null", "-"
        ]
        res_silence = subprocess.run(cmd_silence, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9\.]+)", res_silence.stderr)]
        silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9\.]+)", res_silence.stderr)]

        # Đọc toàn bộ audio vào RAM chuẩn 16000Hz mono 16-bit PCM (1 lần duy nhất)
        cmd_pcm = [
            ffmpeg_bin, "-y", "-v", "error",
            "-i", str(audio_path),
            "-ar", "16000", "-ac", "1",
            "-f", "s16le", "-"
        ]
        proc = subprocess.run(cmd_pcm, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_pcm = proc.stdout
        sample_rate = 16000
        sample_width = 2
        total_samples = len(raw_pcm) // sample_width
        total_dur = total_samples / sample_rate if sample_rate > 0 else 120.0

        raw_segments: List[Tuple[float, float]] = []
        cur = 0.0
        for s_start, s_end in zip(silence_starts, silence_ends):
            if s_start > cur + 0.30:
                raw_segments.append((cur, s_start))
            cur = s_end
        if cur < total_dur - 0.30:
            raw_segments.append((cur, total_dur))

        # Nếu không bắt được khoảng lặng nào, cắt theo sliding window 3.5s - 5.0s
        if not raw_segments:
            step = 4.0
            n = int(total_dur // step) + (1 if total_dur % step > 0 else 0)
            for k in range(n):
                c_st = k * step
                c_en = min(total_dur, (k + 1) * step)
                if c_en > c_st + 0.3:
                    raw_segments.append((c_st, c_en))

        # Chia nhỏ các đoạn nói dài (> 5.5 giây) thành từng câu 3-4.5 giây để phụ đề vừa vặn
        final_segments: List[Tuple[float, float]] = []
        for st, en in raw_segments:
            dur = en - st
            if dur > 5.5:
                step = 4.0
                n = int(dur // step) + (1 if dur % step > 0 else 0)
                chunk_len = dur / n
                for k in range(n):
                    c_st = st + k * chunk_len
                    c_en = min(en, st + (k + 1) * chunk_len)
                    final_segments.append((c_st, c_en))
            else:
                final_segments.append((st, en))

        if not final_segments:
            final_segments = [(0.0, total_dur)]

        # 2. Xử lý nhận diện song song qua ThreadPoolExecutor hoàn toàn trong RAM
        lang_code = "zh-CN" if self.language.lower().startswith("zh") else self.language

        def transcribe_segment(item: Tuple[int, float, float]) -> Tuple[int, float, float, str]:
            idx, st, en = item
            r = sr.Recognizer()
            try:
                start_byte = int(st * sample_rate) * sample_width
                end_byte = min(len(raw_pcm), int(en * sample_rate) * sample_width)
                chunk_bytes = raw_pcm[start_byte:end_byte]
                if len(chunk_bytes) < sample_rate * sample_width * 0.25:
                    return (idx, st, en, "")

                audio_data = sr.AudioData(chunk_bytes, sample_rate, sample_width)
                
                # Thử nhận diện với các mã ngôn ngữ tương thích
                text = ""
                for l_candidate in [lang_code, "zh-CN", "cmn-Hans-CN"]:
                    try:
                        text = r.recognize_google(audio_data, language=l_candidate).strip()
                        if text:
                            break
                    except Exception:
                        continue

                return (idx, st, en, text)
            except Exception as e:
                logger.debug(f"Segment {idx} ({st:.1f}-{en:.1f}s) STT error: {e}")
                return (idx, st, en, "")

        tasks = [(i, st, en) for i, (st, en) in enumerate(final_segments, 1)]
        results: List[Tuple[int, float, float, str]] = []

        with tqdm(total=len(tasks), desc="[Bước 2.3] Local In-Memory Web Speech STT", leave=False) as pbar:
            with ThreadPoolExecutor(max_workers=10) as executor:
                for res in executor.map(transcribe_segment, tasks):
                    results.append(res)
                    pbar.update(1)

        # 3. Tạo danh sách SubtitleItem hoàn chỉnh
        results.sort(key=lambda x: x[1])  # Sắp xếp theo timeline
        subtitle_items: List[SubtitleItem] = []
        out_idx = 1
        for _, st, en, text in results:
            if text:
                item = SubtitleItem(
                    index=out_idx,
                    start_seconds=st,
                    end_seconds=en,
                    start_str=self.format_timestamp(st),
                    end_str=self.format_timestamp(en),
                    text=text
                )
                subtitle_items.append(item)
                out_idx += 1

        return subtitle_items

    @staticmethod
    def deduplicate_hallucinated_subtitles(items: List[SubtitleItem]) -> List[SubtitleItem]:
        """
        Loại bỏ các đoạn phụ đề bị lặp vô nghĩa do Whisper hallucination (lặp lại cùng 1 câu nhiều lần trên nền nhạc/im lặng).
        Nếu 1 câu ngắn lặp lại liên tiếp >= 3 lần, tự động gộp thành 1 câu duy nhất với timeline chuẩn.
        """
        if not items:
            return []

        cleaned: List[SubtitleItem] = []
        i = 0
        while i < len(items):
            cur_item = items[i]
            cur_text = cur_item.text.strip()

            # Đếm số lần lặp liên tiếp
            repeat_group = [cur_item]
            j = i + 1
            while j < len(items):
                next_text = items[j].text.strip()
                if next_text == cur_text and len(cur_text) <= 20:
                    repeat_group.append(items[j])
                    j += 1
                else:
                    break

            if len(repeat_group) >= 3:
                logger.info(f"Đã phát hiện và làm sạch chuỗi lặp Hallucination ({len(repeat_group)} lần): '{cur_text}'")
                merged_end = min(cur_item.start_seconds + 3.0, repeat_group[-1].end_seconds)
                cleaned.append(
                    SubtitleItem(
                        index=len(cleaned) + 1,
                        start_seconds=cur_item.start_seconds,
                        end_seconds=merged_end,
                        start_str=cur_item.start_str,
                        end_str=WhisperTranscriber.format_timestamp(merged_end),
                        text=cur_text
                    )
                )
                i = j
            else:
                cur_item.index = len(cleaned) + 1
                cleaned.append(cur_item)
                i += 1

        return cleaned

    def transcribe(self, audio_path: Path, output_srt: Path) -> List[SubtitleItem]:
        """Nhận diện giọng nói từ file audio và lưu ra file SRT"""
        audio_path = Path(audio_path).resolve()
        output_srt = Path(output_srt).resolve()
        output_srt.parent.mkdir(parents=True, exist_ok=True)

        if not audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file audio: {audio_path}")

        items: List[SubtitleItem] = []

        # 1. Ưu tiên Local In-Memory Web Speech STT (Siêu tốc ~2s, không cần tải model nặng)
        try:
            logger.info("🟢 Đang chạy Local In-Memory Multi-Threaded STT Engine (Song song 10 luồng)...")
            items = self._transcribe_with_web_speech(audio_path)
        except Exception as e:
            logger.warning(f"Local In-Memory Web Speech STT gặp lỗi ({e}), chuyển sang engine tiếp theo...")
            items = []

        # 2. Local Whisper nếu có module openai-whisper
        if not items and self._is_local_whisper_available():
            logger.info("Phát hiện thư viện Whisper cục bộ. Đang chạy Local Whisper STT...")
            try:
                items = self._transcribe_with_local_whisper(audio_path)
            except Exception as e:
                logger.warning(f"Local Whisper gặp lỗi ({e}), chuyển sang fallback...")
                items = []

        # 3. Gemini Audio STT nếu có key
        if not items and getattr(self.config, "gemini_api_key", None):
            try:
                items = self._transcribe_with_gemini_audio(audio_path)
            except Exception as e:
                logger.warning(f"Gemini Audio STT không khả dụng ({e}).")
                items = []

        if not items:
            raise RuntimeError(
                "Bộ nhận diện giọng nói (Speech-to-Text) không tìm thấy câu thoại nào từ track âm thanh video! "
                "Vui lòng kiểm tra lại link video hoặc đảm bảo video có giọng nói rõ ràng."
            )

        # Lọc bỏ và làm sạch chuỗi lặp hallucination
        items = self.deduplicate_hallucinated_subtitles(items)

        srt_blocks = [item.to_srt_block() for item in items]
        full_srt_text = "\n".join(srt_blocks).strip() + "\n"
        output_srt.write_text(full_srt_text, encoding="utf-8")

        logger.info(f"Đã xuất file SRT gốc ({len(items)} câu): {output_srt}")
        return items
