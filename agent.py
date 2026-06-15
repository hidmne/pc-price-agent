"""
agent.py — Bộ não AI của agent (phiên bản Google Gemini).

Dùng Gemini API + công cụ Grounding with Google Search để, với MỖI linh kiện
mô tả bằng lời:
  1. Tự tìm trên web giá bán hiện tại thấp nhất tại các nhà bán lẻ uy tín ở VN.
  2. Nếu model đã ngừng bán / không nơi nào còn hàng -> TỰ ĐỀ XUẤT một linh kiện
     tương đương tốt nhất hiện có và báo giá linh kiện đó, kèm lý do.
  3. Trả về kết quả ở dạng JSON có cấu trúc.

Yêu cầu: biến môi trường GEMINI_API_KEY.
"""

import re
import json

from google import genai
from google.genai import types

_SCHEMA = """{
  "found": true hoặc false,
  "product_name": "tên sản phẩm thực tế tìm được",
  "price_vnd": số nguyên (đồng VND), 0 nếu không có giá,
  "store": "tên nhà bán lẻ",
  "url": "đường link trang sản phẩm",
  "is_substitute": true nếu đây là hàng thay thế (không phải model gốc),
  "substitute_reason": "lý do chọn hàng thay thế (rỗng nếu đúng model gốc)",
  "availability": "in_stock" hoặc "out_of_stock" hoặc "unknown",
  "note": "ghi chú ngắn: đang sale, đã gồm VAT, v.v."
}"""

_PROMPT_TEMPLATE = """Bạn là trợ lý khảo giá linh kiện máy tính tại Việt Nam.

Linh kiện cần khảo giá: "{query}"

Hãy dùng Google Search để tìm GIÁ BÁN HIỆN TẠI tại các nhà bán lẻ uy tín ở Việt \
Nam (ví dụ: GearVN, Phong Vũ, An Phát Computer, Tin Học Ngôi Sao, Hà Nội Computer, \
Memoryzone, Nguyễn Công PC...).

Quy tắc:
- Nếu tìm thấy ĐÚNG model còn bán: báo giá thấp nhất kèm nơi bán và link.
- Nếu model đã NGỪNG KINH DOANH hoặc không nơi nào còn hàng: hãy đề xuất MỘT linh \
kiện THAY THẾ TƯƠNG ĐƯƠNG tốt nhất đang bán (cùng phân khúc, hiệu năng tương đương \
hoặc nhỉnh hơn, cùng socket/chuẩn nếu là CPU/RAM/bo mạch chủ), báo giá linh kiện \
thay thế đó và nêu rõ lý do ở "substitute_reason".
- Giá phải là giá NIÊM YẾT THỰC TẾ bạn thấy trên web, KHÔNG ước lượng. Nếu không \
chắc chắn về giá, đặt "found": false.

Sau khi tìm xong, chỉ in ra DUY NHẤT một đối tượng JSON theo schema sau, KHÔNG kèm \
bất kỳ chữ nào khác trước hoặc sau, KHÔNG bọc trong dấu ```:
{schema}"""


def _extract_json(text: str) -> dict | None:
    """Trích đối tượng JSON cuối cùng trong văn bản trả về của mô hình."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    matches = re.findall(r"\{.*\}", text, re.S)
    for blk in reversed(matches):
        try:
            return json.loads(blk)
        except json.JSONDecodeError:
            continue
    return None


def _response_text(resp) -> str:
    """Lấy text từ phản hồi Gemini một cách an toàn."""
    txt = getattr(resp, "text", None)
    if txt:
        return txt
    try:
        parts = resp.candidates[0].content.parts
        return "".join((getattr(p, "text", "") or "") for p in parts)
    except Exception:  # noqa: BLE001
        return ""


def price_component(client: "genai.Client", query: str, settings: dict) -> dict:
    """Gọi Gemini (có Google Search) để định giá một linh kiện. Trả về dict kết quả."""
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        temperature=0,
    )
    prompt = _PROMPT_TEMPLATE.format(query=query, schema=_SCHEMA)

    resp = client.models.generate_content(
        model=settings.get("model", "gemini-3.5-flash"),
        contents=prompt,
        config=config,
    )

    data = _extract_json(_response_text(resp))
    if not data:
        return {"found": False, "note": "Không phân tích được kết quả từ AI."}

    try:
        data["price_vnd"] = int(re.sub(r"[^\d]", "", str(data.get("price_vnd", 0))) or 0)
    except ValueError:
        data["price_vnd"] = 0
    return data
