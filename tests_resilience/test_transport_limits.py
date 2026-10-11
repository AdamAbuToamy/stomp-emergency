"""Real-socket fault tests. Start an isolated JVM; no dashboard or account database."""
import os,socket,subprocess,tempfile,time,unittest,uuid,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PORT=17779
class Peer:
    def __init__(self,small=False):
        self.sock=socket.socket();self.sock.settimeout(4)
        if small:self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024)
        try:self.sock.connect(('127.0.0.1',PORT))
        except OSError:self.sock.close();raise
        self.buffer=b''
    def send(self,command,headers={},body=''):
        self.sock.sendall((command+'\n'+''.join(k+':'+str(v)+'\n' for k,v in headers.items())+'\n'+body+'\0').encode())
    def read(self):
        while b'\0' not in self.buffer:
            data=self.sock.recv(65536)
            if not data:raise EOFError()
            self.buffer+=data
        frame,self.buffer=self.buffer.split(b'\0',1)
        return frame.decode().lstrip('\n')
    def login(self,name=None):
        self.send('CONNECT',{'accept-version':'1.2','host':'stomp.cs.bgu.ac.il','login':name or 'fault_'+uuid.uuid4().hex,'passcode':'test'})
        assert self.read().startswith('CONNECTED')
    def join(self,channel,receipt='ready'):
        self.send('SUBSCRIBE',{'destination':channel,'id':'0','receipt':receipt})
        assert self.read().startswith('RECEIPT')
    def close(self):self.sock.close()

class TransportLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory();cls.log=open(Path(cls.folder.name)/'console.log','w+')
        env=dict(os.environ,STOMP_BIND='127.0.0.1');env.pop('STOMP_BRIDGE_SECRET',None)
        cls.mode=os.environ.get('RESILIENCE_MODE','tpc')
        cls.proc=subprocess.Popen(['java','-Dstomp.maxFrameBytes=65536','-Dstomp.maxQueuedBytes=131072',
            '-Dstomp.writeTimeoutMillis=300','-Dstomp.sendBufferBytes=4096','-cp',str(ROOT/'server/target/classes'),
            'io.github.adamabutoamy.stomp.protocol.StompServer',str(PORT),cls.mode],cwd=cls.folder.name,env=env,stdout=cls.log,stderr=cls.log)
        for _ in range(100):
            if cls.proc.poll() is not None:raise RuntimeError('Test server exited')
            try:p=Peer();p.close();return
            except OSError:time.sleep(.05)
        raise RuntimeError('Startup timeout')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.wait(timeout=5);cls.log.close();cls.folder.cleanup()
    def peer(self,small=False):
        p=Peer(small);self.addCleanup(p.close);return p
    def test_01_oversized_unterminated_frame_closes_only_offender(self):
        bad=self.peer();bad.login()
        bad.sock.sendall(b'SEND\ndestination:unused\n\n'+b'x'*65537)
        bad.sock.settimeout(2)
        try:self.assertEqual(bad.sock.recv(1),b'')
        except ConnectionResetError:pass
        good=self.peer();good.login()
    def test_02_stalled_subscriber_does_not_stall_other_clients(self):
        channel='load_'+uuid.uuid4().hex
        slow=self.peer(True);slow.login();slow.join(channel)
        sender=self.peer();sender.login();sender.join(channel)
        for i in range(180):
            body=str(i)+':'+('x'*8192)
            sender.send('SEND',{'destination':channel},body)
            message=sender.read()
            self.assertTrue(message.startswith('MESSAGE'))
            self.assertEqual(message.split('\n\n',1)[1],body)
        # Confirm the protective path actually ran, not just that buffers absorbed data.
        self.log.flush();self.log.seek(0);logs=self.log.read()
        marker='SLOW_CONSUMER' if self.mode=='reactor' else 'WRITE_TIMEOUT'
        self.assertIn(marker,logs)
        healthy=self.peer();healthy.login()
    def test_03_response_and_broadcast_frames_do_not_interleave(self):
        channel='mixed_'+uuid.uuid4().hex
        a=self.peer();a.login();a.join(channel)
        b=self.peer();b.login();b.join(channel)
        errors=[]
        def publish():
            try:
                for i in range(80):
                    a.send('SEND',{'destination':channel},'payload-'+str(i));a.read()
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=publish);thread.start()
        for i in range(30):b.send('SUBSCRIBE',{'destination':'other_'+str(i),'id':str(i+1),'receipt':'r'+str(i)})
        messages=[];receipts=[]
        for _ in range(110):
            frame=b.read();head,body=frame.split('\n\n',1)
            if head.startswith('MESSAGE\n'):messages.append(body)
            elif head.startswith('RECEIPT\n'):receipts.append(head.split('receipt-id:',1)[1])
            else:self.fail('Unexpected or corrupted frame: '+head[:80])
        thread.join(timeout=5);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(messages,['payload-'+str(i) for i in range(80)])
        self.assertEqual(set(receipts),{'r'+str(i) for i in range(30)})
