"""
tts_synchronizer.py - Native CapCut Vietnamese Text-to-Speech & Timeline Audio Alignment
Chuyển đổi hoàn toàn từ Edge-TTS sang API CapCut / ByteDance TTS chính chủ.
Đồng bộ giọng đọc tiếng Việt và căn chỉnh phụ đề từng câu khớp 100% thời gian thực.
"""

from __future__ import annotations

import datetime
import io
import json
import logging
from pathlib import Path
import re
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from pydub import AudioSegment
import requests
from tqdm import tqdm

from capcut_tts_api import CapCutClient
from config import PipelineConfig, TTSConfig, VOICE_PRESETS
from transcriber import SubtitleItem

logger = logging.getLogger(__name__)


def format_timestamp(seconds: float) -> str:
    """Chuyển đổi số giây (float) sang định dạng SRT: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
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


class CapCutTTSEngine:
    """
    Engine giao tiếp trực tiếp với hệ thống ByteDance / CapCut TTS Server.
    Hỗ trợ sinh audio song song và hàng loạt (Batch Processing) tốc độ cao.
    """

    def __init__(self):
        self.client = CapCutClient()

    def synthesize_phrases(
        self,
        texts: List[str],
        voice: str = "BV074_streaming",
        resource_id: str = "7102355709945188865",
        rate: str = "1.0",
        max_retries: int = 3
    ) -> List[Tuple[str, Optional[bytes], int]]:
        """
        Gửi danh sách các câu tới CapCut TTS API trong 1 request duy nhất.
        :return: List of (text, audio_bytes, duration_ms)
        """
        if not texts:
            return []

        # Lấy thông tin voice và resource_id từ VOICE_PRESETS nếu có
        final_voice = voice
        final_res_id = resource_id
        for p_key, p_val in VOICE_PRESETS.items():
            if voice in (p_key, p_val["voice"], p_val["name"]):
                final_voice = p_val["voice"]
                final_res_id = p_val["resource_id"]
                break

        for attempt in range(1, max_retries + 1):
            try:
                url, headers, body = self.client.build_tts_new_request(
                    texts=texts,
                    voice=final_voice,
                    resource_id=final_res_id,
                    rate=rate
                )

                resp = requests.post(url, headers=headers, data=body, timeout=12)
                resp_json = resp.json()

                if "data" not in resp_json or not resp_json["data"].get("tasks"):
                    raise RuntimeError(f"CapCut Task Creation failed: {resp_json.get('errmsg', 'Unknown')}")

                task_info = resp_json["data"]["tasks"][0]
                task_id = task_info["id"]
                task_token = task_info["token"]

                # Polling chờ kết quả
                completed = False
                payload_data = None
                for _ in range(15):
                    time.sleep(1.0)
                    q_url, q_headers, q_body = self.client.build_query_request(
                        task_id, task_token, "sami_text_to_speech"
                    )
                    q_resp = requests.post(q_url, headers=q_headers, data=q_body, timeout=10)
                    q_json = q_resp.json()

                    if q_json.get("data", {}).get("tasks"):
                        t_obj = q_json["data"]["tasks"][0]
                        if t_obj.get("status") == "succeed":
                            payload_data = json.loads(t_obj["payload"])
                            completed = True
                            break
                        elif t_obj.get("status") == "failed":
                            raise RuntimeError(f"CapCut Task failed on server: {t_obj}")

                if not completed or not payload_data:
                    raise TimeoutError("CapCut TTS polling timed out")

                # Tải audio streams
                sub_list = payload_data.get("audio_subtitles", [])
                results: List[Tuple[str, Optional[bytes], int]] = []

                for idx, sub in enumerate(sub_list):
                    t_text = sub.get("text", texts[idx] if idx < len(texts) else "")
                    audio_url = sub.get("speech_url")
                    duration_ms = sub.get("duration", 0)

                    audio_bytes = None
                    if audio_url:
                        try:
                            audio_resp = requests.get(audio_url, timeout=10)
                            if audio_resp.status_code == 200 and len(audio_resp.content) > 0:
                                audio_bytes = audio_resp.content
                        except Exception as dl_err:
                            logger.warning(f"Lỗi tải audio câu '{t_text}': {dl_err}")

                    results.append((t_text, audio_bytes, duration_ms))

                return results

            except Exception as e:
                logger.warning(f"Lần thử {attempt}/{max_retries} sinh CapCut TTS thất bại: {e}")
                if attempt == max_retries:
                    return [(t, None, 0) for t in texts]
                time.sleep(1.5)

        return [(t, None, 0) for t in texts]


class VietnameseTTSSynchronizer:
    """
    Module đọc phụ đề tiếng Việt bằng CapCut TTS chính chủ và đồng bộ chính xác vào timeline video.
    Tự động chia nhỏ các câu/đoạn văn dài thành các cụm từ ngắn gọn (5-8 từ).
    Tạo ra file phụ đề SRT mới khớp chính xác 100% từng giây giọng nói (nói tới đâu phụ đề hiện tới đó).
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tts_config: TTSConfig = config.tts_config
        self.engine = CapCutTTSEngine()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Làm sạch văn bản trước khi gửi đến CapCut TTS"""
        text = re.sub(r"[*#_~`]", "", text).strip()
        if not re.search(r"[\w\d\u00C0-\u1EF9]", text, re.UNICODE):
            return ""
        return text

    @staticmethod
    def split_text_into_short_phrases(text: str, max_words: int = 8, max_chars: int = 35) -> List[str]:
        """
        Chia nhỏ một câu hoặc đoạn văn bản dài thành các cụm từ ngắn (5-8 từ hoặc tối đa 35 ký tự),
        phù hợp với nhịp nói của video ngắn TikTok/Douyin (chống tràn màn hình).
        """
        text = re.sub(r"[*#_~`]", "", text).strip()
        if not text:
            return []

        # Tách theo các dấu câu tự nhiên
        raw_clauses = re.split(r"([.,!?;:\n—–]+)", text)
        clauses = []
        temp = ""
        for part in raw_clauses:
            if not part:
                continue
            if re.match(r"^[.,!?;:\n—–]+$", part):
                temp += part
                if temp.strip():
                    clauses.append(temp.strip())
                temp = ""
            else:
                temp = part.strip()
        if temp.strip():
            clauses.append(temp.strip())

        final_phrases = []
        for c in clauses:
            words = c.split()
            if not words:
                continue
            if len(words) <= max_words and len(c) <= max_chars:
                final_phrases.append(c)
            else:
                cur_phrase = []
                for w in words:
                    cur_phrase.append(w)
                    p_text = " ".join(cur_phrase)
                    if len(cur_phrase) >= max_words or len(p_text) >= max_chars:
                        final_phrases.append(p_text)
                        cur_phrase = []
                if cur_phrase:
                    if len(cur_phrase) <= 2 and final_phrases:
                        final_phrases[-1] += " " + " ".join(cur_phrase)
                    else:
                        final_phrases.append(" ".join(cur_phrase))

        return final_phrases if final_phrases else [text]

    @staticmethod
    def _speed_change(sound: AudioSegment, speed: float = 1.0) -> AudioSegment:
        """Thay đổi tốc độ phát của AudioSegment mà giữ nguyên cao độ (pitch) tương đối"""
        if abs(speed - 1.0) < 0.02:
            return sound
        sound_with_altered_frame_rate = sound._spawn(
            sound.raw_data,
            overrides={"frame_rate": int(sound.frame_rate * speed)}
        )
        return sound_with_altered_frame_rate.set_frame_rate(sound.frame_rate)

    def generate_and_sync(
        self,
        subtitles: List[SubtitleItem],
        total_duration_seconds: float,
        output_audio_path: Path,
        output_srt_path: Optional[Path] = None
    ) -> Tuple[Path, List[SubtitleItem]]:
        """
        Tạo file audio tổng hợp và đồng bộ chính xác phụ đề từng câu ngắn theo giọng nói thực tế.
        :return: (output_audio_path, synced_subtitles)
        """
        output_audio_path = Path(output_audio_path).resolve()
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        total_ms = int(total_duration_seconds * 1000) + 1500
        logger.info(f"[Bước 5] Đang sinh giọng đọc CapCut ({self.tts_config.voice}) & đồng bộ phụ đề từng câu...")

        master_track = AudioSegment.silent(duration=total_ms)

        # 1. Phân rã tất cả các câu phụ đề thành các cụm từ ngắn (Short Phrases)
        phrase_tasks = []
        all_phrases_flat: List[str] = []
        phrase_map: List[Tuple[int, int]] = []  # (group_idx, phrase_idx)

        for orig_idx, item in enumerate(subtitles):
            clean_item_text = self._clean_text(item.text)
            if not clean_item_text:
                continue
            sub_phrases = self.split_text_into_short_phrases(clean_item_text)
            phrase_tasks.append({
                "orig_item": item,
                "phrases": sub_phrases
            })
            for p_idx, p_text in enumerate(sub_phrases):
                all_phrases_flat.append(p_text)
                phrase_map.append((len(phrase_tasks) - 1, p_idx))

        # 2. Sinh audio cho từng cụm từ qua CapCut TTS theo Batch (mỗi batch 10-15 câu)
        batch_size = 12
        audio_cache: Dict[Tuple[int, int], AudioSegment] = {}

        with tqdm(total=len(all_phrases_flat), desc="[Bước 5.1] CapCut TTS Từng Câu", leave=False) as pbar:
            for b_start in range(0, len(all_phrases_flat), batch_size):
                b_texts = all_phrases_flat[b_start : b_start + batch_size]
                b_maps = phrase_map[b_start : b_start + batch_size]

                batch_results = self.engine.synthesize_phrases(
                    texts=b_texts,
                    voice=self.tts_config.voice,
                    resource_id=getattr(self.tts_config, "resource_id", "7102355709945188865"),
                    rate=getattr(self.tts_config, "rate", "1.0")
                )

                for (p_text, a_bytes, dur_ms), map_idx in zip(batch_results, b_maps):
                    if a_bytes:
                        try:
                            seg = AudioSegment.from_file(io.BytesIO(a_bytes))
                            audio_cache[map_idx] = seg
                        except Exception as e:
                            logger.warning(f"Lỗi nạp audio segment cho '{p_text}': {e}")
                    pbar.update(1)

        # 3. Đồng bộ hóa Audio vào Master Track và tạo danh sách SubtitleItem chuẩn khớp theo từng câu
        synced_subtitles: List[SubtitleItem] = []
        global_sub_idx = 1

        with tqdm(total=len(phrase_tasks), desc="[Bước 5.2] Khớp Timeline & Phụ Đề", leave=False) as pbar:
            for group_idx, group in enumerate(phrase_tasks):
                orig_item: SubtitleItem = group["orig_item"]
                phrases: List[str] = group["phrases"]

                # Tải audio của các cụm từ trong nhóm này
                phrase_audios: List[Tuple[str, AudioSegment]] = []
                total_group_audio_ms = 0

                for p_idx, phrase in enumerate(phrases):
                    map_key = (group_idx, p_idx)
                    if map_key in audio_cache:
                        seg = audio_cache[map_key]
                        phrase_audios.append((phrase, seg))
                        total_group_audio_ms += len(seg)

                if not phrase_audios:
                    pbar.update(1)
                    continue

                # Tính toán slot thời gian cho phép trong video
                slot_duration_ms = (orig_item.end_seconds - orig_item.start_seconds) * 1000
                start_ms = int(orig_item.start_seconds * 1000)

                # Nếu audio dài hơn khoảng cho phép, tăng tốc nhẹ để vừa vặn slot
                speed_ratio = 1.0
                if total_group_audio_ms > slot_duration_ms > 0:
                    speed_ratio = min(total_group_audio_ms / slot_duration_ms, 1.30)

                # Đặt từng cụm từ vào master track và tạo SubtitleItem tương ứng
                cur_start_ms = start_ms
                for phrase_text, phrase_seg in phrase_audios:
                    if speed_ratio > 1.02:
                        phrase_seg = self._speed_change(phrase_seg, speed_ratio)

                    p_dur_ms = len(phrase_seg)
                    p_start_sec = cur_start_ms / 1000.0
                    p_end_sec = (cur_start_ms + p_dur_ms) / 1000.0

                    # Đặt audio vào master track
                    master_track = master_track.overlay(phrase_seg, position=cur_start_ms)

                    # Tạo phụ đề hiển thị chỉ trong đúng khoảng thời gian đọc câu này
                    synced_subtitles.append(
                        SubtitleItem(
                            index=global_sub_idx,
                            start_seconds=p_start_sec,
                            end_seconds=p_end_sec,
                            start_str=format_timestamp(p_start_sec),
                            end_str=format_timestamp(p_end_sec),
                            text=phrase_text.strip()
                        )
                    )
                    global_sub_idx += 1
                    cur_start_ms += p_dur_ms + 80  # Nghỉ 80ms giữa các cụm từ

                pbar.update(1)

        # 4. Xuất file âm thanh TTS hoàn chỉnh
        master_track = master_track[: int(total_duration_seconds * 1000)]
        master_track.export(str(output_audio_path), format="wav")
        logger.info(f"Đã tạo audio CapCut TTS đồng bộ: {output_audio_path}")

        # 5. Xuất file SRT phụ đề đã đồng bộ nếu có yêu cầu
        if output_srt_path:
            output_srt_path = Path(output_srt_path).resolve()
            output_srt_path.parent.mkdir(parents=True, exist_ok=True)
            srt_blocks = [item.to_srt_block() for item in synced_subtitles]
            final_srt_text = "\n".join(srt_blocks).strip() + "\n"
            output_srt_path.write_text(final_srt_text, encoding="utf-8")
            logger.info(f"Đã lưu phụ đề đồng bộ từng câu ({len(synced_subtitles)} câu ngắn) tại: {output_srt_path}")

        return output_audio_path, synced_subtitles


# Alias để giữ tính tương thích ngược
CapCutTTSSynchronizer = VietnameseTTSSynchronizer
