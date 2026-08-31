"""
tts_synchronizer.py - Native CapCut Vietnamese Text-to-Speech & Timeline Audio Alignment
Chuyển đổi hoàn toàn từ Edge-TTS sang API CapCut / ByteDance TTS chính chủ.
Đồng bộ giọng đọc tiếng Việt nói trọn vẹn hết câu, giữ nguyên cao độ (pitch) và căn chỉnh timeline chuẩn xác 100%.
"""

from __future__ import annotations

import datetime
import io
import json
import logging
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from pydub import AudioSegment
import requests
from tqdm import tqdm

from capcut_tts_api import CapCutClient
from config import PipelineConfig, TTSConfig, VOICE_PRESETS
from transcriber import SubtitleItem

from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter

# Nạp static_ffmpeg nếu có
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

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
    Hỗ trợ sinh audio song song, kết nối Pool và tải đa luồng tốc độ cao chống Timeout.
    """

    def __init__(self):
        self.client = CapCutClient()
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "*/*"
        })

    def synthesize_phrases(
        self,
        texts: List[str],
        voice: str = "BV074_streaming",
        resource_id: str = "7102355709945188865",
        rate: str = "1.0",
        max_retries: int = 3
    ) -> List[Tuple[str, Optional[bytes], int]]:
        """
        Gửi danh sách các câu tới CapCut TTS API trong 1 request duy nhất và tải song song các file audio.
        :return: List of (text, audio_bytes, duration_ms)
        """
        if not texts:
            return []

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

                resp = self.session.post(url, headers=headers, data=body, timeout=(5, 15))
                resp_json = resp.json()

                if "data" not in resp_json or not resp_json["data"].get("tasks"):
                    raise RuntimeError(f"CapCut Task Creation failed: {resp_json.get('errmsg', 'Unknown')}")

                task_info = resp_json["data"]["tasks"][0]
                task_id = task_info["id"]
                task_token = task_info["token"]

                # Polling chờ kết quả với chu kỳ thích ứng nhanh (0.35s)
                completed = False
                payload_data = None
                for poll_i in range(35):
                    time.sleep(0.35)
                    q_url, q_headers, q_body = self.client.build_query_request(
                        task_id, task_token, "sami_text_to_speech"
                    )
                    q_resp = self.session.post(q_url, headers=q_headers, data=q_body, timeout=(5, 15))
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

                # Tải song song toàn bộ audio streams qua ThreadPoolExecutor
                sub_list = payload_data.get("audio_subtitles", [])

                def _fetch_single_audio(item_tuple):
                    idx, sub = item_tuple
                    t_text = sub.get("text", texts[idx] if idx < len(texts) else "")
                    audio_url = sub.get("speech_url")
                    duration_ms = sub.get("duration", 0)

                    audio_bytes = None
                    if audio_url:
                        for dl_attempt in range(1, 4):
                            try:
                                audio_resp = self.session.get(audio_url, timeout=(5, 25))
                                if audio_resp.status_code == 200 and len(audio_resp.content) > 0:
                                    audio_bytes = audio_resp.content
                                    break
                            except Exception as dl_err:
                                if dl_attempt == 3:
                                    logger.warning(f"Lỗi tải audio câu '{t_text}' (Lần {dl_attempt}/3): {dl_err}")
                                time.sleep(0.5 * dl_attempt)

                    return (idx, t_text, audio_bytes, duration_ms)

                workers = min(8, len(sub_list) or 1)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    fetched_items = list(pool.map(_fetch_single_audio, enumerate(sub_list)))

                # Sắp xếp đúng thứ tự ban đầu
                fetched_items.sort(key=lambda x: x[0])
                results = [(item[1], item[2], item[3]) for item in fetched_items]

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
    Đọc trọn vẹn từng câu đầy đủ ngữ điệu, giữ nguyên cao độ (pitch) và không bị ngắt cụt chữ.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tts_config: TTSConfig = config.tts_config
        self.engine = CapCutTTSEngine()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Làm sạch văn bản trước khi gửi đến CapCut TTS và đảm bảo kết thúc bằng dấu câu"""
        text = re.sub(r"[*#_~`]", "", text).strip()
        if not re.search(r"[\w\d\u00C0-\u1EF9]", text, re.UNICODE):
            return ""
        # Đảm bảo có dấu câu kết thúc để giọng đọc có ngữ điệu trọn vẹn
        if text[-1] not in ".!?":
            text += "."
        return text

    @staticmethod
    def _speed_change_ffmpeg(sound: AudioSegment, speed: float = 1.0) -> AudioSegment:
        """
        Thay đổi tốc độ phát của AudioSegment bằng FFmpeg atempo trong bộ nhớ RAM,
        bảo toàn 100% cao độ (pitch) tự nhiên của giọng nói, không bị méo giọng hay giọng sóc chuột (chipmunk).
        """
        if abs(speed - 1.0) < 0.02 or len(sound) == 0:
            return sound

        # Giới hạn tốc độ an toàn từ 0.7x đến 1.35x để giữ giọng nói tự nhiên, rõ chữ
        speed = max(0.70, min(speed, 1.35))

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "wav", "-i", "pipe:0",
            "-filter:a", f"atempo={speed:.4f}",
            "-f", "wav", "pipe:1"
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            wav_data = io.BytesIO()
            sound.export(wav_data, format="wav")
            out_wav, _ = proc.communicate(wav_data.getvalue())
            if proc.returncode == 0 and len(out_wav) > 44:
                return AudioSegment.from_file(io.BytesIO(out_wav), format="wav")
        except Exception:
            pass

        return sound

    @classmethod
    def split_subtitles_into_short_sentences(cls, subtitles: List[SubtitleItem]) -> List[SubtitleItem]:
        """
        Tách các khối phụ đề chứa nhiều câu thành từng câu ngắn riêng biệt.
        Tính toán lại timeline ước tính để từng câu được đọc và hiển thị độc lập,
        khớp chính xác với giọng đọc và chỉ hiển thị 1 câu ngắn trên màn hình tại một thời điểm.
        """
        output_items: List[SubtitleItem] = []
        global_idx = 1

        for item in subtitles:
            raw_text = item.text.strip()
            if not raw_text:
                continue

            # Tách theo các dấu kết thúc câu (. ! ? … ; \n)
            sentence_parts = [p.strip() for p in re.split(r'(?<=[.!?…;\n])\s+', raw_text) if p.strip()]
            
            # Làm sạch và tách nhỏ các câu quá dài có dấu phẩy
            refined_sentences: List[str] = []
            for part in sentence_parts:
                part = part.strip()
                if not part:
                    continue
                words = part.split()
                if len(words) >= 12 and "," in part:
                    comma_split = [cp.strip() for cp in re.split(r',\s*', part) if cp.strip()]
                    if len(comma_split) == 2 and all(len(cp.split()) >= 4 for cp in comma_split):
                        refined_sentences.extend(comma_split)
                        continue
                refined_sentences.append(part)

            if not refined_sentences:
                continue

            if len(refined_sentences) == 1:
                output_items.append(
                    SubtitleItem(
                        index=global_idx,
                        start_seconds=item.start_seconds,
                        end_seconds=item.end_seconds,
                        start_str=item.start_str,
                        end_str=item.end_str,
                        text=refined_sentences[0]
                    )
                )
                global_idx += 1
            else:
                # Phân bổ timeline ước tính theo tỷ lệ độ dài ký tự của từng câu
                total_chars = sum(max(1, len(s)) for s in refined_sentences)
                block_dur = max(0.5, item.end_seconds - item.start_seconds)
                cur_start = item.start_seconds

                for s_text in refined_sentences:
                    s_dur = block_dur * (len(s_text) / total_chars)
                    s_end = cur_start + s_dur
                    output_items.append(
                        SubtitleItem(
                            index=global_idx,
                            start_seconds=cur_start,
                            end_seconds=s_end,
                            start_str=format_timestamp(cur_start),
                            end_str=format_timestamp(s_end),
                            text=s_text
                        )
                    )
                    global_idx += 1
                    cur_start = s_end

        return output_items

    def generate_and_sync(
        self,
        subtitles: List[SubtitleItem],
        total_duration_seconds: float,
        output_audio_path: Path,
        output_srt_path: Optional[Path] = None
    ) -> Tuple[Path, List[SubtitleItem]]:
        """
        Tạo file audio tổng hợp và đồng bộ chính xác phụ đề từng câu theo giọng nói thực tế.
        Đảm bảo hiển thị TỪNG CÂU một, giọng đọc nói HẾT CÂU và khớp chính xác 100% với phụ đề.
        :return: (output_audio_path, synced_subtitles)
        """
        output_audio_path = Path(output_audio_path).resolve()
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        total_ms = int(total_duration_seconds * 1000) + 3000
        logger.info(f"[Bước 4] Đang sinh giọng đọc CapCut ({self.tts_config.voice}) nói trọn vẹn từng câu...")

        master_track = AudioSegment.silent(duration=total_ms)

        # 1. Tách phụ đề thành từng câu ngắn độc lập để hiển thị và đọc từng câu riêng biệt
        split_subtitles = self.split_subtitles_into_short_sentences(subtitles)

        valid_items: List[Tuple[int, SubtitleItem, str]] = []
        for idx, item in enumerate(split_subtitles):
            cleaned = self._clean_text(item.text)
            if cleaned:
                valid_items.append((idx, item, cleaned))

        if not valid_items:
            logger.warning("Không có câu phụ đề hợp lệ nào để lồng tiếng!")
            master_track[: int(total_duration_seconds * 1000)].export(str(output_audio_path), format="wav")
            return output_audio_path, []

        # 2. Gửi từng batch câu hoàn chỉnh đến CapCut TTS để sinh giọng nói tự nhiên, mượt mà
        # 2. Gửi batch câu (lên tới 40 câu/lần) đến CapCut TTS để sinh giọng nói siêu tốc
        batch_size = 40
        audio_dict: Dict[int, AudioSegment] = {}
        all_texts = [text for _, _, text in valid_items]

        batches = [valid_items[i : i + batch_size] for i in range(0, len(valid_items), batch_size)]

        def _synthesize_batch_worker(batch_data):
            b_items = batch_data
            b_texts = [text for _, _, text in b_items]
            results = self.engine.synthesize_phrases(
                texts=b_texts,
                voice=self.tts_config.voice,
                resource_id=getattr(self.tts_config, "resource_id", "7102355709945188865"),
                rate=getattr(self.tts_config, "rate", "1.0")
            )
            return b_items, results

        with tqdm(total=len(valid_items), desc="[Bước 4.1] CapCut TTS Sinh Giọng Đầy Đủ Câu", leave=False) as pbar:
            if len(batches) <= 1:
                for b_items, batch_results in [_synthesize_batch_worker(batches[0])]:
                    for (p_text, a_bytes, dur_ms), (orig_idx, _, _) in zip(batch_results, b_items):
                        if a_bytes:
                            try:
                                seg = AudioSegment.from_file(io.BytesIO(a_bytes))
                                audio_dict[orig_idx] = seg
                            except Exception as e:
                                logger.warning(f"Lỗi nạp audio segment cho '{p_text}': {e}")
                        pbar.update(1)
            else:
                with ThreadPoolExecutor(max_workers=min(3, len(batches))) as pool:
                    for b_items, batch_results in pool.map(_synthesize_batch_worker, batches):
                        for (p_text, a_bytes, dur_ms), (orig_idx, _, _) in zip(batch_results, b_items):
                            if a_bytes:
                                try:
                                    seg = AudioSegment.from_file(io.BytesIO(a_bytes))
                                    audio_dict[orig_idx] = seg
                                except Exception as e:
                                    logger.warning(f"Lỗi nạp audio segment cho '{p_text}': {e}")
                            pbar.update(1)

        # 3. Đồng bộ hóa Audio vào Master Track đảm bảo NÓI TRỌN VẸN HẾT CÂU
        synced_subtitles: List[SubtitleItem] = []
        global_sub_idx = 1
        last_audio_end_ms = 0

        with tqdm(total=len(valid_items), desc="[Bước 4.2] Căn Chỉnh Khớp Timeline Tự Nhiên", leave=False) as pbar:
            for i, (orig_idx, orig_item, clean_text) in enumerate(valid_items):
                if orig_idx not in audio_dict:
                    pbar.update(1)
                    continue

                audio_seg = audio_dict[orig_idx]
                seg_len_ms = len(audio_seg)

                orig_start_ms = int(orig_item.start_seconds * 1000)
                orig_end_ms = int(orig_item.end_seconds * 1000)

                # Xác định thời điểm bắt đầu: không được đè lên câu trước
                target_start_ms = max(orig_start_ms, last_audio_end_ms)

                # Tính slot thời gian cho phép đến câu tiếp theo
                if i + 1 < len(valid_items):
                    next_orig_start_ms = int(valid_items[i + 1][1].start_seconds * 1000)
                    available_slot_ms = max(next_orig_start_ms - target_start_ms, orig_end_ms - target_start_ms)
                else:
                    available_slot_ms = max(int(total_duration_seconds * 1000) - target_start_ms, orig_end_ms - target_start_ms)

                # Nếu audio dài hơn khoảng thời gian cho phép, tăng tốc nhẹ bằng atempo (giữ pitch) để vừa vặn
                if seg_len_ms > available_slot_ms > 400:
                    speed_ratio = min(seg_len_ms / max(available_slot_ms - 50, 400), 1.25)
                    if speed_ratio > 1.03:
                        audio_seg = self._speed_change_ffmpeg(audio_seg, speed_ratio)
                        seg_len_ms = len(audio_seg)

                # Đặt audio vào master track
                master_track = master_track.overlay(audio_seg, position=target_start_ms)

                actual_start_sec = target_start_ms / 1000.0
                actual_end_sec = (target_start_ms + seg_len_ms) / 1000.0
                last_audio_end_ms = target_start_ms + seg_len_ms + 60  # Nghỉ 60ms tự nhiên giữa các câu

                # Tạo phụ đề hiển thị khớp với thời gian đọc câu này
                synced_subtitles.append(
                    SubtitleItem(
                        index=global_sub_idx,
                        start_seconds=actual_start_sec,
                        end_seconds=actual_end_sec,
                        start_str=format_timestamp(actual_start_sec),
                        end_str=format_timestamp(actual_end_sec),
                        text=orig_item.text.strip()
                    )
                )
                global_sub_idx += 1
                pbar.update(1)

        # 4. Xuất file âm thanh TTS hoàn chỉnh
        # Đảm bảo độ dài bao phủ toàn bộ video mà không làm cụt câu cuối
        final_track_duration_ms = max(int(total_duration_seconds * 1000), last_audio_end_ms)
        final_audio = master_track[:final_track_duration_ms]
        final_audio.export(str(output_audio_path), format="wav")
        logger.info(f"Đã tạo audio CapCut TTS hoàn chỉnh: {output_audio_path}")

        # 5. Xuất file SRT phụ đề đã đồng bộ
        if output_srt_path:
            output_srt_path = Path(output_srt_path).resolve()
            output_srt_path.parent.mkdir(parents=True, exist_ok=True)
            srt_blocks = [item.to_srt_block() for item in synced_subtitles]
            final_srt_text = "\n".join(srt_blocks).strip() + "\n"
            output_srt_path.write_text(final_srt_text, encoding="utf-8")
            logger.info(f"Đã lưu phụ đề đồng bộ ({len(synced_subtitles)} câu) tại: {output_srt_path}")

        return output_audio_path, synced_subtitles


# Alias để giữ tính tương thích ngược
CapCutTTSSynchronizer = VietnameseTTSSynchronizer
