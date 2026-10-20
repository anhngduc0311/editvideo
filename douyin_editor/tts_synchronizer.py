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

from config import PipelineConfig, TTSConfig, VOICE_PRESETS, get_voice_preset
from transcriber import SubtitleItem
from job_state import JobCancelled, check_cancelled, signature

from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter

# Nạp static_ffmpeg nếu có
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

logger = logging.getLogger(__name__)


class TTSTimingError(RuntimeError):
    """A phrase cannot fit its slot without excessive speech acceleration."""


class TTSServiceError(RuntimeError):
    """A provider-wide failure should stop the job instead of retrying every cue."""


class TTSTaskError(RuntimeError):
    """A rejected synthesis task can be retried with fewer phrases."""


def capcut_task_failure_detail(task: dict) -> str:
    """Extract diagnostics without exposing task tokens or signed audio URLs."""
    payload = task.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    parts = []
    for source in (task, payload):
        if isinstance(source, dict):
            for key in ("code", "error_code", "errmsg", "error_msg", "message", "reason"):
                value = source.get(key)
                if isinstance(value, (str, int)) and value != "":
                    parts.append(f"{key}={str(value)[:200]}")
    return "; ".join(parts) or "Máy chủ không cung cấp mã lỗi chi tiết."


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
        self.cancel_event = None
        from capcut_tts_api import CapCutClient
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "*/*"
        })
        self.client = CapCutClient(session=self.session, timeout=20)

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
        check_cancelled(self.cancel_event)
        speed = float(rate)
        if not 0.70 <= speed <= 1.35:
            raise ValueError("Tốc độ giọng CapCut phải trong khoảng 0.70–1.35.")

        final_voice = voice
        final_res_id = resource_id
        for p_key, p_val in VOICE_PRESETS.items():
            if voice in (p_key, p_val["voice"], p_val["name"]):
                final_voice = p_val["voice"]
                final_res_id = p_val["resource_id"]
                break

        for attempt in range(1, max_retries + 1):
            check_cancelled(self.cancel_event)
            try:
                # Use the SDK's TTS methods: the builder has no `rate` argument,
                # and query_tts_task supplies mode='tts' and the bind identity.
                resp_json = self.client.create_tts_task(
                    texts=texts,
                    voice=final_voice,
                    resource_id=final_res_id
                )

                if "data" not in resp_json or not resp_json["data"].get("tasks"):
                    raise RuntimeError(f"CapCut Task Creation failed: {resp_json.get('errmsg', 'Unknown')}")

                task_info = resp_json["data"]["tasks"][0]
                task_id = task_info["id"]
                task_token = task_info["token"]
                bind_id = task_info.get("bind_id") or resp_json["data"].get("bind_id") or ""

                # Polling chờ kết quả với chu kỳ thích ứng nhanh (0.35s)
                completed = False
                payload_data = None
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    time.sleep(0.35)
                    check_cancelled(self.cancel_event)
                    q_json = self.client.query_tts_task(task_id, task_token, bind_id=bind_id)

                    if q_json.get("data", {}).get("tasks"):
                        t_obj = q_json["data"]["tasks"][0]
                        status = str(t_obj.get("status", "")).lower()
                        if status in {"success", "succeed", "succeeded", "completed", "done"}:
                            raw_payload = t_obj.get("payload", {})
                            payload_data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                            completed = True
                            break
                        elif status in {"failed", "error", "cancelled", "canceled"}:
                            raise TTSTaskError("CapCut báo tác vụ tạo giọng thất bại. "
                                               + capcut_task_failure_detail(t_obj))

                if not completed or not payload_data:
                    raise TimeoutError("CapCut TTS polling timed out")

                # Tải song song toàn bộ audio streams qua ThreadPoolExecutor
                sub_list = payload_data.get("audio_subtitles", [])
                if not sub_list:
                    raise RuntimeError("CapCut hoàn tất nhưng không trả về audio.")

                def _fetch_single_audio(item_tuple):
                    check_cancelled(self.cancel_event)
                    idx, sub = item_tuple
                    t_text = sub.get("text", texts[idx] if idx < len(texts) else "")
                    audio_url = sub.get("speech_url") or sub.get("audio_url") or sub.get("url")
                    duration_ms = sub.get("duration", 0)

                    audio_bytes = None
                    if audio_url:
                        for dl_attempt in range(1, 4):
                            check_cancelled(self.cancel_event)
                            try:
                                audio_resp = self.session.get(audio_url, timeout=(5, 25))
                                if audio_resp.status_code == 200 and len(audio_resp.content) > 0:
                                    audio_bytes = audio_resp.content
                                    break
                            except Exception as dl_err:
                                if dl_attempt == 3:
                                    logger.warning(f"Lỗi tải audio câu '{t_text}' (Lần {dl_attempt}/3): {dl_err}")
                                time.sleep(0.5 * dl_attempt)

                    if audio_bytes and abs(speed - 1.0) >= 0.02:
                        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
                        audio = VietnameseTTSSynchronizer._speed_change_ffmpeg(audio, speed)
                        buffer = io.BytesIO()
                        audio.export(buffer, format="wav")
                        audio_bytes, duration_ms = buffer.getvalue(), len(audio)
                    return (idx, t_text, audio_bytes, duration_ms)

                workers = min(8, len(sub_list) or 1)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    fetched_items = list(pool.map(_fetch_single_audio, enumerate(sub_list)))

                # Sắp xếp đúng thứ tự ban đầu
                fetched_items.sort(key=lambda x: x[0])
                results = [(item[1], item[2], item[3]) for item in fetched_items]
                if not any(data for _, data, _ in results):
                    raise RuntimeError("Không tải được audio từ CapCut. Kiểm tra kết nối hoặc quyền truy cập dịch vụ.")

                return results

            except JobCancelled:
                raise
            except Exception as e:
                status_code = getattr(e, "status_code", None)
                response_data = getattr(e, "response_data", None) or {}
                detail = (str(response_data.get("errmsg", ""))[:180]
                          if isinstance(response_data, dict) else "")
                if isinstance(e, requests.RequestException):
                    detail = "Không kết nối được dịch vụ CapCut hoặc yêu cầu quá thời gian chờ."
                elif not detail:
                    detail = str(e)[:200]
                message = f"CapCut TTS{f' (HTTP {status_code})' if status_code else ''}: {detail}"
                logger.warning("Lần thử %s/%s: %s", attempt, max_retries, message)
                if isinstance(e, TTSTaskError):
                    raise
                if attempt == max_retries or status_code in (401, 403):
                    raise TTSServiceError(message + " Audio đã tạo được giữ lại; chạy tiếp sau khi khắc phục.") from e
                time.sleep(1.5)

        return [(t, None, 0) for t in texts]


