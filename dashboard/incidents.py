"""Durable dashboard incidents, channel authorization and append-only audit trail."""
import hashlib
import json
import re
import sqlite3
import time
from datetime import date, datetime, timezone

class AccessDenied(ValueError):
    pass

class Conflict(ValueError):
    pass

class Incidents:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS channel_policy (
                    name TEXT PRIMARY KEY, restricted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS channel_members (
                    channel TEXT NOT NULL, username TEXT NOT NULL REFERENCES users(username),
                    PRIMARY KEY(channel,username));
                CREATE TABLE IF NOT EXISTS report_batches (
                    id INTEGER PRIMARY KEY, author TEXT NOT NULL REFERENCES users(username),
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    delivery TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL,
                    UNIQUE(author, request_key));
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES report_batches(id),
                    channel TEXT NOT NULL, author TEXT NOT NULL, title TEXT NOT NULL,
                    city TEXT NOT NULL, description TEXT NOT NULL, event_time INTEGER NOT NULL,
                    active INTEGER NOT NULL, arrived INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new', assignee TEXT,
                    version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS incident_audit (
                    id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES incidents(id),
                    actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS access_audit (
                    id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    details TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS incidents_channel_created ON incidents(channel,created DESC);
                CREATE INDEX IF NOT EXISTS incident_audit_report ON incident_audit(incident_id,id);
            ''')
            columns = {row[1] for row in db.execute("PRAGMA table_info(incidents)")}
            if 'priority' not in columns:
                db.execute("ALTER TABLE incidents ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
            if 'location' not in columns:
                db.execute("ALTER TABLE incidents ADD COLUMN location TEXT NOT NULL DEFAULT ''")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
                    incident_id INTEGER NOT NULL REFERENCES incidents(id), actor TEXT NOT NULL,
                    created REAL NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS notifications_user ON notifications(username,id);
            ''')
            # A crash can leave transmission outcome unknown. Never resend automatically.
            db.execute("UPDATE report_batches SET delivery='unknown' WHERE delivery='pending'")

    @staticmethod
    def allowed(db, session, channel):
        if session['role'] == 'admin':
            return True
        row = db.execute('SELECT restricted FROM channel_policy WHERE name=?',(channel,)).fetchone()
        return not row or not row[0] or bool(db.execute(
            'SELECT 1 FROM channel_members WHERE channel=? AND username=?',
            (channel,session['username'])).fetchone())

    def require(self, session, channel):
        with self.store.connect() as db:
            if not self.allowed(db,session,channel):
                raise AccessDenied('You do not have access to this channel.')

    def create(self, session, report, key):
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):
            raise ValueError('A valid request_id is required for report submission.')
        fingerprint=hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
        now=time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self.allowed(db,session,report['channel_name']):
                raise AccessDenied('You do not have access to this channel.')
            old=db.execute('SELECT * FROM report_batches WHERE author=? AND request_key=?',
                           (session['username'],key)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:
                    raise Conflict('This request ID was already used for different report content.')
                ids=[r[0] for r in db.execute('SELECT id FROM incidents WHERE batch_id=?',(old['id'],))]
                return old['id'],ids,False,old['delivery']
            batch=db.execute('INSERT INTO report_batches(author,request_key,fingerprint,created) VALUES(?,?,?,?)',
                             (session['username'],key,fingerprint,now)).lastrowid
            ids=[]
            for event in report['events']:
                info=event['general_information']
                ident=db.execute('''INSERT INTO incidents(batch_id,channel,author,title,city,description,
                    event_time,active,arrived,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (batch,report['channel_name'],session['username'],event['event_name'],event['city'],
                     event['description'],event['date_time'],info['active'],info['forces_arrival_at_scene'],now,now)).lastrowid
                db.execute('UPDATE incidents SET priority=?,location=? WHERE id=?',
                           (event.get('priority','normal'), event.get('location',''), ident))
                ids.append(ident)
                db.execute('INSERT INTO incident_audit(incident_id,actor,action,details,at) VALUES(?,?,?,?,?)',
                           (ident,session['username'],'created','new',now))
            return batch,ids,True,'pending'

    def delivery(self,batch,state):
        with self.store.connect() as db:
            db.execute('UPDATE report_batches SET delivery=? WHERE id=?',(state,batch))

    def list(self,session,query):
        # Filter authorization in SQL before LIMIT to avoid leaking restricted content/counts.
        where=['(? = \'admin\' OR NOT EXISTS (SELECT 1 FROM channel_policy p WHERE p.name=i.channel AND p.restricted=1) OR EXISTS (SELECT 1 FROM channel_members m WHERE m.channel=i.channel AND m.username=?))']
        args=[session['role'],session['username']]
        if query.get('mine') == '1':
            where.append('i.assignee=?'); args.append(session['username'])
        for field in ('channel','status','priority'):
            if query.get(field):
                where.append('i.'+field+'=?'); args.append(query[field])
        if query.get('q'):
            term=query['q'][:120]
            where.append('(instr(lower(i.title),lower(?))>0 OR instr(lower(i.city),lower(?))>0 OR instr(lower(i.description),lower(?))>0)')
            args.extend([term]*3)
        for key,op,offset in [('from','>=',0),('to','<',86400)]:
            if query.get(key):
                day=date.fromisoformat(query[key])
                value=datetime(day.year,day.month,day.day,tzinfo=timezone.utc).timestamp()+offset
                where.append('i.created'+op+'?'); args.append(value)
        before=int(query.get('before','0'))
        if before:
            where.append('i.id<?'); args.append(before)
        with self.store.connect() as db:
            rows=db.execute('SELECT i.*,b.delivery FROM incidents i JOIN report_batches b ON b.id=i.batch_id WHERE '+
                            ' AND '.join(where)+' ORDER BY i.id DESC LIMIT 51',args).fetchall()
        return {'items':[dict(r) for r in rows[:50]],'next':rows[49]['id'] if len(rows)>50 else None}

    def detail(self,session,ident):
        with self.store.connect() as db:
            row=db.execute('SELECT i.*,b.delivery FROM incidents i JOIN report_batches b ON b.id=i.batch_id WHERE i.id=?',(ident,)).fetchone()
            if not row or not self.allowed(db,session,row['channel']):
                raise AccessDenied('Report unavailable or access denied.')
            result=dict(row)
            result['audit']=[dict(r) for r in db.execute('SELECT actor,action,details,at FROM incident_audit WHERE incident_id=? ORDER BY id',(ident,))]
            return result

    def update(self,session,data):
        if session['role'] not in ('admin','responder'):
            raise AccessDenied('Responder or administrator access required.')
        ident=data.get('id'); version=data.get('version'); state=data.get('status'); assignee=data.get('assignee') or None
        if assignee is not None and (not isinstance(assignee,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',assignee)):
            raise ValueError('Invalid assignee username.')
        if type(ident) is not int or type(version) is not int or state not in ('new','in_progress','closed'):
            raise ValueError('Invalid report update.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM incidents WHERE id=?',(ident,)).fetchone()
            if not row or not self.allowed(db,session,row['channel']):
                raise AccessDenied('Report unavailable or access denied.')
            if row['version']!=version:
                raise Conflict('This report changed. Reload it before saving.')
            if session['role']!='admin' and (assignee!=session['username'] or row['assignee'] not in (None,session['username'])):
                raise AccessDenied('You can claim unassigned reports and update only reports assigned to you.')
            if state!=row['status'] and (row['status'],state) not in {('new','in_progress'),('in_progress','closed'),('closed','in_progress')}:
                raise ValueError('Start work before closing. Closed reports can be reopened.')
            if state in ('in_progress','closed') and not assignee:
                raise ValueError('Assign a responder before starting work.')
            if assignee:
                user=db.execute('SELECT username,role FROM users WHERE username=?',(assignee,)).fetchone()
                if not user or user['role'] not in ('admin','responder') or not self.allowed(db,dict(user),row['channel']):
                    raise ValueError('Assignee must be a responder with access to this channel.')
            if row['status']==state and row['assignee']==assignee:
                return
            now=time.time()
            db.execute('UPDATE incidents SET status=?,assignee=?,version=version+1,updated=? WHERE id=?',(state,assignee,now,ident))
            if assignee and assignee != row['assignee']:
                db.execute('INSERT INTO notifications(username,incident_id,actor,created) VALUES(?,?,?,?)',
                           (assignee,ident,session['username'],now))
            detail=json.dumps({'status':{'from':row['status'],'to':state},'assignee':{'from':row['assignee'],'to':assignee}})
            db.execute('INSERT INTO incident_audit(incident_id,actor,action,details,at) VALUES(?,?,?,?,?)',
                       (ident,session['username'],'updated',detail,now))

    def admin_state(self):
        with self.store.connect() as db:
            return {'users':[dict(r) for r in db.execute('SELECT username,role FROM users ORDER BY username')],
                    'channels':[dict(r) for r in db.execute('SELECT * FROM channel_policy ORDER BY name')],
                    'members':[dict(r) for r in db.execute('SELECT * FROM channel_members ORDER BY channel,username')],
                    'audit':[dict(r) for r in db.execute('SELECT actor,action,details,at FROM access_audit ORDER BY id DESC LIMIT 50')]}

    def administer(self,session,data):
        if session['role']!='admin':
            raise AccessDenied('Administrator access required.')
        action=data.get('action')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if action=='role':
                name=data.get('username'); role=data.get('role')
                if role not in ('user','responder','admin'):
                    raise ValueError('Invalid role.')
                if name==session['username']:
                    raise ValueError('Use another administrator to change your own role.')
                row=db.execute('SELECT role FROM users WHERE username=?',(name,)).fetchone()
                if not row:
                    raise ValueError('Unknown account.')
                db.execute('UPDATE users SET role=? WHERE username=?',(role,name))
            elif action=='channel':
                name=data.get('channel'); restricted=data.get('restricted')
                if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_/-]{1,64}',name) or type(restricted) is not bool:
                    raise ValueError('Invalid channel policy.')
                db.execute('INSERT INTO channel_policy VALUES(?,?) ON CONFLICT(name) DO UPDATE SET restricted=excluded.restricted',(name,restricted))
            elif action=='member':
                name=data.get('channel'); user=data.get('username'); grant=data.get('grant')
                if type(grant) is not bool or not db.execute('SELECT 1 FROM channel_policy WHERE name=?',(name,)).fetchone():
                    raise ValueError('Create the channel policy first.')
                if not db.execute('SELECT 1 FROM users WHERE username=?',(user,)).fetchone():
                    raise ValueError('Unknown account.')
                if grant:
                    db.execute('INSERT OR IGNORE INTO channel_members VALUES(?,?)',(name,user))
                else:
                    db.execute('DELETE FROM channel_members WHERE channel=? AND username=?',(name,user))
            else:
                raise ValueError('Unknown administration action.')
            db.execute('INSERT INTO access_audit(actor,action,details,at) VALUES(?,?,?,?)',
                       (session['username'],action,json.dumps(data),time.time()))

    def overview(self, session):
        with self.store.connect() as db:
            rows = db.execute("""SELECT i.status, i.priority, i.assignee, i.created FROM incidents i
                WHERE (?='admin' OR NOT EXISTS (SELECT 1 FROM channel_policy p WHERE p.name=i.channel AND p.restricted=1)
                OR EXISTS (SELECT 1 FROM channel_members m WHERE m.channel=i.channel AND m.username=?))""",
                (session['role'],session['username'])).fetchall()
        opened = [r for r in rows if r['status'] != 'closed']
        return {'open':len(opened), 'urgent':sum(r['priority']=='urgent' for r in opened),
                'mine':sum(r['assignee']==session['username'] for r in opened),
                'aging':sum(r['created'] < time.time()-86400 for r in opened),
                'closed':sum(r['status']=='closed' for r in rows)}

    def notifications(self, session):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("""SELECT n.id,n.incident_id,n.actor,n.created,n.seen,i.title
                FROM notifications n JOIN incidents i ON i.id=n.incident_id
                WHERE n.username=? AND (?='admin' OR NOT EXISTS
                (SELECT 1 FROM channel_policy p WHERE p.name=i.channel AND p.restricted=1) OR EXISTS
                (SELECT 1 FROM channel_members m WHERE m.channel=i.channel AND m.username=?))
                ORDER BY n.id DESC LIMIT 20""", (session['username'],session['role'],session['username']))]

    def read_notifications(self, session, ids):
        if not isinstance(ids,list) or len(ids)>20 or any(type(i) is not int for i in ids):
            raise ValueError('Invalid notification IDs.')
        with self.store.connect() as db:
            db.executemany('UPDATE notifications SET seen=1 WHERE id=? AND username=?',
                           [(i,session['username']) for i in ids])
