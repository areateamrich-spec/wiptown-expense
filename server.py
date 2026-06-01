#!/usr/bin/env python3
"""
WIPTOWN Expense Tracker — Server
รันด้วย: python3 server.py  →  http://localhost:8765
Railway: ตั้ง DATABASE_URL = ${{ Postgres.DATABASE_URL }}
"""
import json, os, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime

PORT = int(os.environ.get('PORT', 8765))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ─── DB abstraction: Postgres หรือ SQLite ────────────────────────────────────

USE_PG = bool(DATABASE_URL)

if USE_PG:
    import urllib.parse as up
    r = up.urlparse(DATABASE_URL)
    PG_CONF = dict(host=r.hostname, port=r.port or 5432,
                   dbname=r.path.lstrip('/'), user=r.username, password=r.password)
    print(f"✅ Using PostgreSQL: {r.hostname}/{r.path.lstrip('/')}")
else:
    import sqlite3
    _data_dir = '/data' if os.path.isdir('/data') else os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(_data_dir, 'wiptown.db')
    print(f"✅ Using SQLite: {DB_PATH}")


def get_pg():
    import psycopg2, psycopg2.extras
    conn = psycopg2.connect(**PG_CONF)
    return conn

def get_sqlite():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class DB:
    """Thin wrapper — ใช้ .execute() / .fetchall() / .close() เหมือนกันทั้งคู่"""

    def __init__(self):
        if USE_PG:
            import psycopg2, psycopg2.extras
            self._conn = psycopg2.connect(**PG_CONF)
            self._conn.autocommit = False
            self._cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            self._conn = sqlite3.connect(DB_PATH)
            self._conn.row_factory = sqlite3.Row
            self._cur = self._conn.cursor()
        self._is_pg = USE_PG

    # แปลง ? → %s สำหรับ Postgres
    def _sql(self, sql):
        return sql.replace('?', '%s') if self._is_pg else sql

    # แปลง :name → %(name)s สำหรับ Postgres
    def _named(self, sql):
        if not self._is_pg:
            return sql
        return re.sub(r':([a-zA-Z_][a-zA-Z0-9_]*)', r'%(\1)s', sql)

    def execute(self, sql, params=None):
        if params is None:
            self._cur.execute(self._sql(sql))
        elif isinstance(params, dict):
            self._cur.execute(self._named(sql), params)
        else:
            self._cur.execute(self._sql(sql), params)
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self.execute(sql, p)
        return self

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    def fetchone(self):
        r = self._cur.fetchone()
        return dict(r) if r else None

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.commit()
        self._cur.close()
        self._conn.close()

    def executescript(self, script):
        """ใช้เฉพาะ init — แยก statement เพื่อรองรับ Postgres"""
        if self._is_pg:
            stmts = [s.strip() for s in script.split(';') if s.strip()]
            for s in stmts:
                self._cur.execute(s)
        else:
            self._conn.executescript(script)

# ─── Init DB ─────────────────────────────────────────────────────────────────

def init_db():
    db = DB()
    if USE_PG:
        script = """
        CREATE TABLE IF NOT EXISTS expenses (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT NOT NULL DEFAULT 'other',
            date        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'one-time',
            tmpl_id     TEXT,
            slip        TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS templates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT NOT NULL DEFAULT 'other',
            due_day     INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS month_generated (
            month_key   TEXT NOT NULL,
            tmpl_id     TEXT NOT NULL,
            PRIMARY KEY (month_key, tmpl_id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT
        )
        """
    else:
        script = """
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other', date TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'one-time', tmpl_id TEXT, slip TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other', due_day INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS month_generated (
            month_key TEXT NOT NULL, tmpl_id TEXT NOT NULL,
            PRIMARY KEY (month_key, tmpl_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)
        """
    db.executescript(script)
    db.close()
    print("✅ Tables ready")

# ─── API handlers ─────────────────────────────────────────────────────────────

def api_get_expenses(_):
    db = DB()
    rows = db.execute("SELECT * FROM expenses ORDER BY date DESC").fetchall()
    db.close()
    return rows

def api_add_expense(body):
    db = DB()
    eid = body.get('id') or f"e{int(datetime.now().timestamp()*1000)}"
    if USE_PG:
        db.execute("""
            INSERT INTO expenses (id,name,amount,category,date,type,tmpl_id,slip)
            VALUES (%(id)s,%(name)s,%(amount)s,%(category)s,%(date)s,%(type)s,%(tmpl_id)s,%(slip)s)
            ON CONFLICT (id) DO UPDATE SET
              name=EXCLUDED.name, amount=EXCLUDED.amount, category=EXCLUDED.category,
              date=EXCLUDED.date, type=EXCLUDED.type, slip=EXCLUDED.slip
        """, {'id':eid,'name':body['name'],'amount':float(body['amount']),
              'category':body.get('category','other'),'date':body['date'],
              'type':body.get('type','one-time'),
              'tmpl_id':body.get('tmplId') or body.get('tmpl_id'),
              'slip':body.get('slip')})
    else:
        db.execute("""
            INSERT OR REPLACE INTO expenses (id,name,amount,category,date,type,tmpl_id,slip)
            VALUES (:id,:name,:amount,:category,:date,:type,:tmpl_id,:slip)
        """, {'id':eid,'name':body['name'],'amount':float(body['amount']),
              'category':body.get('category','other'),'date':body['date'],
              'type':body.get('type','one-time'),
              'tmpl_id':body.get('tmplId') or body.get('tmpl_id'),
              'slip':body.get('slip')})
    db.close()
    return {'ok': True}

