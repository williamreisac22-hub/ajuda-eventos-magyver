import http.server, socketserver, json, sqlite3, hashlib, secrets, os, urllib.parse, smtplib, ssl, threading, time, datetime, re
from email.message import EmailMessage
from pathlib import Path
import qrcode

BASE=Path(__file__).resolve().parent
DB=BASE/'data'/'magyver.db'
STATIC=BASE/'static'
PORT=int(os.environ.get('PORT','8080'))
SESSIONS={}
LOCK=threading.Lock()

def db():
    c=sqlite3.connect(DB, check_same_thread=False)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=db();
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,login TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,salt TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),company TEXT,email TEXT,pix_type TEXT,pix_key TEXT,merchant_name TEXT,merchant_city TEXT,reminder INTEGER DEFAULT 1,smtp_host TEXT,smtp_port INTEGER DEFAULT 587,smtp_user TEXT,smtp_pass TEXT,smtp_tls INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,phone TEXT,email TEXT,doc TEXT,address TEXT,obs TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,client TEXT,date TEXT NOT NULL,time TEXT NOT NULL,address TEXT,people INTEGER,service TEXT,confirm TEXT,value REAL DEFAULT 0,obs TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id INTEGER,type TEXT,value REAL,method TEXT,status TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS equipment(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,checked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS food(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,cat TEXT,qty TEXT,obs TEXT);
    CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT,client TEXT,event TEXT,people INTEGER,service TEXT,value REAL,status TEXT);
    CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY AUTOINCREMENT,client TEXT,event TEXT,date TEXT,time TEXT,address TEXT,people INTEGER,value REAL,status TEXT,obs TEXT);
    CREATE TABLE IF NOT EXISTS reminders_sent(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id INTEGER,date TEXT,UNIQUE(event_id,date));
    INSERT OR IGNORE INTO settings(id,company,email,pix_type,pix_key,merchant_name,merchant_city,reminder) VALUES(1,'','','','','MAGYVER','SAO PAULO',1);
    '''); c.commit(); c.close()

def hashpw(p,s=None):
    s=s or secrets.token_hex(16)
    return hashlib.pbkdf2_hmac('sha256',p.encode(),s.encode(),240000).hex(),s

def verify(p,h,s): return secrets.compare_digest(hashpw(p,s)[0],h)
def now(): return datetime.datetime.now().isoformat(timespec='seconds')
def token(): return secrets.token_urlsafe(32)

def settings():
    r=db().execute('SELECT * FROM settings WHERE id=1').fetchone(); return dict(r)

def pix_payload(key, amount, name, city, txid='***'):
    def fld(k,v): return f'{k}{len(v):02d}{v}'
    gui=fld('00','BR.GOV.BCB.PIX')
    mai=fld('26',gui+fld('01',key))
    body=fld('00','01')+mai+fld('52','0000')+fld('53','986')
    if amount is not None and str(amount).strip(): body+=fld('54',f'{float(amount):.2f}')
    body+=fld('58','BR')+fld('59',re.sub(r'[^A-Za-z0-9 ]','',name.upper())[:25])+fld('60',re.sub(r'[^A-Za-z0-9 ]','',city.upper())[:15])+fld('62',fld('05',txid))
    raw=body+'6304'
    crc=0xFFFF
    for b in raw.encode():
        crc ^= b<<8
        for _ in range(8): crc=((crc<<1)^0x1021)&0xFFFF if crc&0x8000 else (crc<<1)&0xFFFF
    return raw+f'{crc:04X}'

def send_email(cfg,to,subject,text):
    if not cfg.get('smtp_host') or not cfg.get('smtp_user') or not cfg.get('smtp_pass'): return False,'SMTP não configurado.'
    msg=EmailMessage(); msg['From']=cfg.get('smtp_user'); msg['To']=to; msg['Subject']=subject; msg.set_content(text)
    try:
        with smtplib.SMTP(cfg['smtp_host'],int(cfg.get('smtp_port') or 587),timeout=20) as s:
            if int(cfg.get('smtp_tls') or 1): s.starttls(context=ssl.create_default_context())
            s.login(cfg['smtp_user'],cfg['smtp_pass']); s.send_message(msg)
        return True,'Enviado'
    except Exception as e: return False,str(e)

def reminder_worker():
    while True:
        try:
            cfg=settings(); tomorrow=(datetime.date.today()+datetime.timedelta(days=1)).isoformat()
            if cfg.get('reminder') and cfg.get('email'):
                c=db(); rows=c.execute('SELECT * FROM events WHERE date=? AND confirm<>?',(tomorrow,'Cancelado')).fetchall()
                for e in rows:
                    if c.execute('SELECT 1 FROM reminders_sent WHERE event_id=? AND date=?',(e['id'],tomorrow)).fetchone(): continue
                    ok,_=send_email(cfg,cfg['email'],f"Lembrete: evento amanhã - {e['name']}",f"Lembrete do Ajuda Eventos Magyver\\n\\nEvento: {e['name']}\\nData: {e['date']}\\nHorário: {e['time']}\\nCliente: {e['client']}\\nEndereço: {e['address']}\\nPessoas: {e['people']}\\nServiço: {e['service']}")
                    if ok: c.execute('INSERT OR IGNORE INTO reminders_sent(event_id,date) VALUES(?,?)',(e['id'],tomorrow)); c.commit()
                c.close()
        except Exception: pass
        time.sleep(300)

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def send(self,code,obj,ctype='application/json'):
        self.send_response(code); self.send_header('Content-Type',ctype+'; charset=utf-8' if ctype.startswith('text') or ctype=='application/json' else ctype); self.send_header('Cache-Control','no-store'); self.end_headers()
        if ctype=='application/json': self.wfile.write(json.dumps(obj,ensure_ascii=False).encode())
        else: self.wfile.write(obj)
    def body(self):
        n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n) or b'{}')
    def auth(self): return SESSIONS.get(self.headers.get('Authorization','').replace('Bearer ','').strip())
    def do_GET(self):
        p=urllib.parse.urlparse(self.path); path=p.path
        if path=='/': return self.file('index.html','text/html')
        if path.startswith('/static/'): return self.file(path[8:])
        if path=='/api/me': return self.send(200,{'user':self.auth()} if self.auth() else {'user':None})
        if not self.auth(): return self.send(401,{'error':'Não autenticado'})
        c=db()
        if path=='/api/data':
            out={k:[dict(r) for r in c.execute(q)] for k,q in {'events':'SELECT * FROM events ORDER BY date,time','clients':'SELECT * FROM clients ORDER BY name','payments':'SELECT * FROM payments ORDER BY id DESC','equipment':'SELECT * FROM equipment ORDER BY name','food':'SELECT * FROM food ORDER BY name','quotes':'SELECT * FROM quotes ORDER BY id DESC','contracts':'SELECT * FROM contracts ORDER BY id DESC'}.items()}; out['settings']=settings(); return self.send(200,out)
        if path=='/api/pix':
            q=urllib.parse.parse_qs(p.query); amount=q.get('amount',[''])[0]; cfg=settings()
            if not cfg['pix_key']: return self.send(400,{'error':'Cadastre a chave PIX nas configurações.'})
            payload=pix_payload(cfg['pix_key'],amount,cfg['merchant_name'] or cfg['company'] or 'MAGYVER',cfg['merchant_city'] or 'SAO PAULO')
            return self.send(200,{'payload':payload,'key':cfg['pix_key'],'amount':amount})
        if path=='/api/qr':
            q=urllib.parse.parse_qs(p.query); text=q.get('text',[''])[0]
            if not text: return self.send(400,{'error':'QR vazio'})
            img=qrcode.make(text); import io; b=io.BytesIO(); img.save(b,format='PNG'); return self.send(200,b.getvalue(),'image/png')
        c.close(); return self.send(404,{'error':'Não encontrado'})
    def file(self,name,ctype=None):
        f=(BASE/name) if name=='index.html' else (STATIC/name)
        if not f.exists(): return self.send(404,b'Not found','text/plain')
        data=f.read_bytes(); ctype=ctype or ('image/png' if f.suffix=='.png' else 'text/plain')
        self.send(200,data,ctype)
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path; d=self.body()
        if path=='/api/register':
            if not d.get('name') or not d.get('login') or not d.get('password'): return self.send(400,{'error':'Preencha nome, login e senha.'})
            h,s=hashpw(d['password']); c=db()
            try: c.execute('INSERT INTO users(name,login,password_hash,salt,created_at) VALUES(?,?,?,?,?)',(d['name'],d['login'],h,s,now())); c.commit()
            except sqlite3.IntegrityError: return self.send(409,{'error':'Login já cadastrado.'})
            return self.send(200,{'ok':True})
        if path=='/api/login':
            c=db(); r=c.execute('SELECT * FROM users WHERE login=?',(d.get('login',''),)).fetchone();
            if not r or not verify(d.get('password',''),r['password_hash'],r['salt']): return self.send(401,{'error':'Login ou senha inválidos.'})
            t=token(); SESSIONS[t]={'id':r['id'],'name':r['name'],'login':r['login']}; return self.send(200,{'token':t,'user':SESSIONS[t]})
        if not self.auth(): return self.send(401,{'error':'Não autenticado'})
        c=db()
        if path=='/api/save':
            typ=d.get('type'); obj=d.get('data',{}); maps={
             'events':('events',['name','client','date','time','address','people','service','confirm','value','obs']), 'clients':('clients',['name','phone','email','doc','address','obs']),
             'equipment':('equipment',['name','checked']),'food':('food',['name','cat','qty','obs']),'quotes':('quotes',['client','event','people','service','value','status']),'contracts':('contracts',['client','event','date','time','address','people','value','status','obs'])}
            if typ not in maps:return self.send(400,{'error':'Tipo inválido'})
            table,fields=maps[typ]; vals=[obj.get(x) for x in fields];
            if obj.get('id'):
                sets=','.join(f'{x}=?' for x in fields); c.execute(f'UPDATE {table} SET {sets} WHERE id=?',vals+[obj['id']])
            else:
                c.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",vals); obj['id']=c.lastrowid
            c.commit(); return self.send(200,{'data':obj})
        if path=='/api/delete':
            table=d.get('type'); idv=d.get('id');
            if table not in ['events','clients','equipment','food','quotes','contracts','payments']: return self.send(400,{'error':'Tipo inválido'})
            c.execute(f'DELETE FROM {table} WHERE id=?',(idv,)); c.commit(); return self.send(200,{'ok':True})
        if path=='/api/payment':
            c.execute('INSERT INTO payments(event_id,type,value,method,status,created_at) VALUES(?,?,?,?,?,?)',(d.get('event_id'),d.get('type'),float(d.get('value') or 0),d.get('method'),d.get('status'),now())); c.commit(); return self.send(200,{'ok':True})
        if path=='/api/settings':
            fields=['company','email','pix_type','pix_key','merchant_name','merchant_city','reminder','smtp_host','smtp_port','smtp_user','smtp_pass','smtp_tls']; vals=[d.get(x) for x in fields]
            c.execute('UPDATE settings SET '+','.join(f'{x}=?' for x in fields)+' WHERE id=1',vals); c.commit(); return self.send(200,{'ok':True})
        if path=='/api/profile':
            c.execute('UPDATE users SET name=? WHERE id=?',(d.get('name'),self.auth()['id'])); c.commit(); SESSIONS[[k for k,v in SESSIONS.items() if v['id']==self.auth()['id']][0]]['name']=d.get('name'); return self.send(200,{'ok':True})
        if path=='/api/test-email':
            cfg=settings(); ok,err=send_email(cfg,cfg.get('email'),'Teste - Ajuda Eventos Magyver','Este é um teste do sistema de lembretes por e-mail.'); return self.send(200 if ok else 400,{'ok':ok,'message':err})
        return self.send(404,{'error':'Não encontrado'})

init_db(); threading.Thread(target=reminder_worker,daemon=True).start()
with socketserver.ThreadingTCPServer(('0.0.0.0',PORT),H) as s:
    print(f'Ajuda Eventos Magyver em http://127.0.0.1:{PORT}')
    s.serve_forever()
