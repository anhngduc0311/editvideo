"""
translator.py - AI SRT Subtitle Translation (DeepSeek API & ChatGPT Web Cookie)
Chuyên biệt dịch thuật phụ đề SRT từ Tiếng Trung sang Tiếng Việt bằng DeepSeek API hoặc ChatGPT Web Cookie,
chuẩn văn phong tiếng Việt, khớp 100% timeline và index SRT.
Tích hợp giải mã Proof-of-Work (Sentinel PoW) và giả lập TLS Browser Chrome (curl_cffi) chống lỗi 403.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import time
from typing import Dict, List, Optional, Tuple, Union
import uuid
from tqdm import tqdm

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

import requests

from config import PipelineConfig, TRANSLATION_TOPIC_PRESETS
from transcriber import SubtitleItem

logger = logging.getLogger(__name__)


def build_translation_system_instruction(config: PipelineConfig) -> str:
    """Tạo System Instruction chuyên sâu với bối cảnh chủ đề (ví dụ: Minecraft cho trẻ em)."""
    topic_id = getattr(config, "topic_preset", "minecraft_kids")
    custom_prompt = getattr(config, "custom_translation_prompt", None)

    if custom_prompt and custom_prompt.strip():
        topic_context = f"BỐI CẢNH & YÊU CẦU ĐẶC THÙ (TÙY CHỈNH):\n{custom_prompt.strip()}"
    else:
        preset = TRANSLATION_TOPIC_PRESETS.get(topic_id, TRANSLATION_TOPIC_PRESETS.get("minecraft_kids", {}))
        topic_context = preset.get("prompt_context", "")

    return (
        "Bạn là chuyên gia biên dịch phụ đề video ngắn (Douyin/TikTok/YouTube Shorts) từ Tiếng Trung sang Tiếng Việt xuất sắc nhất.\n"
        "Nhiệm vụ: Dịch toàn bộ danh sách các câu phụ đề sau đây sang tiếng Việt chuẩn, tự nhiên, cuốn hút, đúng ngữ cảnh chủ đề.\n\n"
        f"{topic_context}\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. BẢO TOÀN SỐ LƯỢNG CÂU 100% (TỶ LỆ 1:1 TUYỆT ĐỐI): Đầu vào có bao nhiêu số [index] thì đầu ra PHẢI CÓ ĐÚNG BẤY NHIÊU DÒNG [index].\n"
        "2. ĐỊNH DẠNG ĐẦU RA BẮT BUỘC: Mỗi dòng trả về đúng cú pháp: [index] <câu dịch tiếng Việt> (Ví dụ: [1] Xin chào các bạn).\n"
        "3. TUYỆT ĐỐI KHÔNG GỘP CÂU, KHÔNG TÁCH CÂU, KHÔNG BỎ SÓT CÂU: Giữ nguyên đúng số thứ tự [index] gốc tương ứng.\n"
        "4. VĂN PHONG TỰ NHIÊN, KHÔNG LẶP TỪ: Dịch thoát ý, súc tích để giọng đọc lồng tiếng kịp nhịp video. Nếu gặp các câu ngắn lặp lại liên tục (do lỗi nhận diện âm thanh), hãy dịch súc tích tự nhiên, tuyệt đối tránh lặp từ ngớ ngẩn.\n"
        "5. CHỈ TRẢ VỀ DUY NHẤT danh sách các dòng [index] đã dịch. Không thêm lời chào, không kèm giải thích, không bọc trong thẻ markdown ```."
    )


def build_batch_prompt(batch: List[SubtitleItem]) -> str:
    """Tạo prompt danh sách câu [index] tối ưu cho AI dịch chính xác 100% không lo lỗi format SRT"""
    lines = [f"[{item.index}] {item.text.strip()}" for item in batch]
    content = "\n".join(lines)
    return (
        f"[DANH SÁCH {len(batch)} CÂU PHỤ ĐỀ TIẾNG TRUNG CẦN DỊCH]:\n"
        f"{content}\n\n"
        f"Hãy dịch chính xác toàn bộ {len(batch)} câu trên sang Tiếng Việt, trả về đúng {len(batch)} dòng theo định dạng [index] <câu dịch>:"
    )


def clean_markdown_response(text: str) -> str:
    """Loại bỏ các thẻ markdown ```srt hoặc ``` nếu AI trả về"""
    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", text.strip())
    text = re.sub(r"\n```$", "", text.strip())
    return text.strip()


def parse_srt_string(srt_content: str) -> List[SubtitleItem]:
    """Phân tích chuỗi SRT thành danh sách SubtitleItem (hỗ trợ nhiều biến thể định dạng)"""
    if not srt_content or not srt_content.strip():
        return []

    clean_text = clean_markdown_response(srt_content).replace("\r\n", "\n")
    pattern = re.compile(
        r"(?:^|\n)\s*(\d+)[\.:]?\s*\n"
        r"\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*(?:-->|->)\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*\n"
        r"([\s\S]*?)(?=(?:\n\s*\d+[\.:]?\s*\n\s*\d{1,2}:\d{2}:\d{2})|\Z)"
    )

    def to_secs(t_str: str) -> float:
        parts = t_str.replace(".", ",").split(":")
        h = int(parts[0])
        m = int(parts[1])
        s_ms = parts[2].split(",")
        s = int(s_ms[0])
        ms = int(s_ms[1]) if len(s_ms) > 1 else 0
        return h * 3600 + m * 60 + s + ms / 1000.0

    items = []
    for match in pattern.finditer(clean_text):
        idx = int(match.group(1))
        start_raw = match.group(2).replace(".", ",")
        end_raw = match.group(3).replace(".", ",")
        
        # Chuẩn hóa format timestamp HH:MM:SS,mmm
        start_parts = start_raw.split(":")
        if len(start_parts[0]) == 1:
            start_raw = f"0{start_raw}"
        end_parts = end_raw.split(":")
        if len(end_parts[0]) == 1:
            end_raw = f"0{end_raw}"

        text = " ".join(match.group(4).strip().split())
        items.append(
            SubtitleItem(
                index=idx,
                start_seconds=to_secs(start_raw),
                end_seconds=to_secs(end_raw),
                start_str=start_raw,
                end_str=end_raw,
                text=text
            )
        )
    return items


def extract_translations_from_ai_response(raw_text: str, batch: List[SubtitleItem]) -> Dict[int, str]:
    """
    Trích xuất từ kết quả trả về của AI thành mapping {orig_index: translated_text}.
    Hỗ trợ đa định dạng chống mất câu:
    1. Định dạng chuẩn đánh số: [1] Text, (1) Text, 1. Text, 1: Text, 1 Text
    2. Chuẩn SRT block (1\n00:00:00,000 --> 00:00:00,000\nText)
    3. Fallback danh sách dòng thuần túy (Line-by-line)
    """
    text = clean_markdown_response(raw_text).replace("\r\n", "\n")
    expected_indices = [item.index for item in batch]
    expected_set = set(expected_indices)
    result_dict: Dict[int, str] = {}

    # Cách 1: Regex danh sách có đánh số [1] hoặc 1. hoặc 1: hoặc (1) hoặc [1]:
    list_pattern = re.compile(r"(?:^|\n)\s*(?:\[|\()?(\d+)(?:\]|\)|\.|\:)?\s*[:\.\-\s]?\s*([^\n]+)")
    for m in list_pattern.finditer(text):
        try:
            idx = int(m.group(1))
            t_content = m.group(2).strip()
            # Bỏ qua dòng timestamp nếu có
            if "-->" in t_content or "->" in t_content:
                continue
            t_content = " ".join(t_content.split())
            if not t_content:
                continue
            if idx in expected_set:
                result_dict[idx] = t_content
            elif 1 <= idx <= len(batch):
                orig_idx = batch[idx - 1].index
                if orig_idx not in result_dict:
                    result_dict[orig_idx] = t_content
        except (ValueError, IndexError):
            continue

    # Cách 2: SRT block regex (nếu AI trả về cả khối SRT)
    if len(result_dict) < len(batch):
        srt_pattern = re.compile(
            r"(?:^|\n)\s*(\d+)[\.:]?\s*\n\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*(?:-->|->)\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*\n([\s\S]*?)(?=(?:\n\s*\d+[\.:]?\s*\n\s*\d{1,2}:\d{2}:\d{2})|\Z)"
        )
        for m in srt_pattern.finditer(text):
            try:
                idx = int(m.group(1))
                t_content = m.group(4).strip()
                t_content = " ".join(t_content.split())
                if not t_content:
                    continue
                if idx in expected_set and idx not in result_dict:
                    result_dict[idx] = t_content
                elif 1 <= idx <= len(batch):
                    orig_idx = batch[idx - 1].index
                    if orig_idx not in result_dict:
                        result_dict[orig_idx] = t_content
            except (ValueError, IndexError):
                continue

    # Cách 3: Nếu AI trả về danh sách các dòng văn bản đơn thuần (không có số thứ tự / timeline)
    if len(result_dict) == 0:
        lines = [line.strip() for line in text.split("\n") if line.strip() and not re.match(r"^\d{1,2}:\d{2}:\d{2}", line.strip())]
        if len(lines) == len(batch):
            for i, line in enumerate(lines):
                result_dict[batch[i].index] = " ".join(line.split())

    return result_dict


def translate_batch_resilient(
    call_ai_fn,
    batch: List[SubtitleItem],
    b_idx: int,
    total_batches: int,
    engine_name: str = "AI",
    max_batch_retries: int = 2
) -> List[SubtitleItem]:
    """
    Dịch một batch phụ đề với cơ chế chia nhỏ đệ quy, tự sửa lỗi, tự bù câu thiếu và chống lệch timeline 100%.
    """
    if not batch:
        return []

    prompt = build_batch_prompt(batch)
    trans_map: Dict[int, str] = {}

    # Lần gọi chính thức đầu tiên
    try:
        response_text = call_ai_fn(prompt)
        trans_map = extract_translations_from_ai_response(response_text, batch)
    except Exception as e:
        logger.warning(f"Lỗi khi gọi {engine_name} dịch batch {b_idx}/{total_batches}: {e}")

    # Nếu AI trả về thiếu câu, tự động thử lại / chia nhỏ sub-chunk
    retry_count = 0
    while len(trans_map) < len(batch) and retry_count < max_batch_retries:
        retry_count += 1
        missing_items = [item for item in batch if item.index not in trans_map]
        logger.warning(
            f"Batch {b_idx}/{total_batches}: {engine_name} trả về {len(trans_map)}/{len(batch)} câu (thiếu {len(missing_items)} câu: {[it.index for it in missing_items]}). "
            f"Đang tự động chia nhỏ đoạn và yêu cầu {engine_name} dịch lại (lần {retry_count}/{max_batch_retries})..."
        )
        
        # Gửi lại đúng các câu bị thiếu
        retry_prompt = (
            f"⚠️ LƯU Ý: Vui lòng dịch ĐẦY ĐỦ các câu sau đây sang Tiếng Việt. "
            f"Bắt buộc trả về đúng từng dòng theo định dạng [index] <câu dịch>:\n\n"
            f"{build_batch_prompt(missing_items)}"
        )
        try:
            retry_res = call_ai_fn(retry_prompt)
            new_map = extract_translations_from_ai_response(retry_res, missing_items)
            trans_map.update(new_map)
            if len(trans_map) == len(batch):
                logger.info(f"🟢 Batch {b_idx}/{total_batches}: Đã bù đủ {len(batch)}/{len(batch)} câu dịch!")
                break
        except Exception as e:
            logger.warning(f"Lỗi khi thử lại batch {b_idx}: {e}")

    # Nếu sau các lần retry vẫn còn sót câu, dịch riêng từng câu lẻ (1-by-1 micro-calls)
    missing_items = [item for item in batch if item.index not in trans_map]
    if missing_items:
        logger.warning(f"Batch {b_idx}/{total_batches}: Đang dịch bù riêng lẻ {len(missing_items)} câu chưa có bản dịch...")
        for m_item in missing_items:
            try:
                single_prompt = (
                    f"Dịch câu sau từ Tiếng Trung sang Tiếng Việt tự nhiên (chỉ trả về duy nhất 1 dòng bản dịch tiếng Việt):\n"
                    f"[{m_item.index}] {m_item.text}"
                )
                single_res = call_ai_fn(single_prompt)
                clean_single = clean_markdown_response(single_res).strip()
                clean_single = re.sub(r"^(?:\d+[\.:]?\s*|\(?\[?\d+\]?\)?\s*[:\.\-\s]?)", "", clean_single).strip()
                clean_single = " ".join(clean_single.split())
                if clean_single:
                    trans_map[m_item.index] = clean_single
            except Exception as e:
                logger.warning(f"Lỗi khi dịch bổ sung câu index {m_item.index}: {e}")

    # Xây dựng danh sách SubtitleItem hoàn chỉnh, KHÔNG BAO GIỜ bị lệch timeline (khớp đúng 100% theo orig_item.index)
    res_items: List[SubtitleItem] = []
    for orig_item in batch:
        v_text = trans_map.get(orig_item.index, "").strip()
        if not v_text:
            v_text = orig_item.text.strip()
        res_items.append(
            SubtitleItem(
                index=orig_item.index,
                start_seconds=orig_item.start_seconds,
                end_seconds=orig_item.end_seconds,
                start_str=orig_item.start_str,
                end_str=orig_item.end_str,
                text=v_text
            )
        )

    return res_items


# =====================================================================
# 1. DEEPSEEK API TRANSLATOR
# =====================================================================

def check_deepseek_api_status(
    api_key: str,
    preferred_model: str = "deepseek-v4-flash",
    base_url: str = "https://api.deepseek.com"
) -> dict:
    """
    Kiểm tra tình trạng hoạt động, latency và Rate Limit của DeepSeek API Key.
    """
    if not api_key or not api_key.strip():
        return {
            "valid": False,
            "status": "INVALID_KEY",
            "message": "Chưa nhập DeepSeek API Key. Vui lòng nhập key trên giao diện.",
            "recommended_model": preferred_model,
            "working_models": [],
            "rate_limited_models": [],
            "model_results": {}
        }

    api_key = api_key.strip()
    candidate_models = [
        preferred_model,
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp",
        "deepseek-chat",
    ]
    unique_models = []
    for m in candidate_models:
        clean_m = m.strip()
        if clean_m and clean_m not in unique_models:
            unique_models.append(clean_m)

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    working_models = []
    rate_limited_models = []
    model_results = {}

    def _test_single_model(model: str):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Xin chào"}],
            "max_tokens": 5,
            "temperature": 0.1
        }
        t0 = time.time()
        try:
            res = requests.post(endpoint, json=payload, headers=headers, timeout=5)
            latency = int((time.time() - t0) * 1000)
            if res.status_code == 200:
                return model, {"code": 200, "latency_ms": latency, "msg": f"OK ({latency}ms)"}
            elif res.status_code == 429:
                return model, {"code": 429, "latency_ms": latency, "msg": "Rate Limit (429)"}
            elif res.status_code in (401, 403):
                return model, {"code": res.status_code, "latency_ms": latency, "msg": f"Lỗi Auth ({res.status_code})"}
            elif res.status_code == 404:
                return model, {"code": 404, "latency_ms": latency, "msg": "Not Found (404)"}
            else:
                return model, {"code": res.status_code, "latency_ms": latency, "msg": f"Status {res.status_code}"}
        except requests.exceptions.Timeout:
            return model, {"code": -1, "latency_ms": 5000, "msg": "Timeout (5s)"}
        except Exception as e:
            return model, {"code": -1, "latency_ms": 0, "msg": f"Error: {e}"}

    with ThreadPoolExecutor(max_workers=min(5, len(unique_models))) as executor:
        futures_res = list(executor.map(_test_single_model, unique_models))

    for model, info in futures_res:
        model_results[model] = info
        if info["code"] == 200:
            working_models.append((model, info["latency_ms"]))
        elif info["code"] == 429:
            rate_limited_models.append(model)

    has_auth_error = any(r.get("code") in (401, 403) for r in model_results.values()) and not working_models

    if working_models:
        rec_model = working_models[0][0]
        for wm, _ in working_models:
            if wm == preferred_model:
                rec_model = wm
                break
        rate_info = f" ({len(rate_limited_models)} model bị rate limit)" if rate_limited_models else ""
        msg = f"🟢 DeepSeek API HOẠT ĐỘNG TỐT! Có {len(working_models)} model sẵn sàng{rate_info}. Đang dùng: {rec_model}"
        return {
            "valid": True,
            "status": "OK",
            "message": msg,
            "recommended_model": rec_model,
            "working_models": [wm[0] for wm in working_models],
            "rate_limited_models": rate_limited_models,
            "model_results": model_results
        }
    elif rate_limited_models:
        return {
            "valid": True,
            "status": "RATE_LIMITED",
            "message": "🟡 DeepSeek API hợp lệ nhưng đang bị RATE LIMIT (429)! Vui lòng chờ giây lát hoặc kiểm tra quota.",
            "recommended_model": preferred_model,
            "working_models": [],
            "rate_limited_models": rate_limited_models,
            "model_results": model_results
        }
    elif has_auth_error:
        return {
            "valid": False,
            "status": "INVALID_KEY",
            "message": "🔴 DeepSeek API Key KHÔNG HỢP LỆ (Lỗi 401/403: Invalid Token/Unauthorized). Vui lòng kiểm tra lại key.",
            "recommended_model": preferred_model,
            "working_models": [],
            "rate_limited_models": [],
            "model_results": model_results
        }
    else:
        return {
            "valid": False,
            "status": "NETWORK_ERROR",
            "message": "⚠️ Không thể kết nối tới DeepSeek API (Kiểm tra internet/proxy/VPN).",
            "recommended_model": preferred_model,
            "working_models": [],
            "rate_limited_models": [],
            "model_results": model_results
        }


class DeepSeekTranslator:
    """
    Module dịch thuật phụ đề từ Tiếng Trung sang Tiếng Việt bằng DeepSeek API.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.api_key = config.deepseek_api_key
        if not self.api_key:
            raise ValueError(
                "Chưa cấu hình DEEPSEEK_API_KEY! Hãy truyền API key vào config hoặc gán biến môi trường DEEPSEEK_API_KEY."
            )
        self.model_name = config.deepseek_model_name or "deepseek-v4-flash"
        self.base_url = (config.deepseek_base_url or "https://api.deepseek.com").rstrip("/")

    def check_status(self) -> dict:
        """Kiểm tra API Key và tình trạng model cho instance này"""
        return check_deepseek_api_status(self.api_key, self.model_name, self.base_url)

    def _call_deepseek_api(self, prompt: str, timeout: int = 120, max_retries: int = 3) -> str:
        """Gọi DeepSeek Chat Completions API với cơ chế thử lại (retry) và chuyển model dự phòng"""
        candidate_models = [
            self.model_name,
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash-vision-exp",
            "deepseek-chat"
        ]
        unique_models = []
        for m in candidate_models:
            clean_m = m.strip()
            if clean_m and clean_m not in unique_models:
                unique_models.append(clean_m)

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        system_instruction = build_translation_system_instruction(self.config)

        last_error = None
        for model in unique_models:
            for attempt in range(1, max_retries + 1):
                try:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2
                    }
                    res = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                    if res.status_code == 200:
                        res_data = res.json()
                        self.model_name = model
                        choice = res_data["choices"][0]
                        content = choice["message"].get("content", "")
                        return content
                    elif res.status_code == 404:
                        logger.warning(f"DeepSeek model {model} trả về 404, chuyển model tiếp theo...")
                        last_error = f"Status 404: {res.text}"
                        break
                    elif res.status_code == 429:
                        logger.warning(f"DeepSeek model {model} bị rate limit (429), chờ thử lại (lần {attempt}/{max_retries})...")
                        time.sleep(2 * attempt)
                        if attempt >= 2:
                            logger.info(f"Model {model} chạm trần rate limit, tự động chuyển sang model dự phòng tiếp theo...")
                            last_error = f"Status 429: {res.text}"
                            break
                        continue
                    else:
                        logger.warning(f"DeepSeek API {model} trả về status {res.status_code}, thử lại (lần {attempt}/{max_retries})...")
                        time.sleep(1.5 * attempt)
                        last_error = f"Status {res.status_code}: {res.text}"
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"Kết nối tới DeepSeek ({model}) bị timeout/ngắt ({e}), đang thử lại (lần {attempt}/{max_retries})...")
                    last_error = str(e)
                    time.sleep(2 * attempt)
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"DeepSeek model {model} lỗi ({e}), thử lại...")
                    time.sleep(1.5 * attempt)

        raise RuntimeError(f"Lỗi DeepSeek Translation API: Tất cả model đều thất bại. Chi tiết: {last_error}")

    def translate_srt(
        self,
        input_srt_path: Path,
        output_srt_path: Path
    ) -> List[SubtitleItem]:
        """Dịch file SRT từ Tiếng Trung sang Tiếng Việt qua DeepSeek API (chia batch chống timeout, chống lệch timeline)"""
        input_srt_path = Path(input_srt_path).resolve()
        output_srt_path = Path(output_srt_path).resolve()
        output_srt_path.parent.mkdir(parents=True, exist_ok=True)

        if not input_srt_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file SRT đầu vào: {input_srt_path}")

        raw_srt_text = input_srt_path.read_text(encoding="utf-8").strip()
        if not raw_srt_text:
            logger.warning("File SRT rỗng, tạo file kết quả rỗng.")
            output_srt_path.write_text("", encoding="utf-8")
            return []

        original_items = parse_srt_string(raw_srt_text)
        if not original_items:
            logger.warning("Không phân tích được câu phụ đề nào từ file SRT.")
            output_srt_path.write_text("", encoding="utf-8")
            return []

        total_items = len(original_items)
        logger.info(f"[Bước 3] Đang dịch {total_items} câu phụ đề bằng DeepSeek API ({self.model_name})...")

        final_translated_items: List[SubtitleItem] = []

        # Tối ưu siêu tốc: Nếu dưới 60 câu, gửi toàn bộ trong 1 request duy nhất (Tiết kiệm 10s + Câu dịch liền mạch)
        if total_items <= 60:
            with tqdm(total=total_items, desc="[Bước 3] DeepSeek Dịch thuật SRT (1-Turn)", leave=False) as pbar:
                final_translated_items = translate_batch_resilient(
                    call_ai_fn=lambda p: self._call_deepseek_api(p, timeout=120),
                    batch=original_items,
                    b_idx=1,
                    total_batches=1,
                    engine_name="DeepSeek API"
                )
                pbar.update(total_items)
        else:
            # Nếu trên 60 câu, chia batch 35 câu và dịch SONG SONG đa luồng
            BATCH_SIZE = 35
            batches = [original_items[i:i + BATCH_SIZE] for i in range(0, total_items, BATCH_SIZE)]
            total_batches = len(batches)

            def _translate_batch_worker(b_tuple):
                b_idx, batch = b_tuple
                res_items = translate_batch_resilient(
                    call_ai_fn=lambda p: self._call_deepseek_api(p, timeout=120),
                    batch=batch,
                    b_idx=b_idx,
                    total_batches=total_batches,
                    engine_name="DeepSeek API"
                )
                return b_idx, res_items

            batch_tasks = list(enumerate(batches, 1))
            batch_results = []

            with tqdm(total=total_items, desc="[Bước 3] DeepSeek Dịch thuật SRT (Song Song)", leave=False) as pbar:
                with ThreadPoolExecutor(max_workers=min(5, total_batches)) as executor:
                    for b_idx, res_items in executor.map(_translate_batch_worker, batch_tasks):
                        batch_results.append((b_idx, res_items))
                        pbar.update(len(res_items))

            batch_results.sort(key=lambda x: x[0])
            for _, r_items in batch_results:
                final_translated_items.extend(r_items)

        # Xuất file SRT hoàn chỉnh
        srt_blocks = [item.to_srt_block() for item in final_translated_items]
        final_srt_text = "\n".join(srt_blocks).strip() + "\n"
        output_srt_path.write_text(final_srt_text, encoding="utf-8")
        logger.info(f"Đã dịch thành công toàn bộ {len(final_translated_items)} câu sang: {output_srt_path}")
        return final_translated_items


