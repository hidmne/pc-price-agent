"""
main.py — Điểm chạy chính của AI agent khảo giá PC.

Quy trình mỗi lần chạy:
  1. Đọc cấu hình linh kiện (config.yaml).
  2. Đọc lịch sử giá tuần trước (price_history.json) để so sánh tăng/giảm.
  3. Với mỗi linh kiện, để AI tự tìm giá (và tự đề xuất hàng tương đương nếu cần).
  4. Gửi báo cáo tổng hợp lên Lark.
  5. Ghi lại snapshot giá tuần này.
"""

import os
import json
import time
import datetime

import yaml
from google import genai

from agent import price_component
from reporter import send_lark_report

# Free tier giới hạn 10 request/phút cho gemini-3.5-flash.
# Nghỉ 7 giây giữa các lần gọi = tối đa ~8 request/phút, an toàn.
DELAY_BETWEEN_CALLS = 7  # giây

# Tự thử lại khi bị rate limit (429), tối đa 3 lần, mỗi lần chờ lâu hơn.
MAX_RETRIES = 3

CONFIG_PATH = "config.yaml"
HISTORY_PATH = "price_history.json"
MAX_SNAPSHOTS = 52


def load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"snapshots": []}


def save_history(history: dict) -> None:
    history["snapshots"] = history["snapshots"][-MAX_SNAPSHOTS:]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    settings = config.get("settings", {})
    client = genai.Client()  # đọc GEMINI_API_KEY từ môi trường

    history = load_history()
    last = history["snapshots"][-1] if history["snapshots"] else None
    last_items = (last or {}).get("items", {})

    results: list[dict] = []
    total = 0
    snapshot_items: dict[str, int] = {}

    for idx, comp in enumerate(config["components"]):
        key, query = comp["key"], comp["query"]
        print(f"→ [{key}] {query}")

        # Nghỉ giữa các lần gọi để không vượt rate limit free tier.
        if idx > 0:
            print(f"    (chờ {DELAY_BETWEEN_CALLS}s...)")
            time.sleep(DELAY_BETWEEN_CALLS)

        # Thử lại tự động khi bị 429.
        data = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                data = price_component(client, query, settings)
                break
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    wait = 30 * attempt  # 30s, 60s, 90s
                    print(f"    Rate limit (lần {attempt}/{MAX_RETRIES}), chờ {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"    LỖI gọi AI: {err}")
                    break

        if data is None:
            results.append({"key": key, "query": query, "status": "error",
                            "note": "Vượt rate limit sau nhiều lần thử."})
            continue

        price = data.get("price_vnd", 0)
        if not data.get("found") or price <= 0:
            results.append({"key": key, "query": query, "status": "not_found",
                            "note": data.get("note", "")})
            print("    Không tìm thấy giá đáng tin cậy.")
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