def api_update_expense(eid, body):
    db = DB()
    slip_sql = "slip = COALESCE(%(slip)s, slip)" if USE_PG else "slip = COALESCE(:slip, slip)"
    db.execute(f"""
        UPDATE expenses SET name={'%(name)s' if USE_PG else ':name'},
          amount={'%(amount)s' if USE_PG else ':amount'},
          category={'%(category)s' if USE_PG else ':category'},
          date={'%(date)s' if USE_PG else ':date'},
          type={'%(type)s' if USE_PG else ':type'},
          {slip_sql}
        WHERE id={'%(id)s' if USE_PG else ':id'}
    """, {'id':eid,'name':body['name'],'amount':float(body['amount']),
          'category':body.get('category','other'),'date':body['date'],
          'type':body.get('type','one-time'),'slip':body.get('slip')})
    db.close()
    return {'ok': True}

def api_delete_expense(eid):
    db = DB()
    db.execute("DELETE FROM expenses WHERE id=?", (eid,))
    db.close()
    return {'ok': True}

def api_get_templates():
    db = DB()
    rows = db.execute("SELECT * FROM templates ORDER BY created_at").fetchall()
    db.close()
    return rows

def api_add_template(body):
    db = DB()
    tid = body.get('id') or f"t{int(datetime.now().timestamp()*1000)}"
    if USE_PG:
        db.execute("""
            INSERT INTO templates (id,name,amount,category,due_day)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              name=EXCLUDED.name, amount=EXCLUDED.amount,
              category=EXCLUDED.category, due_day=EXCLUDED.due_day
        """, (tid, body['name'], float(body['amount']), body.get('category','other'), int(body.get('dueDay',1))))
    else:
        db.execute("""
            INSERT OR REPLACE INTO templates (id,name,amount,category,due_day)
            VALUES (?,?,?,?,?)
        """, (tid, body['name'], float(body['amount']), body.get('category','other'), int(body.get('dueDay',1))))
    db.close()
    return {'ok': True, 'id': tid}

def api_update_template(tid, body):
    db = DB()
    db.execute("UPDATE templates SET name=?,amount=?,category=?,due_day=? WHERE id=?",
               (body['name'], float(body['amount']), body.get('category','other'), int(body.get('dueDay',1)), tid))
    db.close()
    return {'ok': True}

def api_delete_template(tid):
    db = DB()
    db.execute("DELETE FROM templates WHERE id=?", (tid,))
    db.close()
    return {'ok': True}

def api_get_month_generated():
    db = DB()
    rows = db.execute("SELECT * FROM month_generated").fetchall()
    db.close()
    result = {}
    for r in rows:
        k = r['month_key']
        if k not in result: result[k] = []
        result[k].append(r['tmpl_id'])
    return result

def api_set_month_generated(body):
    db = DB()
    for month_key, tmpl_ids in body.items():
        for tid in tmpl_ids:
            if USE_PG:
                db.execute("INSERT INTO month_generated (month_key,tmpl_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                           (month_key, tid))
            else:
                db.execute("INSERT OR IGNORE INTO month_generated (month_key,tmpl_id) VALUES (?,?)",
                           (month_key, tid))
    db.close()
    return {'ok': True}

def api_get_settings():
    db = DB()
    rows = db.execute("SELECT key,value FROM settings").fetchall()
    db.close()
    return {r['key']: r['value'] for r in rows}

def api_save_settings(body):
    db = DB()
    for k, v in body.items():
        val = str(v) if v is not None else ''
        if USE_PG:
            db.execute("INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                       (k, val))
        else:
            db.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, val))
    db.close()
    return {'ok': True}

# ─── HTTP Handler ─────────────────────────────────────────────────────────────

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
            if p in ('', '/'):
                with open(os.path.join(os.path.dirname(__file__), 'index.html'), 'rb') as f:
                    self.send_html(f.read())
            elif p == '/api/expenses':       self.send_json(api_get_expenses({}))
            elif p == '/api/templates':      self.send_json(api_get_templates())
            elif p == '/api/month-generated':self.send_json(api_get_month_generated())
            elif p == '/api/settings':       self.send_json(api_get_settings())
            else: self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            body = self.read_body()
            if   p == '/api/expenses':        self.send_json(api_add_expense(body))
            elif p == '/api/templates':       self.send_json(api_add_template(body))
            elif p == '/api/month-generated': self.send_json(api_set_month_generated(body))
            elif p == '/api/settings':        self.send_json(api_save_settings(body))
            else: self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({'error': str(e)}, 500)

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip('/')
        try:
            body = self.read_body()
            m = re.match(r'^/api/expenses/(.+)$', p)
            if m: self.send_json(api_update_expense(m.group(1), body)); return
            m = re.match(r'^/api/templates/(.+)$', p)
            if m: self.send_json(api_update_template(m.group(1), body)); return
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

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"\n{'='*45}")
    print(f"  🚀 WIPTOWN Expense Tracker")
    print(f"  DB: {'PostgreSQL' if USE_PG else 'SQLite'}")
    print(f"  Port: {PORT}")
    print(f"{'='*45}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⛔ Server stopped.")
