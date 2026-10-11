"""Storage invariants: migration, crash recovery and simultaneous writers."""
import concurrent.futures
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from auth import Store
from incidents import Incidents, Conflict

class IncidentStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store=Store(self.folder.name)
        self.store.register('operator','Password8!')
        self.store.promote('operator')
        self.session={'username':'operator','role':'admin'}
        self.report={'channel_name':'police','events':[{'event_name':'Example','city':'City','description':'Text',
                    'date_time':1700000000,'general_information':{'active':True,'forces_arrival_at_scene':False}}]}
        self.registry=Incidents(self.store)

    def test_crash_recovery_does_not_lose_user_or_resend_pending_report(self):
        token,_=self.store.issue('operator')
        batch,ids,_,_=self.registry.create(self.session,self.report,'durable-request-123')
        restarted=Incidents(Store(self.folder.name))
        self.assertTrue(self.store.verify('operator','Password8!'))
        self.assertEqual(self.store.session(token)['role'],'admin')
        self.assertEqual(restarted.detail(self.session,ids[0])['delivery'],'unknown')
        replay=restarted.create(self.session,self.report,'durable-request-123')
        self.assertFalse(replay[2]); self.assertEqual(replay[1],ids)

    def test_concurrent_updates_have_one_winner_and_one_audit_entry(self):
        ident=self.registry.create(self.session,self.report,'concurrent-report-123')[1][0]
        def save(_):
            try:
                self.registry.update(self.session,{'id':ident,'version':1,'status':'in_progress','assignee':'operator'})
                return 'saved'
            except Conflict: return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(save,range(2))),['saved','conflict'])
        detail=self.registry.detail(self.session,ident)
        self.assertEqual(detail['version'],2); self.assertEqual(len(detail['audit']),2)

    def test_concurrent_retries_create_one_batch(self):
        def create(_): return self.registry.create(self.session,self.report,'same-request-id-123')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(create,range(2)))
        self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(sum(r[2] for r in results),1)

    def test_new_cannot_jump_to_closed(self):
        ident=self.registry.create(self.session,self.report,'invalid-transition-123')[1][0]
        with self.assertRaises(ValueError):
            self.registry.update(self.session,{'id':ident,'version':1,'status':'closed','assignee':'operator'})
        self.assertEqual(self.registry.detail(self.session,ident)['version'],1)
