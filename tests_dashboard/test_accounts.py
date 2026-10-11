"""Run against real Java/C++ processes: python3 -m unittest discover -s tests_dashboard -v"""
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8080'
PASSWORD = 'Test-phrase-593!'


class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                   urllib.request.HTTPCookieProcessor(self.jar))
    def request(self, path, data=None, origin=BASE):
        if isinstance(data,dict) and data.get('action')=='report' and 'request_id' not in data:
            data=dict(data,request_id=uuid.uuid4().hex)
        headers = {'Origin': origin, 'X-STOMP-UI': '1', 'Content-Type': 'application/json'}
        req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers=headers)
        try:
            response = self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())


class AccountsIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='stomp-auth-test-')
        cls.log = tempfile.TemporaryFile(mode='w+')
        cls.env = dict(os.environ, STOMP_DATA_DIR=cls.directory.name)
        cls.mode = os.environ.get('DASHBOARD_TEST_MODE', 'tpc')
        cls.process = None
        cls.start()

    @classmethod
    def start(cls):
        cls.process = subprocess.Popen([sys.executable, 'scripts/run_dashboard.py', '--mode', cls.mode],
                                       cwd=ROOT, env=cls.env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            try:
                if Browser().request('/health')[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(.1)
        raise RuntimeError('Startup timeout')

    @classmethod
    def stop(cls):
        cls.process.terminate()
        cls.process.wait(timeout=20)

    @classmethod
    def tearDownClass(cls):
        if cls.process and cls.process.poll() is None:
            cls.stop()
        cls.log.close()
        cls.directory.cleanup()

    def account(self, name):
        browser = Browser()
        self.assertEqual(browser.request('/auth/register', {'username':name, 'password':PASSWORD})[0], 201)
        self.assertEqual(browser.request('/session')[1]['user']['name'], name)
        self.addCleanup(lambda: browser.request('/auth/logout', {}))
        return browser

    def test_01_registration_password_storage_and_duplicate(self):
        browser = self.account('alice')
        self.assertEqual(browser.request('/auth/register', {'username':'alice', 'password':PASSWORD})[0], 400)
        with sqlite3.connect(Path(self.directory.name)/'accounts.sqlite3') as db:
            row=db.execute('SELECT password_hash, salt FROM users WHERE username=?',('alice',)).fetchone()
            self.assertNotEqual(row[0],PASSWORD)
            self.assertEqual(len(row[0]),64)
            cookie = next(iter(browser.jar)).value
            self.assertNotEqual(db.execute('SELECT digest FROM sessions WHERE username=?',('alice',)).fetchone()[0], cookie)
        cookie=next(iter(browser.jar))
        self.assertTrue(cookie.has_nonstandard_attr('HttpOnly'))
        self.assertEqual(cookie.get_nonstandard_attr('SameSite'),'Strict')

    def test_02_auth_and_origin_guards(self):
        anon=Browser()
        self.assertEqual(anon.request('/command',{'action':'join','channel':'police'})[0],401)
        self.assertEqual(anon.request('/server-logs')[0],401)
        self.assertEqual(anon.request('/auth/login',{'username':'alice','password':'wrong-password'})[0],401)
        self.assertEqual(anon.request('/auth/register',{'username':'evil','password':PASSWORD},origin='https://evil.example')[0],403)
        self.assertEqual(anon.request('/session')[1]['user'],None)

    def test_03_isolation_delivery_summary_and_independent_cursors(self):
        a=self.account('bob'); b=self.account('carol')
        self.assertEqual(a.request('/command',{'action':'join','channel':'police'})[0],200)
        self.assertEqual(b.request('/command',{'action':'join','channel':'baka'})[0],200)
        report=json.loads((ROOT/'examples/police-demo.json').read_text())
        self.assertEqual(b.request('/command',{'action':'report','report':report})[0],400)
        self.assertEqual(b.request('/session')[1]['user']['name'],'carol')
        self.assertEqual(a.request('/command',{'action':'report','report':report})[0],200)
        time.sleep(.2)
        first=a.request('/events?after=0')[1]
        self.assertEqual(first,a.request('/events?after=0')[1])
        self.assertTrue(any(e['type']=='report_received' for e in first['events']))
        self.assertFalse(any(e['type']=='report_received' for e in b.request('/events?after=0')[1]['events']))
        self.assertEqual(a.request('/command',{'action':'summary','channel':'police','user':'bob'})[0],200)
        snap=a.request('/session')[1]
        self.assertTrue(any('Total: 1' in e.get('content','') for e in snap['events']))
        self.assertEqual(b.request('/command',{'action':'join','channel':'police'})[0],200)
        self.assertEqual(a.request('/command',{'action':'report','report':report})[0],200)
        time.sleep(.2)
        self.assertTrue(any(e['type']=='report_received' and e['user']=='bob' for e in b.request('/session')[1]['events']))

    def test_04_admin_is_server_enforced(self):
        browser=self.account('david')
        self.assertEqual(browser.request('/server-status')[0],403)
        self.assertEqual(browser.request('/server-logs')[0],403)
        subprocess.run([sys.executable,'scripts/manage_users.py','promote','david'],cwd=ROOT,env=self.env,check=True,stdout=subprocess.DEVNULL)
        self.assertEqual(browser.request('/server-status')[0],200)
        self.assertTrue(browser.request('/server-status')[1]['available'])
        self.assertEqual(browser.request('/server-logs')[0],200)
        self.assertEqual(browser.request('/session')[1]['user']['role'],'admin')

    def test_05_logout_revocation_and_new_login(self):
        a=self.account('erica')
        old_cookie=next(iter(a.jar)).value
        other=Browser()
        self.assertEqual(other.request('/auth/login',{'username':'erica','password':PASSWORD})[0],200)
        self.assertEqual(a.request('/events?after=0')[0],401)
        self.assertEqual(other.request('/auth/logout',{})[0],200)
        self.assertEqual(other.request('/command',{'action':'join','channel':'police'})[0],401)

    def test_06_input_validation_and_internal_password_rejection(self):
        browser=self.account('frank')
        self.assertEqual(browser.request('/command',{'action':'join','channel':'police\nlogout'})[0],400)
        with socket.create_connection(('127.0.0.1',7777),timeout=2) as sock:
            sock.sendall(('CONNECT\naccept-version:1.2\nhost:stomp.cs.bgu.ac.il\nlogin:outsider\npasscode:'+PASSWORD+'\n\n\0').encode())
            self.assertIn(b'ERROR',sock.recv(4096))

    def test_07_accounts_and_cookie_survive_restart(self):
        browser=self.account('grace')
        self.stop(); self.start()
        snap=browser.request('/session')[1]
        self.assertEqual(snap['user']['name'],'grace')
        self.assertTrue(any(e['type']=='login_success' for e in snap['events']))
        self.assertEqual(browser.request('/auth/logout',{})[0],200)
        self.assertEqual(browser.request('/auth/login',{'username':'grace','password':PASSWORD})[0],200)

    def test_08_durable_workflow_idempotency_and_conflict(self):
        reporter=self.account('hannah'); responder=self.account('isaac')
        admin=self.account('julia')
        subprocess.run([sys.executable,'scripts/manage_users.py','promote','julia'],cwd=ROOT,env=self.env,check=True,stdout=subprocess.DEVNULL)
        self.assertEqual(admin.request('/access',{'action':'role','username':'isaac','role':'responder'})[0],200)
        self.assertEqual(responder.request('/incidents')[0],401)
        self.assertEqual(responder.request('/auth/login',{'username':'isaac','password':PASSWORD})[0],200)
        self.assertEqual(reporter.request('/command',{'action':'join','channel':'police'})[0],200)
        report=json.loads((ROOT/'examples/police-demo.json').read_text())
        payload={'action':'report','report':report,'request_id':uuid.uuid4().hex}
        code,result=reporter.request('/command',payload)
        self.assertEqual(code,200)
        ident=result['incident_ids'][0]
        self.assertEqual(reporter.request('/command',payload)[1]['incident_ids'],[ident])
        payload['report']['events'][0]['event_name']='Changed content'
        self.assertEqual(reporter.request('/command',payload)[0],409)
        self.assertEqual(reporter.request('/incidents/update',{'id':ident,'version':1,'status':'in_progress','assignee':'hannah'})[0],403)
        update={'id':ident,'version':1,'status':'in_progress','assignee':'isaac'}
        self.assertEqual(responder.request('/incidents/update',update)[0],200)
        self.assertEqual(responder.request('/incidents/update',update)[0],409)
        self.assertEqual(responder.request('/incidents/update',dict(update,version=2,status='closed'))[0],200)
        detail=reporter.request('/incidents/'+str(ident))[1]
        self.assertEqual(detail['status'],'closed'); self.assertEqual(len(detail['audit']),3)
        self.assertTrue(any(x['id']==ident for x in reporter.request('/incidents?status=closed&channel=police&q=Training')[1]['items']))
        self.assertFalse(any(x['id']==ident for x in reporter.request('/incidents?status=new')[1]['items']))
        self.stop(); self.start()
        detail=reporter.request('/incidents/'+str(ident))[1]
        self.assertEqual(detail['status'],'closed'); self.assertEqual(detail['assignee'],'isaac')

    def test_09_restricted_channel_revocation_and_role_guards(self):
        admin=self.account('kevin'); user=self.account('laura'); outsider=self.account('maria')
        subprocess.run([sys.executable,'scripts/manage_users.py','promote','kevin'],cwd=ROOT,env=self.env,check=True,stdout=subprocess.DEVNULL)
        self.assertEqual(user.request('/access')[0],403)
        self.assertEqual(user.request('/access',{'action':'role','username':'laura','role':'admin'})[0],403)
        self.assertEqual(admin.request('/access',{'action':'channel','channel':'private','restricted':True})[0],200)
        self.assertEqual(admin.request('/access',{'action':'member','channel':'private','username':'laura','grant':True})[0],200)
        for browser,name in [(user,'laura'),(outsider,'maria')]:
            self.assertEqual(browser.request('/auth/login',{'username':name,'password':PASSWORD})[0],200)
        self.assertEqual(outsider.request('/command',{'action':'join','channel':'private'})[0],403)
        self.assertEqual(user.request('/command',{'action':'join','channel':'private'})[0],200)
        report=json.loads((ROOT/'examples/police-demo.json').read_text()); report['channel_name']='private'
        ident=user.request('/command',{'action':'report','report':report})[1]['incident_ids'][0]
        self.assertEqual(outsider.request('/incidents/'+str(ident))[0],403)
        self.assertEqual(outsider.request('/incidents?channel=private')[1]['items'],[])
        self.assertEqual(admin.request('/access',{'action':'member','channel':'private','username':'laura','grant':False})[0],200)
        self.assertEqual(user.request('/events')[0],401)
        self.assertEqual(user.request('/auth/login',{'username':'laura','password':PASSWORD})[0],200)
        self.assertEqual(user.request('/incidents/'+str(ident))[0],403)
        self.assertEqual(user.request('/command',{'action':'join','channel':'private'})[0],403)

    def test_10_eight_character_password_and_duplicate_no_takeover(self):
        a=Browser(); b=Browser()
        self.assertEqual(a.request('/auth/register',{'username':'nancy','password':'1234567'})[0],400)
        self.assertEqual(a.request('/auth/register',{'username':'nancy','password':'Pass123!'})[0],201)
        self.assertEqual(a.request('/session')[1]['user']['name'],'nancy')
        self.assertEqual(b.request('/auth/register',{'username':'nancy','password':'Other123!'})[0],400)
        self.assertIsNone(b.request('/session')[1]['user'])
        self.assertEqual(a.request('/session')[1]['user']['name'],'nancy')
        self.assertEqual(a.request('/auth/logout',{})[0],200)

    def test_11_change_password_verifies_current_revokes_and_persists(self):
        browser=self.account('olivia')
        token=next(iter(browser.jar)).value
        self.assertEqual(Browser().request('/auth/password',{})[0],401)
        payload={'current_password':PASSWORD,'new_password':'NewPass8!','confirm_password':'NewPass8!'}
        self.assertEqual(browser.request('/auth/password',dict(payload,current_password='WrongPass8!'))[0],400)
        self.assertEqual(browser.request('/auth/password',dict(payload,confirm_password='Mismatch8!'))[0],400)
        self.assertEqual(browser.request('/auth/password',dict(payload,new_password='short',confirm_password='short'))[0],400)
        self.assertEqual(browser.request('/auth/password',payload)[0],200)
        self.assertIsNone(browser.request('/session')[1]['user'])
        stale=Browser()
        import http.cookiejar
        stale.jar.set_cookie(http.cookiejar.Cookie(0,'stomp_session',token,None,False,'127.0.0.1',False,False,'/',True,False,None,True,None,None,{}))
        self.assertEqual(stale.request('/incidents')[0],401)
        self.assertEqual(browser.request('/auth/login',{'username':'olivia','password':PASSWORD})[0],401)
        self.stop(); self.start()
        self.assertEqual(browser.request('/auth/login',{'username':'olivia','password':'NewPass8!'})[0],200)
        self.assertEqual(browser.request('/auth/logout',{})[0],200)

    def test_12_priorities_overview_and_private_assignment_notifications(self):
        admin=self.account('peter'); worker=self.account('quinn')
        subprocess.run([sys.executable,'scripts/manage_users.py','promote','peter'],cwd=ROOT,env=self.env,check=True,stdout=subprocess.DEVNULL)
        self.assertEqual(admin.request('/access',{'action':'role','username':'quinn','role':'responder'})[0],200)
        self.assertEqual(worker.request('/auth/login',{'username':'quinn','password':PASSWORD})[0],200)
        self.assertEqual(admin.request('/command',{'action':'join','channel':'operations'})[0],200)
        report=json.loads((ROOT/'examples/police-demo.json').read_text()); report['channel_name']='operations'
        report['events'][0].update(priority='urgent',location='Building C · Floor 2')
        ident=admin.request('/command',{'action':'report','report':report})[1]['incident_ids'][0]
        detail=admin.request('/incidents/'+str(ident))[1]
        self.assertEqual(detail['priority'],'urgent'); self.assertEqual(detail['location'],'Building C · Floor 2')
        self.assertEqual(admin.request('/incidents/update',{'id':ident,'version':1,'status':'in_progress','assignee':'quinn'})[0],200)
        self.assertEqual(worker.request('/overview')[1]['mine'],1)
        self.assertEqual(worker.request('/incidents?mine=1&priority=urgent')[1]['items'][0]['id'],ident)
        self.assertEqual(worker.request('/incidents?mine=1&priority=low')[1]['items'],[])
        notice=worker.request('/notifications')[1]['items'][0]
        self.assertEqual(notice['incident_id'],ident); self.assertEqual(notice['seen'],0)
        admin.request('/notifications/read',{'ids':[notice['id']]})
        self.assertEqual(worker.request('/notifications')[1]['items'][0]['seen'],0)
        worker.request('/notifications/read',{'ids':[notice['id']]})
        self.assertEqual(worker.request('/notifications')[1]['items'][0]['seen'],1)
        report['events'][0]['priority']='invalid'
        self.assertEqual(admin.request('/command',{'action':'report','report':report})[0],400)
        self.assertEqual(admin.request('/access',{'action':'channel','channel':'operations','restricted':True})[0],200)
        worker.request('/auth/login',{'username':'quinn','password':PASSWORD})
        self.assertEqual(worker.request('/notifications')[1]['items'],[])
        self.assertEqual(worker.request('/overview')[1]['mine'],0)
        self.assertEqual(Browser().request('/overview')[0],401)
        self.assertEqual(Browser().request('/notifications')[0],401)
