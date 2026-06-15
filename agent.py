"""
agent.py — Bộ não AI của agent (Google Gemini, có nhận thức cấu hình tổng thể).

Với MỖI linh kiện, AI sẽ:
  1. Tìm trên web (Google Search, gồm Shopee/Lazada/Tiki và các nhà bán lẻ uy tín)
     giá bán hiện tại thấp nhất ở Việt Nam.
  2. Nếu model gốc ngừng bán / không có giá -> ĐỀ XUẤT linh kiện thay thế, BẮT BUỘC
     tương thích với toàn bộ cấu hình còn lại (socket, chuẩn RAM, công suất nguồn,
     kích thước case/tản, đủ nguồn cho VGA...), tránh nghẽn cổ chai.
  3. Tự thử lại khi gặp lỗi kết nối tạm thời hoặc khi không phân tích được JSON.

Yêu cầu: biến môi trường GEMINI_API_KEY.
"""

import re
import json
import time

from google import genai
from google.genai import types

MAX_RETRIES = 4            # số lần thử lại tối đa cho mỗi linh kiện
RETRY_BACKOFF = [5, 10, 20, 30]  # giây chờ giữa các lần thử

_TRANSIENT = (
    "disconnect", "timeout", "timed out", "temporarily", "unavailable",
    "deadline", "connection", "reset", "500", "502", "503", "504",
    "internal error", "overloaded", "resource_exhausted", "429",
)

_SCHEMA = """{
  "found": true hoặc false,
  "product_name": "tên sản phẩm thực tế tìm được",
  "price_vnd": số nguyên (đồng VND), 0 nếu không có giá,
  "store": "tên nhà bán lẻ",
  "url": "đường link trang sản phẩm",
  "is_substitute": true nếu đây là hàng thay thế (không phải model gốc),
  "substitute_reason": "lý do + khẳng định tương thích với cấu hình (rỗng nếu đúng model gốc)",
  "availability": "in_stock" hoặc "out_of_stock" hoặc "unknown",
  "note": "ghi chú ngắn: đang sale, đã gồm VAT, v.v."
}"""

_PROMPT_TEMPLATE = """Bạn là chuyên gia tư vấn & khảo giá linh kiện máy tính tại Việt Nam.

CẤU HÌNH TỔNG THỂ người dùng đang nhắm tới:
{build_context}

Linh kiện cần khảo giá lần này: "{query}"

NHIỆM VỤ — hãy tìm cho bằng được một mức giá thực tế:
1. Dùng web search tìm GIÁ BÁN HIỆN TẠI trên MỌI nền tảng tại Việt Nam: các nhà \
bán lẻ uy tín (GearVN, Phong Vũ, An Phát, Tin Học Ngôi Sao, Hà Nội Computer, \
Memoryzone, Nguyễn Công PC...) VÀ các sàn TMĐT (Shopee, Lazada, Tiki). Ưu tiên \
nguồn uy tín, hàng chính hãng; chọn giá thấp nhất CÒN HÀNG.
2. Nếu model gốc đã NGỪNG KINH DOANH hoặc không nơi nào còn giá: hãy đề xuất MỘT \
linh kiện THAY THẾ đang bán. Linh kiện thay thế BẮT BUỘC phải TƯƠNG THÍCH với toàn \
bộ cấu hình ở trên:
   - CPU ↔ Bo mạch chủ: cùng socket.
   - RAM ↔ Bo mạch chủ: cùng chuẩn (DDR4/DDR5).
   - Tản nhiệt: hỗ trợ socket CPU và vừa với case (vd radiator 360mm).
   - VGA: lọt khe/độ dài trong case và được nguồn cấp đủ công suất + đầu cắm.
   - Nguồn: đủ wattage cho cả dàn (đặc biệt CPU + VGA).
   - Case: đúng form factor (ATX...), đủ chỗ cho VGA và tản.
   Tránh nghẽn cổ chai và bảo đảm lắp ráp được. Giải thích ngắn ở "substitute_reason".
3. Giá phải là giá NIÊM YẾT THỰC TẾ thấy trên web, KHÔNG bịa. Chỉ đặt "found": false \
khi đã thử mọi nguồn và cả phương án thay thế mà vẫn không có giá thực.

Sau khi tìm xong, chỉ in ra DUY NHẤT một đối tượng JSON theo schema sau, KHÔNG kèm \
chữ nào khác trước/sau, KHÔNG bọc trong dấu ```:
{schema}"""


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    for blk in reversed(re.findall(r"\{.*\}", text, re.S)):
        try:
            return json.loads(blk)
        except json.JSONDecodeError:
            continue
    return None


def _response_text(resp) -> str:
    txt = getattr(resp, "text", None)
    if txt:
        return txt
    try:
        return "".join((getattr(p, "text", "") or "")
                       for p in resp.candidates[0].content.parts)
    except Exception:  # noqa: BLE001
        return ""


def _is_transient(err: Exception) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in _TRANSIENT)


def price_component(client: "genai.Client", query: str,
                    build_context: str, settings: dict) -> dict:
    """Định giá một linh kiện, tự thử lại đến khi có kết quả phân tích được."""
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    cfg = types.GenerateContentConfig(tools=[grounding_tool], temperature=0)
    prompt = _PROMPT_TEMPLATE.format(
        build_context=build_context, query=query, schema=_SCHEMA)

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=settings.get("model", "gemini-3.5-flash"),
                contents=prompt,
                config=cfg,
            )
            data = _extract_json(_response_text(resp))
            if data:  # phân tích JSON thành công
                try:
                    data["price_vnd"] = int(
                        re.sub(r"[^\d]", "", str(data.get("price_vnd", 0))) or 0)
                except ValueError:
                    data["price_vnd"] = 0
                return data
            # Không phân tích được -> coi như lỗi tạm, thử lại
            last_err = "Không phân tích được JSON"
            print(f"      (lần {attempt+1}: không đọc được JSON, thử lại)")
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if not _is_transient(exc):
                print(f"      Lỗi không thể thử lại: {last_err}")
                break
            print(f"      (lần {attempt+1}: lỗi kết nối, thử lại) {last_err[:80]}")

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])

    return {"found": False, "note": f"Thất bại sau {MAX_RETRIES} lần: {last_err}"}