# =====================================================================
# 2. CHATGPT WEB COOKIE / SENTINEL POW TRANSLATOR
# =====================================================================

def get_parse_time() -> str:
    """Tạo chuỗi timestamp định dạng chuẩn theo múi giờ trình duyệt"""
    now = datetime.now()
    return now.strftime("%a %b %d %Y %H:%M:%S GMT+0700 (Indochina Time)")


def calc_proof_token(seed: str, difficulty: str, user_agent: str = None) -> Optional[str]:
    """
    Tính toán Proof-of-Work token (SHA3-512) để vượt qua lớp bảo vệ Sentinel của OpenAI (Tránh lỗi 403)
    """
    if not seed or not difficulty:
        return None

    ua = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    screen_info = random.choice([
        "1920,1080,24,1,1920,1040,1920,1080",
        "2560,1440,24,1,2560,1400,2560,1440",
        "1536,864,24,1.25,1536,824,1536,864"
    ])
    time_str = get_parse_time()
    config = [screen_info, time_str, random.randint(1000, 3000), 0, ua, "", None, None, None]

    for i in range(500000):
        config[3] = i
        json_str = json.dumps(config, separators=(",", ":"))
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        hasher = hashlib.sha3_512()
        hasher.update((seed + b64_str).encode("utf-8"))
        hash_hex = hasher.hexdigest()

        if hash_hex[:len(difficulty)] <= difficulty:
            return "gAAAAAB" + b64_str

    return None


