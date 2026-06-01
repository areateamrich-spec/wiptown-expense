#!/usr/bin/env python3
"""WIPTOWN Expense Tracker — works locally (SQLite) and on Railway (PostgreSQL)"""
import json, os, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime

PORT = int(os.environ.get('PORT', 8765))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = DATABASE_URL.startswith('postgres')

print(f"PORT={PORT} USE_PG={USE_PG}")

# ── SQLite setup ──────────────────────────────────────────────────────────────
if not USE_PG:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wiptown.db')

# ── PostgreSQL setup ──────────────────────────────────────────────────────────
if USE_PG:
    import psycopg2, psycopg2.extras
    import urllib.parse as urlparse_pg
    r = urlparse_pg.urlparse(DATABASE_URL)
    PG = dict(host=r.hostname, port=r.port or 5432,
              dbname=r.path.lstrip('/'), user=r.username, password=r.password,
              sslmode='require')

# ── DB connection ─────────────────────────────────────────────────────────────
def get_conn():
    if USE_PG:
        conn = psycopg2.connect(**PG)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def rows_to_list(cur):
    if USE_PG:
        return [dict(r) for r in cur.fetchall()]
    else:
        return [dict(r) for r in cur.fetchall()]

def q(sql):
    """Convert ? placeholders to %s for psycopg2"""
    return sql.replace('?', '%s') if USE_PG else sql

def upsert_expense(cur, d):
    if USE_PG:
        cur.execute("""
            INSERT INTO expenses (id,name,amount,category,date,type,tmpl_id,slip)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET
              name=EXCLUDED.name, amount=EXCLUDED.amount, category=EXCLUDED.category,
              date=EXCLUDED.date, type=EXCLUDED.type,
              slip=COALESCE(EXCLUDED.slip, expenses.slip)
        """, (d['id'],d['name'],d['amount'],d['category'],d['date'],d['type'],d.get('tmpl_id'),d.get('slip')))
    else:
        cur.execute("""
            INSERT OR REPLACE INTO expenses (id,name,amount,category,date,type,tmpl_id,slip)
            VALUES (?,?,?,?,?,?,?,?)
        """, (d['id'],d['name'],d['amount'],d['category'],d['date'],d['type'],d.get('tmpl_id'),d.get('slip')))

def upsert_template(cur, d):
    if USE_PG:
        cur.execute("""
            INSERT INTO templates (id,name,amount,category,due_day)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET
              name=EXCLUDED.name, amount=EXCLUDED.amount,
              category=EXCLUDED.category, due_day=EXCLUDED.due_day
        """, (d['id'],d['name'],d['amount'],d['category'],d['due_day']))
    else:
        cur.execute("""
            INSERT OR REPLACE INTO templates (id,name,amount,category,due_day)
            VALUES (?,?,?,?,?)
        """, (d['id'],d['name'],d['amount'],d['category'],d['due_day']))

def upsert_setting(cur, key, val):
    if USE_PG:
        cur.execute("""
            INSERT INTO settings(key,value) VALUES(%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """, (key, val))
    else:
        cur.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, val))

def insert_month_gen(cur, month_key, tmpl_id):
    if USE_PG:
        cur.execute("INSERT INTO month_generated(month_key,tmpl_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (month_key, tmpl_id))
    else:
        cur.execute("INSERT OR IGNORE INTO month_generated(month_key,tmpl_id) VALUES(?,?)",
                    (month_key, tmpl_id))

# ── Init DB ───────────────────────────────────────────────────────────────────
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other', date TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'one-time', tmpl_id TEXT, slip TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other', due_day INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS month_generated (
                month_key TEXT NOT NULL, tmpl_id TEXT NOT NULL,
                PRIMARY KEY(month_key, tmpl_id)
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT
            )""")
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other', date TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'one-time', tmpl_id TEXT, slip TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other', due_day INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS month_generated (
                month_key TEXT NOT NULL, tmpl_id TEXT NOT NULL,
                PRIMARY KEY(month_key, tmpl_id)
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        """)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB tables ready")

# ── API handlers ──────────────────────────────────────────────────────────────
def api_get_expenses():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id,name,amount,category,date,type,tmpl_id,slip FROM expenses ORDER BY date DESC")
    rows = rows_to_list(cur); cur.close(); conn.close()
    return rows

