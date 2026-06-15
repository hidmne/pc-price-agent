# PC Price AI Agent → Lark (Google Gemini)

AI agent tự khảo giá linh kiện PC hàng tuần, **tự đề xuất hàng tương đương khi model gốc ngừng bán**, và gửi báo cáo lên Lark.

- **Bộ não:** Google Gemini API + Grounding with Google Search (tự tìm, tự suy luận).
- **Lịch chạy:** 8:00 sáng Thứ Hai hàng tuần (GitHub Actions).
- **Cấu hình:** chỉ cần mô tả linh kiện bằng tiếng Việt trong `config.yaml` — không cần dán link.
- **Chi phí:** gần như miễn phí (Gemini 3.x cho 5.000 lượt Google Search/tháng miễn phí).

## Bắt đầu
Đọc **HUONG_DAN.md** — hướng dẫn từng bước, kể cả thao tác nhỏ nhất.

## Cấu trúc
```
config.yaml   # Mô tả linh kiện + chọn model — phần bạn chỉnh
main.py       # Điều phối: đọc config → gọi AI → gửi báo cáo → lưu lịch sử
agent.py      # Bộ não: gọi Gemini + Google Search, trả JSON kết quả có cấu trúc
reporter.py   # Dựng & gửi thẻ báo cáo lên Lark
.github/workflows/weekly.yml   # Lịch tự động hàng tuần
price_history.json             # (tự sinh) lịch sử giá để so sánh tuần
```

## Secrets (GitHub) / biến môi trường
| Tên | Bắt buộc | Ý nghĩa |
|---|---|---|
| `GEMINI_API_KEY` | Có | API key từ https://aistudio.google.com |
| `LARK_WEBHOOK_URL` | Có | Webhook của Lark Custom Bot |
| `LARK_WEBHOOK_SECRET` | Không | Chỉ khi bật "Signature verification" |
