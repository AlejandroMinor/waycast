#!/usr/bin/env python3
import subprocess, socket, threading, os, signal, sys, time, argparse, base64, secrets, re, json, urllib.parse

parser = argparse.ArgumentParser(description='Stream a Wayland desktop to the Meta Quest browser')
parser.add_argument('--fps',      type=int, default=20,   help='Frames per second (default: 20)')
parser.add_argument('--quality',  type=int, default=4,    help='MJPEG quality 1=best 31=worst (default: 4)')
parser.add_argument('--port',     type=int, default=8080, help='HTTP port (default: 8080)')
parser.add_argument('--output',   type=str, default=None, help='Monitor to capture, e.g. eDP-1, HDMI-A-1')
parser.add_argument('--password', type=str, default=None, help='Access password (one is generated if omitted)')
parser.add_argument('--sharp',    action='store_true', help='Sharper text (4:4:4) at the cost of ~2x data and more latency')
parser.add_argument('--scale',    type=int, default=None, help='Downscale to this height in px (e.g. 720). Less data = less latency')
args = parser.parse_args()

ENV      = os.environ.copy()
FPS      = args.fps
QUALITY  = args.quality
PORT     = args.port
PASSWORD = args.password or secrets.token_urlsafe(8)

latest_frame   = None
frame_lock     = threading.Lock()
frame_event    = threading.Event()
running        = True
current_output = args.output
restart_event  = threading.Event()
current_proc   = None


def check_auth(raw):
    for line in raw.split('\r\n'):
        if line.lower().startswith('authorization: basic '):
            try:
                decoded = base64.b64decode(line[21:]).decode()
                _, pwd   = decoded.split(':', 1)
                return pwd == PASSWORD
            except Exception:
                return False
    return False


def send_401(conn):
    body = b'Unauthorized'
    resp = (
        b'HTTP/1.1 401 Unauthorized\r\n'
        b'WWW-Authenticate: Basic realm="waycast"\r\n'
        b'Content-Type: text/plain\r\n'
        b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
        b'Connection: close\r\n\r\n' + body
    )
    try:
        conn.sendall(resp)
    except Exception:
        pass
    finally:
        conn.close()


def build_cmd():
    output_flag = f'-o {current_output} ' if current_output else ''
    pixfmt = 'yuvj444p' if args.sharp else 'yuvj420p'
    scale_flag = f'-F scale=-2:{args.scale} ' if args.scale else ''
    return (
        f'echo y | wf-recorder -c mjpeg -m mpjpeg -r {FPS} -D '
        f'{scale_flag}-x {pixfmt} -p qmin={QUALITY} -p qmax={QUALITY} '
        f'{output_flag}-f /dev/stdout 2>/dev/null'
    )


def capture_loop():
    global latest_frame, current_proc
    print(f'Capturing @ {FPS}fps  quality={QUALITY}'
          + (f'  output={current_output}' if current_output else ''))

    while running:
        cmd = build_cmd()
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                preexec_fn=os.setsid, env=ENV)
        current_proc = proc
        buf = b''
        try:
            while running and not restart_event.is_set():
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    s = buf.find(b'\xff\xd8')
                    if s == -1:
                        buf = b''
                        break
                    e = buf.find(b'\xff\xd9', s + 2)
                    if e == -1:
                        buf = buf[s:]
                        break
                    with frame_lock:
                        latest_frame = buf[s:e + 2]
                    frame_event.set()
                    frame_event.clear()
                    buf = buf[e + 2:]
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            proc.wait()
        if restart_event.is_set():
            restart_event.clear()
            print(f'Switching to output={current_output}')
            continue
        if running:
            print('Capture interrupted, restarting in 1s...')
            time.sleep(1)


def list_monitors():
    try:
        out = subprocess.run(['wf-recorder', '-L'], capture_output=True,
                             text=True, env=ENV, timeout=5).stdout
        return re.findall(r'Name:\s*(\S+)', out)
    except Exception:
        return []


def do_switch(name):
    global current_output, current_proc
    if name not in list_monitors():
        return False
    current_output = name
    restart_event.set()
    p = current_proc
    if p is not None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass
    return True


def stream_client(conn):
    try:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
        except Exception:
            pass
        conn.sendall(
            b'HTTP/1.1 200 OK\r\n'
            b'Content-Type: multipart/x-mixed-replace; boundary=frame\r\n'
            b'Cache-Control: no-cache\r\n'
            b'Connection: close\r\n\r\n'
        )
        last = None
        while True:
            frame_event.wait(timeout=1.0)
            with frame_lock:
                frame = latest_frame
            if frame is None or frame is last:
                continue
            last = frame
            hdr = (
                f'--frame\r\nContent-Type: image/jpeg\r\n'
                f'Content-Length: {len(frame)}\r\n\r\n'
            ).encode()
            conn.sendall(hdr + frame + b'\r\n')
    except Exception:
        pass
    finally:
        conn.close()


