#!/usr/bin/env python3
"""WIPTOWN Expense Tracker"""
import json, os, re, sys, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime

def log(msg):
    print(msg, flush=True)
    sys.stdout.flush()

PORT = int(os.environ.get('PORT', 8765))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = DATABASE_URL.startswith('postgres')

log(f"=== WIPTOWN STARTING ===")
log(f"PORT={PORT}")
log(f"USE_PG={USE_PG}")
log(f"DATABASE_URL={'SET' if DATABASE_URL else 'NOT SET'}")

# ── psycopg2 import test ───────────────────────────────────────────────────────
if USE_PG:
    try:
        import psycopg2
        import psycopg2.extras
        log("psycopg2 import OK")
    except ImportError as e:
        log(f"FATAL: psycopg2 import failed: {e}")
        sys.exit(1)

    import urllib.parse as _up
    _r = _up.urlparse(DATABASE_URL)
    PG_KWARGS = dict(
        host=_r.hostname,
        port=_r.port or 5432,
        dbname=_r.path.lstrip('/'),
        user=_r.username,
        password=_r.password,
        sslmode='require',
        connect_timeout=10,
    )
    log(f"PG host={_r.hostname} db={_r.path.lstrip('/')}")
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wiptown.db')
    log(f"SQLite path={DB_PATH}")

# ── connection ────────────────────────────────────────────────────────────────
def get_conn():
    if USE_PG:
        conn = psycopg2.connect(**PG_KWARGS)
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def to_list(cur):
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def P(sql):
    return sql.replace('?','%s') if USE_PG else sql

