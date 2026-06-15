"""
main.py — Điểm chạy chính của AI agent khảo giá PC (Google Gemini).

Quy trình mỗi lần chạy:
  1. Đọc cấu hình linh kiện (config.yaml).
  2. Dựng "bối cảnh cấu hình tổng thể" để AI chọn hàng thay thế tương thích.
  3. Đọc lịch sử giá tuần trước (price_history.json) để so sánh tăng/giảm.
  4. Với mỗi linh kiện, để AI tự tìm giá (tự thử lại đến khi có kết quả).
  5. Gửi báo cáo tổng hợp lên Lark.
  6. Ghi lại snapshot giá tuần này.
"""

import os
import json
import time
import datetime

import yaml
from google import genai
from google.genai import types

from agent import price_component
from reporter import send_lark_report

CONFIG_PATH = "config.yaml"
HISTORY_PATH = "price_history.json"
MAX_SNAPSHOTS = 52
PAUSE_BETWEEN = 2  # giây nghỉ nhẹ giữa các linh kiện


def load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history: dict) -> None:
    history["snapshots"] = history["snapshots"][-MAX_SNAPSHOTS:]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def build_context(components: list[dict]) -> str:
    """Tạo mô tả cấu hình tổng thể để AI bảo đảm hàng thay thế tương thích."""
    return "\n".join(f"- {c['query']}" for c in components)


def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    settings = config.get("settings", {})
    # Timeout dài hơn để tránh "Server disconnected" khi grounding chậm.
    client = genai.Client(
        http_options=types.HttpOptions(timeout=180_000)  # 180 giây (ms)
    )

    ctx = build_context(config["components"])

    history = load_history()
    last = history["snapshots"][-1] if history["snapshots"] else None
    last_items = (last or {}).get("items", {})

    results: list[dict] = []
    total = 0
    snapshot_items: dict[str, int] = {}

    for idx, comp in enumerate(config["components"]):
        key, query = comp["key"], comp["query"]
        print(f"→ [{key}] {query}")
        if idx > 0:
            time.sleep(PAUSE_BETWEEN)

        data = price_component(client, query, ctx, settings)

        price = data.get("price_vnd", 0)
        if not data.get("found") or price <= 0:
            results.append({"key": key, "query": query, "status": "not_found",
                            "note": data.get("note", "")})
            print(f"    Không tìm thấy giá. {data.get('note','')}")
            continue

        line = {
            "key": key, "query": query, "status": "ok",
            "product_name": data.get("product_name", query),
            "price": price,
            "store": data.get("store", ""),
            "url": data.get("url", ""),
            "is_substitute": bool(data.get("is_substitute")),
            "substitute_reason": data.get("substitute_reason", ""),
            "availability": data.get("availability", "unknown"),
            "note": data.get("note", ""),
        }
        if line["availability"] == "out_of_stock":
            line["status"] = "out_of_stock"

        total += price
        snapshot_items[key] = price

        if key in last_items:
            line["prev_price"] = last_items[key]
            line["delta"] = price - last_items[key]

        tag = " [THAY THẾ]" if line["is_substitute"] else ""
        print(f"    {price:,}đ — {line['store']}{tag}")
        results.append(line)

    prev_total = last["total"] if last else None
    today = datetime.date.today().isoformat()

    print(f"\nTỔNG DỰ KIẾN: {total:,}đ")
    send_lark_report(results, total, prev_total, today, config)

    history["snapshots"].append({"date": today, "total": total, "items": snapshot_items})
    save_history(history)
    print("Đã lưu lịch sử. Hoàn tất.")


if __name__ == "__main__":
    main()