def create_tts_engine(voice: str):
    if get_voice_preset(voice).get("provider") == "openvoice":
        from voice_clone import JapaneseCloneTTSEngine
        return JapaneseCloneTTSEngine()
    return CapCutTTSEngine()


class VietnameseTTSSynchronizer:
    """
    Module đọc phụ đề tiếng Việt bằng CapCut TTS chính chủ và đồng bộ chính xác vào timeline video.
    Đọc trọn vẹn từng câu đầy đủ ngữ điệu, giữ nguyên cao độ (pitch) và không bị ngắt cụt chữ.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tts_config: TTSConfig = config.tts_config
        self.engine = create_tts_engine(self.tts_config.voice)
        self.cancel_event = None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Làm sạch văn bản trước khi gửi đến CapCut TTS và đảm bảo kết thúc bằng dấu câu"""
        text = re.sub(r"[*#_~`]", "", text).strip()
        if not re.search(r"[\w\d\u00C0-\u1EF9]", text, re.UNICODE):
            return ""
        # Đảm bảo có dấu câu kết thúc để giọng đọc có ngữ điệu trọn vẹn
        if text[-1] not in ".!?。！？":
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
            sentence_parts = [p.strip() for p in re.split(r'(?<=[。！？])|(?<=[.!?…;\n])\s+', raw_text) if p.strip()]
            
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

        check_cancelled(self.cancel_event)
        self.engine.cancel_event = self.cancel_event
        total_ms = int(total_duration_seconds * 1000)
        logger.info(f"[Bước 4] Đang sinh giọng đọc CapCut ({self.tts_config.voice}) nói trọn vẹn từng câu...")

        # 1. Tách phụ đề thành từng câu ngắn độc lập để hiển thị và đọc từng câu riêng biệt
        split_subtitles = self.split_subtitles_into_short_sentences(subtitles)

        valid_items: List[Tuple[int, SubtitleItem, str]] = []
        for idx, item in enumerate(split_subtitles):
            cleaned = self._clean_text(item.text)
            if cleaned:
                valid_items.append((idx, item, cleaned))

        if not valid_items:
            raise RuntimeError("Không có câu phụ đề hợp lệ để lồng tiếng. Hãy kiểm tra bản dịch.")

        # Smaller, serial CapCut tasks reduce request pressure. Task failures
        # split adaptively; authentication/service failures still stop the job.
        is_clone = get_voice_preset(self.tts_config.voice).get("provider") == "openvoice"
        batch_size = 40 if is_clone else 8
        audio_dict: Dict[int, AudioSegment] = {}
        cache_dir = output_audio_path.parent / "tts_phrases"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_signature = (self.engine._model_signature()
                           if get_voice_preset(self.tts_config.voice).get("provider") == "openvoice" else None)

        def cache_path(text):
            return cache_dir / (signature(["tts-v2", text, self.tts_config.voice,
                                          self.tts_config.resource_id, self.tts_config.rate,
                                          model_signature]) + ".wav")

        def accept_results(b_items, results):
            # Text identity prevents a partial/reordered provider response shifting audio.
            identity = lambda text: re.sub(r"[\W_]+", "", text.casefold())
            by_text = {identity(text): data for text, data, _ in results if data}
            for orig_idx, _, text in b_items:
                data = by_text.get(identity(text))
                if not data:
                    continue
                try:
                    seg = AudioSegment.from_file(io.BytesIO(data))
                    if len(seg) <= 0:
                        continue
                    temporary = cache_path(text).with_suffix(".tmp")
                    with temporary.open("wb") as stream:
                        seg.export(stream, format="wav")
                    temporary.replace(cache_path(text))
                    audio_dict[orig_idx] = seg
                except Exception as error:
                    logger.warning("Không đọc được audio câu %s: %s", orig_idx + 1, str(error)[-250:])

        pending = []
        for orig_idx, item, text in valid_items:
            check_cancelled(self.cancel_event)
            try:
                seg = AudioSegment.from_file(io.BytesIO(cache_path(text).read_bytes()), format="wav")
                if len(seg) <= 0:
                    raise ValueError("Empty cached phrase")
                audio_dict[orig_idx] = seg
            except Exception:
                pending.append((orig_idx, item, text))
        batches = []
        batch = []
        batch_chars = 0
        for item in pending:
            if batch and (len(batch) >= batch_size or (not is_clone and batch_chars + len(item[2]) > 1500)):
                batches.append(batch)
                batch, batch_chars = [], 0
            batch.append(item)
            batch_chars += len(item[2])
        if batch:
            batches.append(batch)

        def _synthesize_batch_worker(batch_data):
            check_cancelled(self.cancel_event)
            b_items = batch_data
            b_texts = [text for _, _, text in b_items]
            try:
                results = self.engine.synthesize_phrases(
                    texts=b_texts, voice=self.tts_config.voice,
                    resource_id=self.tts_config.resource_id, rate=self.tts_config.rate,
                    max_retries=2)
            except (JobCancelled, TTSServiceError):
                raise
            except TTSTaskError as error:
                if len(b_items) > 1:
                    logger.warning("CapCut từ chối đoạn %s câu; chia nhỏ và thử lại: %s", len(b_items), error)
                    midpoint = len(b_items) // 2
                    # Persist successful halves immediately, even if a later
                    # half encounters a service failure or cancellation.
                    for half in (b_items[:midpoint], b_items[midpoint:]):
                        half_items, half_results = _synthesize_batch_worker(half)
                        accept_results(half_items, half_results)
                    return b_items, []
                logger.warning("CapCut chưa tạo được câu %s, sẽ thử lại: %s", b_items[0][1].index, error)
                results = []
            except Exception as error:
                logger.warning("TTS batch lỗi, sẽ thử lại từng câu: %s", error)
                results = []
            check_cancelled(self.cancel_event)
            return b_items, results

        with tqdm(total=len(valid_items), desc="[Bước 4.1] CapCut TTS Sinh Giọng Đầy Đủ Câu", leave=False) as pbar:
            if batches:
                if is_clone:
                    with ThreadPoolExecutor(max_workers=min(3, len(batches))) as pool:
                        for b_items, results in pool.map(_synthesize_batch_worker, batches):
                            accept_results(b_items, results)
                            pbar.update(len(b_items))
                else:
                    for batch in batches:
                        b_items, results = _synthesize_batch_worker(batch)
                        accept_results(b_items, results)
                        pbar.update(len(b_items))
            for _ in range(2):
                missing = [item for item in valid_items if item[0] not in audio_dict]
                if not missing:
                    break
                for item in missing:
                    b_items, results = _synthesize_batch_worker([item])
                    accept_results(b_items, results)
            missing = [str(item.index) for idx, item, _ in valid_items if idx not in audio_dict]
            if missing:
                preview = ", ".join(missing[:10]) + (", …" if len(missing) > 10 else "")
                raise RuntimeError(f"TTS chưa tạo được audio cho {len(missing)}/{len(valid_items)} câu. "
                                   "Câu lỗi: " + preview +
                                   ". Chạy lại để thử các câu lỗi; audio thành công đã được lưu.")

        # 3. Prepare speech, then schedule actual durations. Character-based split
        # boundaries are estimates, not hard deadlines for individual phrases.
        synced_subtitles: List[SubtitleItem] = []
        global_sub_idx = 1
        prepared = []
        previous_preferred_ms = 0
        for i, (orig_idx, orig_item, _) in enumerate(valid_items):
            check_cancelled(self.cancel_event)
            audio_seg = audio_dict[orig_idx]
            start_ms = round(orig_item.start_seconds * 1000)
            if start_ms < 0 or orig_item.end_seconds <= orig_item.start_seconds:
                raise TTSTimingError(f"Câu {orig_item.index} có mốc thời gian không hợp lệ.")
            # STT blocks may overlap; preserve narration order even when an
            # estimated split extends past the following block's start.
            start_ms = max(start_ms, previous_preferred_ms)
            previous_preferred_ms = start_ms
            next_start = (round(valid_items[i + 1][1].start_seconds * 1000)
                          if i + 1 < len(valid_items) else total_ms)
            slot_ms = max(0, next_start - start_ms)
            if len(audio_seg) > slot_ms:
                ratio = min(len(audio_seg) / max(slot_ms - 30, 1), 1.25)
                audio_seg = self._speed_change_ffmpeg(audio_seg, ratio)
            prepared.append((orig_item, start_ms, audio_seg))

        # Reserve enough space for the remaining speech at the end. This lets
        # dense groups borrow nearby silence and recover their original timing.
        total_ms = max(total_ms, sum(len(audio) for _, _, audio in prepared))
        latest_starts = [0] * len(prepared)
        cursor_ms = total_ms
        for i in range(len(prepared) - 1, -1, -1):
            cursor_ms -= len(prepared[i][2])
            latest_starts[i] = cursor_ms
        master_track = AudioSegment.silent(duration=total_ms)
        previous_end_ms = 0

        with tqdm(total=len(valid_items), desc="[Bước 4.2] Căn Chỉnh Khớp Timeline Tự Nhiên", leave=False) as pbar:
            for i, (orig_item, preferred_start_ms, audio_seg) in enumerate(prepared):
                check_cancelled(self.cancel_event)
                seg_len_ms = len(audio_seg)
                target_start_ms = max(previous_end_ms, min(preferred_start_ms, latest_starts[i]))
                if abs(target_start_ms - preferred_start_ms) > 500:
                    logger.info("Căn lại câu %s: %.2fs → %.2fs để giữ trọn lời đọc.",
                                orig_item.index, preferred_start_ms / 1000, target_start_ms / 1000)
                previous_end_ms = target_start_ms + seg_len_ms

                # Đặt audio vào master track
                master_track = master_track.overlay(audio_seg, position=target_start_ms)

                actual_start_sec = target_start_ms / 1000.0
                actual_end_sec = (target_start_ms + seg_len_ms) / 1000.0

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
        check_cancelled(self.cancel_event)
        final_audio = master_track[:total_ms]
        temporary_audio = output_audio_path.with_suffix(".tmp")
        with temporary_audio.open("wb") as stream:
            final_audio.export(stream, format="wav")
        temporary_audio.replace(output_audio_path)
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
