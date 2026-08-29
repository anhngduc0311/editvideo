"""
transcriber.py - Speech-to-Text with Multi-Engine Support (Whisper AI + Gemini Audio STT + Web Speech Fallback)
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
from typing import List, Optional, Tuple
import requests
from tqdm import tqdm

from config import PipelineConfig

logger = logging.getLogger(__name__)


@dataclass
class SubtitleItem:
    index: int
    start_seconds: float
    end_seconds: float
    start_str: str
    end_str: str
    text: str

    def to_srt_block(self) -> str:
        return f"{self.index}\n{self.start_str} --> {self.end_str}\n{self.text.strip()}\n"


class WhisperTranscriber:
    """
    Module nhận diện giọng nói (Speech-to-Text) tiếng Trung sang phụ đề SRT chuẩn.
    Hỗ trợ 3 cơ chế tự động chuyển đổi thông minh (Triple-Engine Resilience):
    1. Local OpenAI Whisper (nếu môi trường đã cài đặt thư viện whisper).
    2. Gemini Audio STT Cloud (khi API Key có quyền multimodal audio).
    3. High-Speed Web Speech STT Engine via FFmpeg VAD Segmentation (100% miễn phí, chạy mượt trên mọi hệ điều hành).
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.model_size = config.whisper_model_size
        self.language = config.whisper_language
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
            logger.info(f"Đang tải Whisper model: '{self.model_size}'...")
            self._model = self._whisper_module.load_model(self.model_size)

        with tqdm(total=100, desc="[Bước 2.3] Local Whisper Speech-to-Text", leave=False) as pbar:
            result = self._model.transcribe(
                str(audio_path),
                language=self.language,
                task="transcribe",
                verbose=False,
                fp16=False
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
        """
        Nhận diện giọng nói trực tiếp qua Gemini Multimodal Audio (REST API)
        """
        api_key = self.config.gemini_api_key
        if not api_key:
            raise ValueError("Cần có Gemini API Key để nhận diện giọng nói qua Gemini Cloud!")

        logger.info("[Bước 2.3 Fallback] Đang nhận diện giọng nói qua Gemini Audio STT Cloud...")
        
        # Nén audio sang 16kHz mono MP3 để tránh vượt quá giới hạn payload của Google
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
            self.config.gemini_model_name,
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
                        logger.warning(f"Gemini Audio STT model {model} trả về {res.status_code} ({res.text[:120]}). Chuyển sang model tiếp theo hoặc fallback...")
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

        # Phân tích SRT
        pattern = re.compile(
            r"(\d+)\s*\n"
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n"
            r"([\s\S]*?)(?=\n{2,}|\n*\Z)"
        )
        items = []
        for match in pattern.finditer(raw_text.strip()):
            idx = int(match.group(1))
            start_str = match.group(2).replace(".", ",")
            end_str = match.group(3).replace(".", ",")
            text = match.group(4).strip()

            def to_secs(t_str: str) -> float:
                h, m, s_ms = t_str.split(":")
                s, ms = s_ms.split(",")
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

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

    def _transcribe_with_web_speech(self, audio_path: Path) -> List[SubtitleItem]:
        """
        Nhận diện giọng nói siêu tốc & ổn định qua FFmpeg VAD Segmentation + Google Web Speech API.
        100% miễn phí, không yêu cầu API key, hoạt động hoàn hảo trên mọi nền tảng kể cả ARM64.
        """
        logger.info("[Bước 2.3 Fallback Web STT] Đang nhận diện giọng nói qua Web Speech Engine...")
        import speech_recognition as sr

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

        # Monkey-patch FLAC conversion via FFmpeg để không phụ thuộc vào flac.exe
        def ffmpeg_get_flac_data(audio_data_self, convert_rate=None, convert_width=None):
            wav_data = audio_data_self.get_wav_data(convert_rate=convert_rate, convert_width=convert_width)
            proc = subprocess.run(
                [ffmpeg_bin, "-y", "-i", "pipe:0", "-f", "flac", "pipe:1"],
                input=wav_data,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True
            )
            return proc.stdout

        sr.AudioData.get_flac_data = ffmpeg_get_flac_data

        # 1. Phát hiện khoảng lặng (silence detection) để cắt câu chính xác
        cmd_silence = [
            ffmpeg_bin, "-i", str(audio_path),
            "-af", "silencedetect=noise=-30dB:d=0.30",
            "-f", "null", "-"
        ]
        res_silence = subprocess.run(cmd_silence, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9\.]+)", res_silence.stderr)]
        silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9\.]+)", res_silence.stderr)]

        # Lấy tổng thời lượng audio
        cmd_dur = [ffmpeg_bin, "-i", str(audio_path)]
        res_dur = subprocess.run(cmd_dur, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        m_dur = re.search(r"Duration:\s*(\d+):(\d+):([0-9\.]+)", res_dur.stderr)
        total_dur = (
            int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))
            if m_dur else 120.0
        )

        raw_segments: List[Tuple[float, float]] = []
        cur = 0.0
        for s_start, s_end in zip(silence_starts, silence_ends):
            if s_start > cur + 0.35:
                raw_segments.append((cur, s_start))
            cur = s_end
        if cur < total_dur - 0.35:
            raw_segments.append((cur, total_dur))

        # Chia nhỏ các đoạn nói dài (> 6 giây) thành từng câu 3-5 giây để hiển thị phụ đề đẹp mắt
        final_segments: List[Tuple[float, float]] = []
        for st, en in raw_segments:
            dur = en - st
            if dur > 6.0:
                step = 5.0
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

        # Tự động cấu hình bộ mã hóa FLAC qua FFmpeg cho SpeechRecognition
        def ffmpeg_flac_data(audio_inst, convert_rate=None, convert_width=None):
            wav_data = audio_inst.get_wav_data(convert_rate=convert_rate, convert_width=convert_width)
            cmd = [ffmpeg_bin, "-y", "-i", "pipe:0", "-f", "flac", "pipe:1"]
            return subprocess.run(cmd, input=wav_data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout

        sr.AudioData.get_flac_data = ffmpeg_flac_data

        # 2. Xử lý nhận diện song song qua ThreadPoolExecutor
        def transcribe_segment(item: Tuple[int, float, float]) -> Tuple[int, float, float, str]:
            idx, st, en = item
            r = sr.Recognizer()
            try:
                chunk_proc = subprocess.run(
                    [ffmpeg_bin, "-y", "-ss", f"{st:.3f}", "-to", f"{en:.3f}", "-i", str(audio_path), "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
                with sr.AudioFile(io.BytesIO(chunk_proc.stdout)) as source:
                    audio_data = r.record(source)
                
                lang_code = "zh-CN" if self.language.lower().startswith("zh") else self.language
                text = r.recognize_google(audio_data, language=lang_code).strip()
                return (idx, st, en, text)
            except Exception:
                return (idx, st, en, "")

        tasks = [(i, st, en) for i, (st, en) in enumerate(final_segments, 1)]
        results: List[Tuple[int, float, float, str]] = []

        with tqdm(total=len(tasks), desc="[Bước 2.3] Web Speech STT", leave=False) as pbar:
            with ThreadPoolExecutor(max_workers=5) as executor:
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

    def transcribe(self, audio_path: Path, output_srt: Path) -> List[SubtitleItem]:
        """Nhận diện giọng nói từ file audio và lưu ra file SRT"""
        audio_path = Path(audio_path).resolve()
        output_srt = Path(output_srt).resolve()
        output_srt.parent.mkdir(parents=True, exist_ok=True)

        if not audio_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file audio: {audio_path}")

        items: List[SubtitleItem] = []
        if self._is_local_whisper_available():
            logger.info("Phát hiện thư viện Whisper cục bộ. Đang chạy Local Whisper STT...")
            items = self._transcribe_with_local_whisper(audio_path)
        else:
            try:
                items = self._transcribe_with_gemini_audio(audio_path)
            except Exception as e:
                logger.warning(
                    f"Gemini Audio STT không khả dụng hoặc bị giới hạn ({e}). "
                    "Tự động chuyển sang Bộ nhận diện giọng nói Web Speech STT..."
                )
                items = self._transcribe_with_web_speech(audio_path)

        if not items:
            logger.warning("Không nhận diện được giọng nói trong audio!")

        srt_blocks = [item.to_srt_block() for item in items]
        full_srt_text = "\n".join(srt_blocks).strip() + "\n"
        output_srt.write_text(full_srt_text, encoding="utf-8")

        logger.info(f"Đã xuất file SRT gốc ({len(items)} câu): {output_srt}")
        return items