INDEX = (
    '<!DOCTYPE html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>Stream</title>'
    '<style>'
    '*{margin:0;padding:0;box-sizing:border-box}'
    'body{background:#000;display:flex;align-items:center;justify-content:center;min-height:100vh}'
    'img{max-width:100vw;max-height:100vh;object-fit:contain;display:block}'
    '#fs{'
      'position:fixed;bottom:20px;right:20px;'
      'background:rgba(255,255,255,.15);border:none;border-radius:8px;'
      'width:48px;height:48px;cursor:pointer;'
      'display:flex;align-items:center;justify-content:center;'
    '}'
    '#fs:hover{background:rgba(255,255,255,.3)}'
    '#bar{position:fixed;top:12px;left:12px;display:flex;gap:8px;z-index:10;flex-wrap:wrap}'
    '#bar button{'
      'background:rgba(255,255,255,.15);color:#fff;border:none;border-radius:8px;'
      'padding:8px 14px;font-size:14px;cursor:pointer;font-family:sans-serif;opacity:.55'
    '}'
    '#bar button:hover{opacity:1;background:rgba(255,255,255,.3)}'
    '#bar button.active{opacity:1;background:rgba(80,160,255,.85)}'
    '#s{opacity:0;transition:opacity .25s}'
    '#s.on{opacity:1}'
    '#msg{'
      'position:fixed;inset:0;z-index:5;'
      'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;'
      'color:#9aa6b2;font-family:sans-serif;text-align:center'
    '}'
    '#msg.hide{display:none}'
    '#msg .spin{'
      'width:44px;height:44px;border-radius:50%;'
      'border:3px solid rgba(255,255,255,.15);border-top-color:#5aa0ff;'
      'animation:spin 1s linear infinite'
    '}'
    '#msg .t{font-size:18px;letter-spacing:.5px}'
    '@keyframes spin{to{transform:rotate(360deg)}}'
    '</style></head>'
    '<body>'
    '<div id="bar"></div>'
    '<div id="msg"><div class="spin"></div><div class="t" id="msgt">Waiting for video…</div></div>'
    '<img id="s" src="/stream">'
    '<button id="fs" title="Fullscreen">'
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="white">'
        '<path d="M1 1h6v2H3v4H1V1zm12 0h6v6h-2V3h-4V1zM1 13h2v4h4v2H1v-6zm14 4h-4v2h6v-6h-2v4z"/>'
      '</svg>'
    '</button>'
    '<script>'
    'var img=document.getElementById("s");'
    'var msg=document.getElementById("msg"),msgt=document.getElementById("msgt");'
    'function reconnect(){img.src="/stream?"+Date.now()}'
    'img.onload=function(){img.classList.add("on");msg.classList.add("hide")};'
    'img.onerror=function(){'
      'img.classList.remove("on");'
      'msg.classList.remove("hide");'
      'msgt.textContent="Reconnecting…";'
      'setTimeout(reconnect,2000)'
    '};'
    'var fsBtn=document.getElementById("fs");'
    'fsBtn.onclick=function(){'
      'document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen()'
    '};'
    'document.addEventListener("fullscreenchange",function(){'
      'fsBtn.style.display=document.fullscreenElement?"none":"flex"'
    '});'
    'var bar=document.getElementById("bar");'
    'function loadMonitors(){'
      'fetch("/monitors").then(function(r){return r.json()}).then(function(d){'
        'bar.innerHTML="";'
        'if(!d.monitors||d.monitors.length<2)return;'
        'd.monitors.forEach(function(m){'
          'var b=document.createElement("button");'
          'b.textContent=m;'
          'if(m===d.current)b.className="active";'
          'b.onclick=function(){'
            'fetch("/switch?output="+encodeURIComponent(m)).then(function(){'
              'Array.prototype.forEach.call(bar.children,function(c){'
                'c.className=(c.textContent===m)?"active":""'
              '})'
            '})'
          '};'
          'bar.appendChild(b)'
        '})'
      '}).catch(function(){})'
    '}'
    'loadMonitors();'
    '</script>'
    '</body></html>'
).encode()


def index_client(conn):
    resp = (
        b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n'
        b'Content-Length: ' + str(len(INDEX)).encode() + b'\r\n\r\n' + INDEX
    )
    try:
        conn.sendall(resp)
    except Exception:
        pass
    finally:
        conn.close()


def json_response(conn, obj, ok=True):
    body = json.dumps(obj).encode()
    line = b'200 OK' if ok else b'400 Bad Request'
    resp = (
        b'HTTP/1.1 ' + line + b'\r\nContent-Type: application/json\r\n'
        b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
        b'Connection: close\r\n\r\n' + body
    )
    try:
        conn.sendall(resp)
    except Exception:
        pass
    finally:
        conn.close()


def dispatch(conn):
    try:
        data = conn.recv(2048).decode(errors='ignore')
        if not check_auth(data):
            send_401(conn)
            return
        path = data.split(' ')[1] if ' ' in data else '/'
        if path.startswith('/monitors'):
            json_response(conn, {'monitors': list_monitors(), 'current': current_output})
        elif path.startswith('/switch'):
            query = path.split('?', 1)[1] if '?' in path else ''
            params = dict(p.split('=', 1) for p in query.split('&') if '=' in p)
            name = urllib.parse.unquote(params.get('output', ''))
            ok = do_switch(name)
            json_response(conn, {'ok': ok, 'current': current_output}, ok=ok)
        elif '/stream' in path:
            stream_client(conn)
        else:
            index_client(conn)
    except Exception:
        conn.close()


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def shutdown(sig, frame):
    global running
    running = False
    print('\nStopping...')
    p = current_proc
    if p is not None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

if current_output is None:
    _mons = list_monitors()
    if _mons:
        current_output = _mons[0]

threading.Thread(target=capture_loop, daemon=True).start()

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('0.0.0.0', PORT))
srv.listen(20)

ip = get_local_ip()
print(f'Stream ready → http://{ip}:{PORT}')
print(f'Password:      {PASSWORD}')
print(f'Ctrl+C to stop\n')

while True:
    conn, _ = srv.accept()
    threading.Thread(target=dispatch, args=(conn,), daemon=True).start()