def run(sql, params=(), fetch=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(P(sql), params)
    result = to_list(cur) if fetch else []
    conn.commit()
    cur.close()
    conn.close()
    return result

# ── upserts ────────────────────────────────────────────────────────────────────
def upsert_exp(d):
    if USE_PG:
        run("""INSERT INTO expenses(id,name,amount,category,date,type,tmpl_id,slip)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET
                 name=EXCLUDED.name,amount=EXCLUDED.amount,category=EXCLUDED.category,
                 date=EXCLUDED.date,type=EXCLUDED.type,
                 slip=COALESCE(EXCLUDED.slip,expenses.slip)""",
            (d['id'],d['name'],d['amount'],d['category'],d['date'],d['type'],d.get('tmpl_id'),d.get('slip')))
    else:
        run("INSERT OR REPLACE INTO expenses(id,name,amount,category,date,type,tmpl_id,slip) VALUES(?,?,?,?,?,?,?,?)",
            (d['id'],d['name'],d['amount'],d['category'],d['date'],d['type'],d.get('tmpl_id'),d.get('slip')))

def upsert_tmpl(d):
    if USE_PG:
        run("""INSERT INTO templates(id,name,amount,category,due_day)
               VALUES(%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET
                 name=EXCLUDED.name,amount=EXCLUDED.amount,
                 category=EXCLUDED.category,due_day=EXCLUDED.due_day""",
            (d['id'],d['name'],d['amount'],d['category'],d['due_day']))
    else:
        run("INSERT OR REPLACE INTO templates(id,name,amount,category,due_day) VALUES(?,?,?,?,?)",
            (d['id'],d['name'],d['amount'],d['category'],d['due_day']))

def upsert_setting(k,v):
    if USE_PG:
        run("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",(k,v))
    else:
        run("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))

def insert_mgen(mk,tid):
    if USE_PG:
        run("INSERT INTO month_generated(month_key,tmpl_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(mk,tid))
    else:
        run("INSERT OR IGNORE INTO month_generated(month_key,tmpl_id) VALUES(?,?)",(mk,tid))

# ── init ──────────────────────────────────────────────────────────────────────
def init_db():
    log("Connecting to DB...")
    try:
        conn = get_conn()
        log("DB connected OK")
        cur = conn.cursor()
        if USE_PG:
            cur.execute("""CREATE TABLE IF NOT EXISTS expenses(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',date TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'one-time',tmpl_id TEXT,slip TEXT,
                created_at TEXT DEFAULT 'now')""")
            cur.execute("""CREATE TABLE IF NOT EXISTS templates(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',due_day INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT 'now')""")
            cur.execute("""CREATE TABLE IF NOT EXISTS month_generated(
                month_key TEXT NOT NULL,tmpl_id TEXT NOT NULL,
                PRIMARY KEY(month_key,tmpl_id))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,value TEXT)""")
        else:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS expenses(id TEXT PRIMARY KEY,name TEXT NOT NULL,
                  amount REAL NOT NULL,category TEXT NOT NULL DEFAULT 'other',date TEXT NOT NULL,
                  type TEXT NOT NULL DEFAULT 'one-time',tmpl_id TEXT,slip TEXT,created_at TEXT);
                CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY,name TEXT NOT NULL,
                  amount REAL NOT NULL,category TEXT NOT NULL DEFAULT 'other',
                  due_day INTEGER NOT NULL DEFAULT 1,created_at TEXT);
                CREATE TABLE IF NOT EXISTS month_generated(month_key TEXT NOT NULL,
                  tmpl_id TEXT NOT NULL,PRIMARY KEY(month_key,tmpl_id));
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            """)
        conn.commit()
        cur.close()
        conn.close()
        log("✅ DB tables ready")
    except Exception as e:
        log(f"FATAL DB init error: {e}")
        traceback.print_exc()
        sys.exit(1)

# ── API ───────────────────────────────────────────────────────────────────────
def api_get_expenses():
    return run("SELECT id,name,amount,category,date,type,tmpl_id,slip FROM expenses ORDER BY date DESC",fetch=True)

def api_add_expense(b):
    d={'id':b.get('id') or f"e{int(datetime.now().timestamp()*1000)}",
       'name':b['name'],'amount':float(b['amount']),'category':b.get('category','other'),
       'date':b['date'],'type':b.get('type','one-time'),
       'tmpl_id':b.get('tmplId') or b.get('tmpl_id'),'slip':b.get('slip')}
    upsert_exp(d); return {'ok':True}

def api_update_expense(eid,b):
    slip=b.get('slip')
    if USE_PG:
        run("UPDATE expenses SET name=%s,amount=%s,category=%s,date=%s,type=%s,slip=COALESCE(%s,slip) WHERE id=%s",
            (b['name'],float(b['amount']),b.get('category','other'),b['date'],b.get('type','one-time'),slip,eid))
    else:
        run("UPDATE expenses SET name=?,amount=?,category=?,date=?,type=?,slip=COALESCE(?,slip) WHERE id=?",
            (b['name'],float(b['amount']),b.get('category','other'),b['date'],b.get('type','one-time'),slip,eid))
    return {'ok':True}

def api_delete_expense(eid):
    run("DELETE FROM expenses WHERE id=?",(eid,)); return {'ok':True}

def api_get_templates():
    return run("SELECT id,name,amount,category,due_day FROM templates ORDER BY created_at",fetch=True)

def api_add_template(b):
    d={'id':b.get('id') or f"t{int(datetime.now().timestamp()*1000)}",
       'name':b['name'],'amount':float(b['amount']),'category':b.get('category','other'),
       'due_day':int(b.get('dueDay',1))}
    upsert_tmpl(d); return {'ok':True,'id':d['id']}

def api_update_template(tid,b):
    run("UPDATE templates SET name=?,amount=?,category=?,due_day=? WHERE id=?",
        (b['name'],float(b['amount']),b.get('category','other'),int(b.get('dueDay',1)),tid))
    return {'ok':True}

def api_delete_template(tid):
    run("DELETE FROM templates WHERE id=?",(tid,)); return {'ok':True}

def api_get_month_generated():
    rows=run("SELECT month_key,tmpl_id FROM month_generated",fetch=True)
    out={}
    for r in rows:
        k=r['month_key']
        if k not in out: out[k]=[]
        out[k].append(r['tmpl_id'])
    return out

def api_set_month_generated(body):
    for mk,tids in body.items():
        for tid in tids: insert_mgen(mk,tid)
    return {'ok':True}

def api_get_settings():
    rows=run("SELECT key,value FROM settings",fetch=True)
    return {r['key']:r['value'] for r in rows}

def api_save_settings(body):
    for k,v in body.items(): upsert_setting(k,str(v) if v is not None else '')
    return {'ok':True}

# ── HTTP ──────────────────────────────────────────────────────────────────────
HTML=os.path.join(os.path.dirname(os.path.abspath(__file__)),'index.html')

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass

    def jout(self,data,code=200):
        b=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',len(b))
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers(); self.wfile.write(b)

    def hout(self):
        with open(HTML,'rb') as f: b=f.read()
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',len(b))
        self.end_headers(); self.wfile.write(b)

    def body(self):
        n=int(self.headers.get('Content-Length',0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

    def do_GET(self):
        p=urlparse(self.path).path.rstrip('/') or '/'
        try:
            if   p=='/':                    self.hout()
            elif p=='/health':              self.jout({'ok':True})
            elif p=='/api/expenses':        self.jout(api_get_expenses())
            elif p=='/api/templates':       self.jout(api_get_templates())
            elif p=='/api/month-generated': self.jout(api_get_month_generated())
            elif p=='/api/settings':        self.jout(api_get_settings())
            else:                           self.jout({'error':'not found'},404)
        except Exception as e:
            traceback.print_exc(file=sys.stdout); sys.stdout.flush()
            self.jout({'error':str(e)},500)

    def do_POST(self):
        p=urlparse(self.path).path.rstrip('/')
        try:
            b=self.body()
            if   p=='/api/expenses':        self.jout(api_add_expense(b))
            elif p=='/api/templates':       self.jout(api_add_template(b))
            elif p=='/api/month-generated': self.jout(api_set_month_generated(b))
            elif p=='/api/settings':        self.jout(api_save_settings(b))
            else:                           self.jout({'error':'not found'},404)
        except Exception as e:
            traceback.print_exc(file=sys.stdout); sys.stdout.flush()
            self.jout({'error':str(e)},500)

    def do_PUT(self):
        p=urlparse(self.path).path.rstrip('/')
        try:
            b=self.body()
            m=re.match(r'^/api/expenses/(.+)$',p)
            if m: self.jout(api_update_expense(m.group(1),b)); return
            m=re.match(r'^/api/templates/(.+)$',p)
            if m: self.jout(api_update_template(m.group(1),b)); return
            self.jout({'error':'not found'},404)
        except Exception as e:
            traceback.print_exc(file=sys.stdout); sys.stdout.flush()
            self.jout({'error':str(e)},500)

    def do_DELETE(self):
        p=urlparse(self.path).path.rstrip('/')
        try:
            m=re.match(r'^/api/expenses/(.+)$',p)
            if m: self.jout(api_delete_expense(m.group(1))); return
            m=re.match(r'^/api/templates/(.+)$',p)
            if m: self.jout(api_delete_template(m.group(1))); return
            self.jout({'error':'not found'},404)
        except Exception as e:
            traceback.print_exc(file=sys.stdout); sys.stdout.flush()
            self.jout({'error':str(e)},500)

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    log(f"🚀 Listening on 0.0.0.0:{PORT}")
    srv=HTTPServer(('0.0.0.0',PORT),H)
    srv.serve_forever()
