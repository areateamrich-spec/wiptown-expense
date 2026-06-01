#!/usr/bin/env python3
"""
WIPTOWN Expense Tracker — Server
รันด้วย: python3 server.py
แล้วเปิด http://localhost:8765
"""
import sqlite3, json, os, base64, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'wiptown.db')
PORT = 8765

# ─── Database setup ───────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT NOT NULL DEFAULT 'other',
            date        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'one-time',
            tmpl_id     TEXT,
            slip        TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS templates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT NOT NULL DEFAULT 'other',
            due_day     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS month_generated (
            month_key   TEXT NOT NULL,
            tmpl_id     TEXT NOT NULL,
            PRIMARY KEY (month_key, tmpl_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT
        );
    """)
    conn.commit()
    conn.close()
    print(f"✅ Database ready: {DB_PATH}")

# ─── API Handlers ─────────────────────────────────────────────────────────────

def api_get_expenses(params):
    conn = get_db()
    rows = conn.execute("SELECT * FROM expenses ORDER BY date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def api_add_expense(body):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO expenses (id,name,amount,category,date,type,tmpl_id,slip)
        VALUES (:id,:name,:amount,:category,:date,:type,:tmpl_id,:slip)
    """, {
        'id':       body.get('id', f"e{int(datetime.now().timestamp()*1000)}"),
        'name':     body['name'],
        'amount':   float(body['amount']),
        'category': body.get('category','other'),
        'date':     body['date'],
        'type':     body.get('type','one-time'),
        'tmpl_id':  body.get('tmplId') or body.get('tmpl_id'),
        'slip':     body.get('slip'),
    })
    conn.commit()
    conn.close()
    return {'ok': True}

def api_update_expense(eid, body):
    conn = get_db()
    conn.execute("""
        UPDATE expenses SET
            name=:name, amount=:amount, category=:category,
            date=:date, type=:type, slip=COALESCE(:slip, slip)
        WHERE id=:id
    """, {
        'id':       eid,
        'name':     body['name'],
        'amount':   float(body['amount']),
        'category': body.get('category','other'),
        'date':     body['date'],
        'type':     body.get('type','one-time'),
        'slip':     body.get('slip'),
    })
    conn.commit()
    conn.close()
    return {'ok': True}

def api_delete_expense(eid):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return {'ok': True}

def api_get_templates():
    conn = get_db()
    rows = conn.execute("SELECT * FROM templates ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def api_add_template(body):
    conn = get_db()
    tid = body.get('id', f"t{int(datetime.now().timestamp()*1000)}")
    conn.execute("""
        INSERT OR REPLACE INTO templates (id,name,amount,category,due_day)
        VALUES (?,?,?,?,?)
    """, (tid, body['name'], float(body['amount']), body.get('category','other'), int(body.get('dueDay',1))))
    conn.commit()
    conn.close()
    return {'ok': True, 'id': tid}

def api_update_template(tid, body):
    conn = get_db()
    conn.execute("""
        UPDATE templates SET name=?,amount=?,category=?,due_day=? WHERE id=?
    """, (body['name'], float(body['amount']), body.get('category','other'), int(body.get('dueDay',1)), tid))
    conn.commit()
    conn.close()
    return {'ok': True}

def api_delete_template(tid):
    conn = get_db()
    conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return {'ok': True}

def api_get_month_generated():
    conn = get_db()
    rows = conn.execute("SELECT * FROM month_generated").fetchall()
    conn.close()
    result = {}
    for r in rows:
        k = r['month_key']
        if k not in result: result[k] = []
        result[k].append(r['tmpl_id'])
    return result

def api_set_month_generated(body):
    # body = { "2025-5": ["t1","t2"], ... }
    conn = get_db()
    for month_key, tmpl_ids in body.items():
        for tid in tmpl_ids:
            conn.execute("INSERT OR IGNORE INTO month_generated (month_key,tmpl_id) VALUES (?,?)", (month_key, tid))
    conn.commit()
    conn.close()
    return {'ok': True}

def api_get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

def api_save_settings(body):
    conn = get_db()
    for k, v in body.items():
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, str(v) if v is not None else ''))
    conn.commit()
    conn.close()
    return {'ok': True}

# ─── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html_bytes):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html_bytes))
        self.end_headers()
        self.wfile.write(html_bytes)

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            if p == '' or p == '/':
                html_path = os.path.join(os.path.dirname(__file__), 'index.html')
                with open(html_path, 'rb') as f:
                    self.send_html(f.read())
            elif p == '/api/expenses':
                self.send_json(api_get_expenses({}))
            elif p == '/api/templates':
                self.send_json(api_get_templates())
            elif p == '/api/month-generated':
                self.send_json(api_get_month_generated())
            elif p == '/api/settings':
                self.send_json(api_get_settings())
            else:
                self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            body = self.read_body()
            if p == '/api/expenses':
                self.send_json(api_add_expense(body))
            elif p == '/api/templates':
                self.send_json(api_add_template(body))
            elif p == '/api/month-generated':
                self.send_json(api_set_month_generated(body))
            elif p == '/api/settings':
                self.send_json(api_save_settings(body))
            else:
                self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            body = self.read_body()
            m = re.match(r'^/api/expenses/(.+)$', p)
            if m:
                self.send_json(api_update_expense(m.group(1), body)); return
            m = re.match(r'^/api/templates/(.+)$', p)
            if m:
                self.send_json(api_update_template(m.group(1), body)); return
            self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_DELETE(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            m = re.match(r'^/api/expenses/(.+)$', p)
            if m:
                self.send_json(api_delete_expense(m.group(1))); return
            m = re.match(r'^/api/templates/(.+)$', p)
            if m:
                self.send_json(api_delete_template(m.group(1))); return
            self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"\n{'='*45}")
    print(f"  🚀 WIPTOWN Expense Tracker")
    print(f"  เปิดเบราว์เซอร์ที่: http://localhost:{PORT}")
    print(f"  กด Ctrl+C เพื่อหยุด")
    print(f"{'='*45}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⛔ Server stopped.")
