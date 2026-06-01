# WIPTOWN Expense Tracker

## วิธีรัน (ง่ายมาก)

### Mac / Linux
```bash
bash start.sh
```

### Windows
ดับเบิลคลิก `start.bat`

### หรือรันตรงๆ
```bash
python3 server.py
```

แล้วเปิดเบราว์เซอร์ที่ **http://localhost:8765**

---

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|------|---------|
| `server.py` | Python web server + REST API |
| `index.html` | หน้าเว็บ UI ทั้งหมด |
| `wiptown.db` | ฐานข้อมูล SQLite (สร้างอัตโนมัติตอนรันครั้งแรก) |
| `start.sh` | รันบน Mac/Linux |
| `start.bat` | รันบน Windows |

## ฐานข้อมูล (SQLite)

- **expenses** — รายการค่าใช้จ่ายทั้งหมด (รวมสลิป base64)
- **templates** — เทมเพลตค่าใช้จ่ายประจำเดือน
- **month_generated** — ติดตามว่าเดือนไหนโหลด template ไปแล้ว
- **settings** — รายได้, Discord webhook, SMS config

## ความต้องการ

- Python 3.6+ (มาพร้อม Mac/Linux)
- ไม่ต้องติดตั้ง library เพิ่มเติมใดๆ