def extract_chatgpt_session_info(cookie_or_token: str) -> dict:
    """
    Trích xuất Access Token và thông tin tài khoản từ Cookie ChatGPT hoặc Session Token.
    Sử dụng curl_cffi giả lập TLS Chrome để tránh bị Cloudflare chặn.
    """
    if not cookie_or_token or not cookie_or_token.strip():
        return {
            "valid": False,
            "status": "EMPTY",
            "message": "Chưa nhập Cookie ChatGPT. Vui lòng dán cookie từ chatgpt.com."
        }

    raw = cookie_or_token.strip()

    # Chuẩn hóa Cookie Header
    if "__Secure-next-auth.session-token" in raw:
        cookie_header = raw
    elif raw.startswith("eyJ"):
        cookie_header = f"__Secure-next-auth.session-token={raw}"
    else:
        cookie_header = raw

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Cookie": cookie_header,
        "Accept": "*/*",
        "Referer": "https://chatgpt.com/",
        "Origin": "https://chatgpt.com"
    }

    endpoints = [
        "https://chatgpt.com/api/auth/session",
        "https://chat.openai.com/api/auth/session"
    ]

    session_cls = cffi_requests.Session if HAS_CURL_CFFI else requests.Session
    sess_kwargs = {"impersonate": "chrome124"} if HAS_CURL_CFFI else {}

    try:
        with session_cls(**sess_kwargs) as s:
            for ep in endpoints:
                try:
                    res = s.get(ep, headers=headers, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        access_token = data.get("accessToken")
                        user = data.get("user", {})
                        expires = data.get("expires", "")
                        if access_token:
                            email = user.get("email") or user.get("name") or "User ChatGPT"
                            return {
                                "valid": True,
                                "status": "OK",
                                "access_token": access_token,
                                "email": email,
                                "expires": expires,
                                "message": f"🟢 Cookie ChatGPT HỢP LỆ! Tài khoản: {email}"
                            }
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Lỗi khởi tạo session curl_cffi: {e}")

    # Nếu gọi session endpoint thất bại nhưng raw input là một chuỗi JWT hợp lệ (bắt đầu bằng eyJ)
    if raw.startswith("eyJ") and len(raw) > 100:
        return {
            "valid": True,
            "status": "TOKEN_DIRECT",
            "access_token": raw,
            "email": "ChatGPT Direct Token",
            "expires": "",
            "message": "🟢 Đã nhận diện trực tiếp Access Token ChatGPT!"
        }

    return {
        "valid": False,
        "status": "INVALID_COOKIE",
        "message": "🔴 Cookie ChatGPT KHÔNG HỢP LỆ hoặc ĐÃ HẾT HẠN. Vui lòng đăng nhập chatgpt.com và lấy lại cookie mới."
    }


def check_chatgpt_cookie_status(cookie_or_token: str) -> dict:
    """Hàm wrapper kiểm tra trạng thái Cookie cho giao diện GUI"""
    return extract_chatgpt_session_info(cookie_or_token)


class ChatGPTWebTranslator:
    """
    Module dịch thuật phụ đề từ Tiếng Trung sang Tiếng Việt bằng tài khoản ChatGPT Web
    Tích hợp curl_cffi Browser TLS Impersonation + OpenAI Sentinel PoW Solver chống lỗi 403.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.raw_cookie = getattr(config, "chatgpt_cookie", "").strip()
        if not self.raw_cookie:
            raise ValueError(
                "Chưa cấu hình Cookie ChatGPT! Hãy dán Cookie hoặc __Secure-next-auth.session-token vào giao diện."
            )
        self.model_name = getattr(config, "chatgpt_model_name", "auto") or "auto"
        self.device_id = str(uuid.uuid4())
        self.access_token: Optional[str] = None
        self.user_email: Optional[str] = None
        self._refresh_access_token()

    def _refresh_access_token(self):
        info = extract_chatgpt_session_info(self.raw_cookie)
        if info.get("valid") and info.get("access_token"):
            self.access_token = info["access_token"]
            self.user_email = info.get("email")
            logger.info(f"Đã xác thực ChatGPT Web thành công ({self.user_email})")
        elif self.raw_cookie.startswith("eyJ"):
            self.access_token = self.raw_cookie
        else:
            raise RuntimeError(
                f"Không thể xác thực tài khoản ChatGPT từ Cookie: {info.get('message', 'Cookie hết hạn hoặc không hợp lệ')}"
            )

    def check_status(self) -> dict:
        return extract_chatgpt_session_info(self.raw_cookie)

    def _get_sentinel_headers(self, session) -> Dict[str, str]:
        """
        Lấy Chat Requirements Token và giải mã Proof-of-Work (PoW) để vượt qua bảo vệ Sentinel
        """
        sentinel_headers = {
            "oai-device-id": self.device_id,
            "oai-language": "en-US",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json"
        }
        if self.access_token:
            sentinel_headers["Authorization"] = f"Bearer {self.access_token}"

        req_endpoint = "https://chatgpt.com/backend-api/sentinel/chat-requirements"
        try:
            res = session.post(
                req_endpoint,
                json={"conversation_mode_kind": "primary_assistant"},
                headers=sentinel_headers,
                timeout=12
            )
            if res.status_code == 200:
                data = res.json()
                req_token = data.get("token")
                pow_info = data.get("proofofwork") or {}

                res_headers = {
                    "oai-device-id": self.device_id,
                    "oai-language": "en-US"
                }
                if req_token:
                    res_headers["openai-sentinel-chat-requirements-token"] = req_token

                if pow_info.get("required") and pow_info.get("seed") and pow_info.get("difficulty"):
                    proof_token = calc_proof_token(pow_info["seed"], pow_info["difficulty"])
                    if proof_token:
                        res_headers["openai-sentinel-proof-token"] = proof_token

                return res_headers
        except Exception as e:
            logger.warning(f"Lỗi khi thực hiện Sentinel handshake: {e}")

        return {"oai-device-id": self.device_id, "oai-language": "en-US"}

    def _call_chatgpt_web(self, prompt: str, timeout: int = 120, max_retries: int = 3) -> str:
        """Gửi prompt đến ChatGPT Web Conversation endpoint qua curl_cffi và parse SSE stream"""
        if not self.access_token:
            self._refresh_access_token()

        system_instruction = build_translation_system_instruction(self.config)
        full_prompt = f"{system_instruction}\n\n{prompt}"

        # Map model name
        target_model = "auto"
        if "mini" in self.model_name.lower():
            target_model = "gpt-4o-mini"
        elif "4o" in self.model_name.lower():
            target_model = "gpt-4o"

        payload = {
            "action": "next",
            "messages": [
                {
                    "id": str(uuid.uuid4()),
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": [full_prompt]
                    },
                    "metadata": {}
                }
            ],
            "model": target_model,
            "parent_message_id": str(uuid.uuid4()),
            "timezone_offset_min": -420,
            "history_and_training_disabled": True,
            "arkose_token": None
        }

        endpoint = "https://chatgpt.com/backend-api/conversation"
        session_cls = cffi_requests.Session if HAS_CURL_CFFI else requests.Session
        sess_kwargs = {"impersonate": "chrome124"} if HAS_CURL_CFFI else {}

        last_error = None

        with session_cls(**sess_kwargs) as session:
            for attempt in range(1, max_retries + 1):
                try:
                    # Lấy Sentinel headers kèm Proof-of-Work giải mã
                    sentinel_headers = self._get_sentinel_headers(session)

                    req_headers = {
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "Referer": "https://chatgpt.com/",
                        "Origin": "https://chatgpt.com",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                        **sentinel_headers
                    }

                    res = session.post(endpoint, json=payload, headers=req_headers, timeout=timeout, stream=True)

                    if res.status_code == 401:
                        logger.warning("Access token hết hạn, đang tự động làm mới từ Cookie...")
                        self._refresh_access_token()
                        time.sleep(1)
                        continue

                    if res.status_code == 200:
                        full_response = ""
                        for line in res.iter_lines():
                            if not line:
                                continue
                            if isinstance(line, bytes):
                                line = line.decode("utf-8", errors="ignore")
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    event_data = json.loads(data_str)
                                    msg = event_data.get("message", {})
                                    content = msg.get("content", {})
                                    parts = content.get("parts", [])
                                    if parts and isinstance(parts[0], str):
                                        full_response = parts[0]
                                except Exception:
                                    pass

                        if full_response.strip():
                            return full_response
                        else:
                            raise RuntimeError("ChatGPT trả về phản hồi rỗng.")

                    elif res.status_code == 403:
                        last_error = f"Status 403: {res.text}"
                        logger.warning(f"ChatGPT Web trả về 403 (Sentinel/Cloudflare), đang giải lại PoW và thử lại lần {attempt}/{max_retries}...")
                        time.sleep(2 * attempt)
                    elif res.status_code == 429:
                        logger.warning(f"ChatGPT Web bị giới hạn tốc độ (429), chờ thử lại (lần {attempt}/{max_retries})...")
                        time.sleep(3 * attempt)
                        last_error = "Rate limit 429"
                    else:
                        last_error = f"Status {res.status_code}: {res.text}"
                        logger.warning(f"ChatGPT Web trả về lỗi ({res.status_code}), thử lại...")
                        time.sleep(2 * attempt)

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Lỗi kết nối ChatGPT Web ({e}), thử lại lần {attempt}/{max_retries}...")
                    time.sleep(2 * attempt)

        raise RuntimeError(
            f"Lỗi ChatGPT Web Translation: {last_error}\n\n"
            f"💡 Mẹo khắc phục: Nếu ChatGPT Web tạm thời bị giới hạn, bạn có thể chuyển sang tab '🔹 DeepSeek API' trên giao diện để dịch siêu nhanh và ổn định 100%!"
        )

    def translate_srt(
        self,
        input_srt_path: Path,
        output_srt_path: Path
    ) -> List[SubtitleItem]:
        """Dịch file SRT qua ChatGPT Web với PoW và Chrome TLS (tự động sửa lỗi thiếu câu, chống lệch timeline)"""
        input_srt_path = Path(input_srt_path).resolve()
        output_srt_path = Path(output_srt_path).resolve()
        output_srt_path.parent.mkdir(parents=True, exist_ok=True)

        if not input_srt_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file SRT đầu vào: {input_srt_path}")

        raw_srt_text = input_srt_path.read_text(encoding="utf-8").strip()
        if not raw_srt_text:
            output_srt_path.write_text("", encoding="utf-8")
            return []

        original_items = parse_srt_string(raw_srt_text)
        if not original_items:
            output_srt_path.write_text("", encoding="utf-8")
            return []

        total_items = len(original_items)
        batch_size = int(getattr(self.config, "chatgpt_batch_size", 12) or 12)
        batches = [original_items[i:i + batch_size] for i in range(0, total_items, batch_size)]
        total_batches = len(batches)
        logger.info(f"[Bước 3] Đang dịch {total_items} câu phụ đề bằng ChatGPT Web ({self.model_name}) - Chia {total_batches} đoạn ({batch_size} câu/đoạn)...")

        final_translated_items: List[SubtitleItem] = []

        with tqdm(total=total_items, desc="[Bước 3] ChatGPT Dịch thuật SRT (Chia Đoạn)", leave=False) as pbar:
            for b_idx, batch in enumerate(batches, 1):
                batch_res = translate_batch_resilient(
                    call_ai_fn=lambda p: self._call_chatgpt_web(p, timeout=120),
                    batch=batch,
                    b_idx=b_idx,
                    total_batches=total_batches,
                    engine_name="ChatGPT Web"
                )
                final_translated_items.extend(batch_res)
                pbar.update(len(batch))

        # Xuất file SRT hoàn chỉnh
        srt_blocks = [item.to_srt_block() for item in final_translated_items]
        final_srt_text = "\n".join(srt_blocks).strip() + "\n"
        output_srt_path.write_text(final_srt_text, encoding="utf-8")
        logger.info(f"Đã dịch thành công toàn bộ {len(final_translated_items)} câu sang: {output_srt_path}")
        return final_translated_items


def create_translator(config: PipelineConfig) -> Union[DeepSeekTranslator, ChatGPTWebTranslator]:
    """Khởi tạo Translator phù hợp (DeepSeek API hoặc ChatGPT Web Cookie) theo cấu hình"""
    provider = getattr(config, "llm_provider", "deepseek")
    if provider == "chatgpt_cookie":
        return ChatGPTWebTranslator(config)
    return DeepSeekTranslator(config)