def api_add_expense(b):
    conn = get_conn(); cur = conn.cursor()
    d = {'id': b.get('id') or f"e{int(datetime.now().timestamp()*1000)}",
         'name': b['name'], 'amount': float(b['amount']),
         'category': b.get('category','other'), 'date': b['date'],
         'type': b.get('type','one-time'),
         'tmpl_id': b.get('tmplId') or b.get('tmpl_id'),
         'slip': b.get('slip')}
    upsert_expense(cur, d)
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_update_expense(eid, b):
    conn = get_conn(); cur = conn.cursor()
    slip = b.get('slip')
    if USE_PG:
        cur.execute("""UPDATE expenses SET name=%s,amount=%s,category=%s,date=%s,type=%s,
                       slip=COALESCE(%s,slip) WHERE id=%s""",
                    (b['name'],float(b['amount']),b.get('category','other'),
                     b['date'],b.get('type','one-time'),slip,eid))
    else:
        cur.execute("""UPDATE expenses SET name=?,amount=?,category=?,date=?,type=?,
                       slip=COALESCE(?,slip) WHERE id=?""",
                    (b['name'],float(b['amount']),b.get('category','other'),
                     b['date'],b.get('type','one-time'),slip,eid))
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_delete_expense(eid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q("DELETE FROM expenses WHERE id=?"), (eid,))
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_get_templates():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id,name,amount,category,due_day FROM templates ORDER BY created_at")
    rows = rows_to_list(cur); cur.close(); conn.close()
    return rows

def api_add_template(b):
    conn = get_conn(); cur = conn.cursor()
    d = {'id': b.get('id') or f"t{int(datetime.now().timestamp()*1000)}",
         'name': b['name'], 'amount': float(b['amount']),
         'category': b.get('category','other'), 'due_day': int(b.get('dueDay',1))}
    upsert_template(cur, d)
    conn.commit(); cur.close(); conn.close()
    return {'ok': True, 'id': d['id']}

def api_update_template(tid, b):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q("UPDATE templates SET name=?,amount=?,category=?,due_day=? WHERE id=?"),
                (b['name'],float(b['amount']),b.get('category','other'),int(b.get('dueDay',1)),tid))
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_delete_template(tid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(q("DELETE FROM templates WHERE id=?"), (tid,))
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_get_month_generated():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT month_key, tmpl_id FROM month_generated")
    rows = rows_to_list(cur); cur.close(); conn.close()
    result = {}
    for r in rows:
        k = r['month_key']
        if k not in result: result[k] = []
        result[k].append(r['tmpl_id'])
    return result

def api_set_month_generated(body):
    conn = get_conn(); cur = conn.cursor()
    for month_key, tmpl_ids in body.items():
        for tid in tmpl_ids:
            insert_month_gen(cur, month_key, tid)
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

def api_get_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT key,value FROM settings")
    rows = rows_to_list(cur); cur.close(); conn.close()
    return {r['key']: r['value'] for r in rows}

def api_save_settings(body):
    conn = get_conn(); cur = conn.cursor()
    for k, v in body.items():
        upsert_setting(cur, k, str(v) if v is not None else '')
    conn.commit(); cur.close(); conn.close()
    return {'ok': True}

# ── HTTP Handler ──────────────────────────────────────────────────────────────
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress access logs

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        with open(HTML_PATH, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path.rstrip('/') or '/'
        try:
            if p == '/':                      self.send_html()
            elif p == '/health':              self.send_json({'ok': True})
            elif p == '/api/expenses':        self.send_json(api_get_expenses())
            elif p == '/api/templates':       self.send_json(api_get_templates())
            elif p == '/api/month-generated': self.send_json(api_get_month_generated())
            elif p == '/api/settings':        self.send_json(api_get_settings())
            else:                             self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            b = self.read_body()
            if   p == '/api/expenses':        self.send_json(api_add_expense(b))
            elif p == '/api/templates':       self.send_json(api_add_template(b))
            elif p == '/api/month-generated': self.send_json(api_set_month_generated(b))
            elif p == '/api/settings':        self.send_json(api_save_settings(b))
            else:                             self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            b = self.read_body()
            m = re.match(r'^/api/expenses/(.+)$', p)
            if m: self.send_json(api_update_expense(m.group(1), b)); return
            m = re.match(r'^/api/templates/(.+)$', p)
            if m: self.send_json(api_update_template(m.group(1), b)); return
            self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_DELETE(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            m = re.match(r'^/api/expenses/(.+)$', p)
            if m: self.send_json(api_delete_expense(m.group(1))); return
            m = re.match(r'^/api/templates/(.+)$', p)
            if m: self.send_json(api_delete_template(m.group(1))); return
            self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    httpd = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"🚀 WIPTOWN running on 0.0.0.0:{PORT} ({'PostgreSQL' if USE_PG else 'SQLite'})")
    httpd.serve_forever()
