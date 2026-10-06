import base64, http.client, json, os, socket, subprocess, sys, tempfile, time, hashlib
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
STREAM = os.environ.get('WAYCAST_STREAM') or os.path.join(ROOT, 'stream.py')
BIN = os.path.join(HERE, 'bin')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(extra=(), output='SYNTH-A', password='pw', fps=None,
                 frame_size=None, split=False, env_extra=None):
    tmp = tempfile.mkdtemp(prefix='waycast-test-')
    port = free_port()
    env = os.environ.copy()
    env['PATH'] = BIN + os.pathsep + env.get('PATH', '')
    env['FAKE_ARGV_LOG'] = os.path.join(tmp, 'argv.jsonl')
    env['FAKE_STDIN_LOG'] = os.path.join(tmp, 'stdin.bin')
    env['FAKE_LOG'] = os.path.join(tmp, 'writes.jsonl')
    if frame_size is not None:
        env['FAKE_FRAME_SIZE'] = str(frame_size)
    if split:
        env['FAKE_SPLIT'] = '1'
    for key, value in (env_extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    argv = [sys.executable, STREAM, '--password', password, '--port', str(port)]
    if output:
        argv += ['--output', output]
    if fps is not None:
        argv += ['--fps', str(fps)]
    argv += list(extra)
    log = open(os.path.join(tmp, 'server.log'), 'w')
    proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('server died: ' + open(os.path.join(tmp, 'server.log')).read())
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    else:
        proc.kill()
        raise RuntimeError('server did not open its port')
    return SimpleNamespace(proc=proc, port=port, tmp=tmp, password=password, log=log,
                           argv_log=os.path.join(tmp, 'argv.jsonl'),
                           stdin_log=os.path.join(tmp, 'stdin.bin'),
                           write_log=os.path.join(tmp, 'writes.jsonl'))


def stop_server(srv):
    try:
        srv.proc.terminate()
        try:
            srv.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.proc.kill()
            srv.proc.wait()
    finally:
        srv.log.close()


def http_get(port, path, password=None, timeout=5):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    headers = {}
    if password is not None:
        headers['Authorization'] = 'Basic ' + base64.b64encode(b'x:' + password.encode()).decode()
    conn.request('GET', path, headers=headers)
    resp = conn.getresponse()
    body = resp.read()
    out = (resp.status, dict(resp.getheaders()), body)
    conn.close()
    return out


def recv_frames(port, password, duration, max_frames=None):
    s = socket.create_connection(('127.0.0.1', port), timeout=duration + 5)
    tok = base64.b64encode(b'x:' + password.encode()).decode()
    s.sendall((b'GET /stream HTTP/1.1\r\nHost: 127.0.0.1\r\n'
               b'Authorization: Basic ' + tok.encode() + b'\r\n\r\n'))
    frames = []
    buf = b''
    end = time.monotonic() + duration
    while time.monotonic() < end:
        if max_frames and len(frames) >= max_frames:
            break
        s.settimeout(max(0.05, end - time.monotonic()))
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(b'\r\n\r\n')
            if i == -1:
                break
            header = buf[:i].decode(errors='ignore')
            length = None
            for line in header.split('\r\n'):
                if line.lower().startswith('content-length:'):
                    try:
                        length = int(line.split(':', 1)[1].strip())
                    except ValueError:
                        length = None
            if length is None:
                buf = buf[i + 4:]
                continue
            if len(buf) < i + 4 + length + 2:
                break
            data = buf[i + 4:i + 4 + length]
            frames.append((time.monotonic(), data))
            buf = buf[i + 4 + length + 2:]
    s.close()
    return frames


def read_writes(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            t, md5, size = json.loads(line)
            out.append((t, md5, size))
    return out


def read_argv(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def jpeg_ok(data):
    return data[:2] == b'\xff\xd8' and data[-2:] == b'\xff\xd9'


def md5(data):
    return hashlib.md5(data).hexdigest()


def percentile(vals, p):
    if not vals:
        return float('nan')
    s = sorted(vals)
    k = min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))
    return s[k]
