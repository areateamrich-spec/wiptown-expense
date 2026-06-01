# WIPTOWN Expense Tracker

## วิธีรัน Local (ง่ายมาก)

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

## Deploy บน Railway

### ขั้นตอน
1. อัปโหลดไฟล์ทั้งหมดขึ้น GitHub
2. สร้าง project ใหม่ใน Railway → Deploy from GitHub
3. เพิ่ม Postgres service ใน Railway
4. ใน wiptown-expense service → Variables → เพิ่ม:
   - `DATABASE_URL` = เลือกจาก autocomplete ของ Railway (ไม่ต้องพิมพ์เอง)
5. **อย่าตั้ง PORT variable** — ให้ Railway จัดการเอง
6. Deploy → เปิด URL ได้เลย

### หมายเหตุ
- ห้ามตั้ง Variable ชื่อ PORT ใน Railway dashboard
- ถ้าเคยตั้ง PORT ไว้ให้ลบออกก่อน

---

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|------|---------|
| `server.py` | Python web server + REST API (รองรับ PostgreSQL + SQLite) |
| `index.html` | หน้าเว็บ UI ทั้งหมด |
| `requirements.txt` | Python packages (psycopg2-binary) |
| `Procfile` | บอก Railway วิธีรัน |
| `nixpacks.toml` | config การ build |

## ฐานข้อมูล

- **Local**: SQLite (wiptown.db) สร้างอัตโนมัติ
- **Railway**: PostgreSQL (ตั้ง DATABASE_URL variable)
