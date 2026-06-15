"""
reporter.py — Dựng và gửi báo cáo dạng thẻ (interactive card) lên Lark
qua Custom Bot Webhook.
"""

import os
import json
import time
import hmac
import base64
import hashlib
import requests


def _fmt(value: int) -> str:
    return f"{value:,}".replace(",", ".") + "₫"


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _delta_text(line: dict) -> str:
    prev = line.get("prev_price")
    if "delta" not in line or not prev:
        return ""
    d = line["delta"]
    if d == 0:
        return "  ( ổn định )"
    pct = abs(d) / prev * 100
    arrow = "🔻" if d < 0 else "🔺"
    return f"  ({arrow} {_fmt(abs(d))} | {pct:.1f}%)"


def _line_block(r: dict) -> str:
    status = r["status"]
    title = f"**{r['query']}**"
    if status in ("not_found", "error"):
        note = r.get("note", "")
        icon = "⚠️" if status == "not_found" else "❗"
        return f"{title}\n{icon} {note or 'Không lấy được giá'}"

    sub = "  🔄 *(hàng tương đương)*" if r.get("is_substitute") else ""
    oos = "  ⛔ *(hết hàng)*" if status == "out_of_stock" else ""
    delta = _delta_text(r)
    name = r.get("product_name", "")[:70]
    store = r.get("store", "")
    url = r.get("url", "")
    link = f" — [{store}]({url})" if url else (f" — {store}" if store else "")

    block = f"{title}{sub}{oos}\n{_fmt(r['price'])}{delta}\n_{name}_{link}"
    if r.get("is_substitute") and r.get("substitute_reason"):
        block += f"\n↳ _Lý do thay thế: {r['substitute_reason'][:120]}_"
    return block


def build_card(results, total, prev_total, today, config) -> dict:
    body = "\n\n".join(_line_block(r) for r in results)

    total_delta = ""
    if prev_total:
        d = total - prev_total
        if d != 0:
            pct = abs(d) / prev_total * 100
            label = "🔻 GIẢM" if d < 0 else "🔺 TĂNG"
            total_delta = f"\n{label} {_fmt(abs(d))} ({pct:.1f}%) so với tuần trước"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🤖 Báo giá PC mơ ước — {today}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md",
                "content": f"**💰 TỔNG DỰ KIẾN: {_fmt(total)}**{total_delta}"}},
            {"tag": "note", "elements": [{"tag": "lark_md",
                "content": "Giá do AI khảo sát trên web tại thời điểm chạy • Vui lòng xác nhận lại trước khi mua"}]},
        ],
    }


def send_lark_report(results, total, prev_total, today, config) -> None:
    webhook = os.environ.get("LARK_WEBHOOK_URL", "").strip()
    secret = os.environ.get("LARK_WEBHOOK_SECRET", "").strip()

    card = build_card(results, total, prev_total, today, config)

    if not webhook:
        print("[LỖI] Thiếu biến môi trường LARK_WEBHOOK_URL.")
        print("Xem trước nội dung thẻ:")
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return

    payload = {"msg_type": "interactive", "card": card}
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)

    resp = requests.post(webhook, json=payload, timeout=20)
    print(f"Phản hồi từ Lark: HTTP {resp.status_code} — {resp.text}")
    resp.raise_for_status()
