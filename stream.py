#!/usr/bin/env python3
import socket, threading, os, signal, sys, time, argparse, base64, secrets, json, urllib.parse

import backends

parser = argparse.ArgumentParser(description='Stream a Wayland desktop to the Meta Quest browser')
parser.add_argument('--fps',      type=int, default=20,   help='Frames per second (default: 20)')
parser.add_argument('--quality',  type=int, default=4,    help='MJPEG quality 1=best 31=worst (default: 4)')
parser.add_argument('--port',     type=int, default=8080, help='HTTP port (default: 8080)')
parser.add_argument('--output',   type=str, default=None, help='Monitor to capture, e.g. eDP-1, HDMI-A-1')
parser.add_argument('--password', type=str, default=None, help='Access password (one is generated if omitted)')
parser.add_argument('--sharp',    action='store_true', help='Sharper text (4:4:4) at the cost of ~1.4x data and more latency')
parser.add_argument('--chroma',   type=str, choices=('420', '422', '444'), default=None,
                    help='Chroma subsampling: 420 = default, 422 = sharper color for ~1.1x data, 444 = full (= --sharp)')
parser.add_argument('--scale',    type=int, default=None, help='Downscale to this height in px (e.g. 720). Less data = less latency')
parser.add_argument('--backend',  type=str, choices=('auto', 'wlr', 'x11'), default='auto',
                    help='Capture backend: auto = detect (default), wlr = wf-recorder, x11 = ffmpeg x11grab')
args = parser.parse_args()

FPS      = args.fps
QUALITY  = args.quality
PORT     = args.port
PASSWORD = args.password or secrets.token_urlsafe(8)
CHROMA   = args.chroma or ('444' if args.sharp else '420')
BACKEND  = backends.create_backend(args.backend, fps=FPS, quality=QUALITY,
                                   chroma=CHROMA, scale=args.scale)

latest_frame   = None
frame_seq      = 0
frame_cond     = threading.Condition()
running        = True
current_output = args.output
restart_event  = threading.Event()
mon_lock       = threading.Lock()
mon_cache      = {'names': None, 'at': 0.0}


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


def publish(frame):
    global latest_frame, frame_seq
    with frame_cond:
        latest_frame = frame
        frame_seq += 1
        frame_cond.notify_all()


def await_frame(after_seq, timeout=1.0):
    with frame_cond:
        if frame_seq == after_seq:
            frame_cond.wait(timeout)
        return frame_seq, latest_frame


def capture_loop():
    print(f'Capturing @ {FPS}fps  quality={QUALITY}  chroma={CHROMA}  backend={BACKEND.name}'
          + (f'  output={current_output}' if current_output else ''))

    while running:
        BACKEND.start(current_output)
        try:
            for frame in BACKEND.frames():
                publish(frame)
                if not running or restart_event.is_set():
                    break
        finally:
            BACKEND.stop()
        if restart_event.is_set():
            restart_event.clear()
            print(f'Switching to output={current_output}')
            continue
        if running:
            print('Capture interrupted, restarting in 1s...')
            time.sleep(1)


def list_monitors(refresh=False):
    with mon_lock:
        if not refresh and mon_cache['names'] is not None and time.monotonic() - mon_cache['at'] < 5.0:
            return mon_cache['names']
        names = BACKEND.list_outputs()
        if names:
            mon_cache['names'] = names
            mon_cache['at'] = time.monotonic()
        return mon_cache['names'] or []


def do_switch(name):
    global current_output
    if name not in list_monitors() and name not in list_monitors(refresh=True):
        return False
    current_output = name
    restart_event.set()
    BACKEND.stop()
    return True


def tune_send_buffer(conn, frame_size):
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF,
                        max(32 * 1024, min(frame_size, 128 * 1024)))
    except OSError:
        pass


def stream_client(conn):
    try:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        conn.sendall(
            b'HTTP/1.1 200 OK\r\n'
            b'Content-Type: multipart/x-mixed-replace; boundary=frame\r\n'
            b'Cache-Control: no-cache\r\n'
            b'Connection: close\r\n\r\n'
        )
        sent_seq = 0
        tuned = False
        while True:
            seq, frame = await_frame(sent_seq)
            if frame is None or seq == sent_seq:
                continue
            if not tuned:
                tune_send_buffer(conn, len(frame))
                tuned = True
            hdr = (
                f'--frame\r\nContent-Type: image/jpeg\r\n'
                f'Content-Length: {len(frame)}\r\n\r\n'
            ).encode()
            conn.sendall(hdr + frame + b'\r\n')
            sent_seq = seq
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
    '#wrap{position:relative;display:flex}'
    '#toggle{'
      'position:absolute;top:20px;left:20px;'
      'background:rgba(255,255,255,.15);border:none;border-radius:8px;'
      'width:48px;height:48px;cursor:pointer;'
      'display:flex;align-items:center;justify-content:center;'
      'opacity:.08;transition:opacity .2s ease'
    '}'
    '#toggle:hover{opacity:1;background:rgba(255,255,255,.3)}'
    '#wrap.hidden #bar,#wrap.hidden #fs{opacity:0;pointer-events:none}'
    '#wrap.hidden #toggle{opacity:.2}'
    '#fs{'
      'position:absolute;top:20px;right:20px;'
      'background:rgba(255,255,255,.15);border:none;border-radius:8px;'
      'width:48px;height:48px;cursor:pointer;'
      'display:flex;align-items:center;justify-content:center;'
      'opacity:.08;transition:opacity .2s ease'
    '}'
    '#fs:hover{opacity:1;background:rgba(255,255,255,.3)}'
    '#bar{position:absolute;top:16px;left:50%;transform:translateX(-50%);display:flex;gap:8px;z-index:10;opacity:.08;transition:opacity .2s ease}'
    '#bar:hover{opacity:1}'
    '#bar button{'
      'background:rgba(255,255,255,.15);color:#fff;border:none;border-radius:8px;'
      'padding:8px 14px;font-size:14px;cursor:pointer;font-family:sans-serif'
    '}'
    '#bar button:hover{background:rgba(255,255,255,.3)}'
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
    '<div id="msg"><div class="spin"></div><div class="t" id="msgt">Waiting for video…</div></div>'
    '<div id="wrap">'
    '<img id="s" src="/stream">'
    '<div id="bar"></div>'
    '<button id="toggle" title="Toggle controls">'
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="white">'
        '<path fill-rule="evenodd" d="M1 10C1 10 5 4 10 4s9 6 9 6-4 6-9 6-9-6-9-6zm9-3a3 3 0 100 6 3 3 0 000-6z"/>'
      '</svg>'
    '</button>'
    '<button id="fs" title="Fullscreen">'
      '<svg class="enter" width="20" height="20" viewBox="0 0 20 20" fill="white">'
        '<path d="M1 1h6v2H3v4H1V1zm12 0h6v6h-2V3h-4V1zM1 13h2v4h4v2H1v-6zm14 4h-4v2h6v-6h-2v4z"/>'
      '</svg>'
      '<svg class="exit" width="20" height="20" viewBox="0 0 20 20" fill="white" style="display:none">'
        '<path d="M13 1h6v6h-2V3h-4V1zM1 7V1h6v2H3v4H1zM13 19v-2h4v-4h2v6h-6zM1 13h2v4h4v2H1v-6z"/>'
      '</svg>'
    '</button>'
    '</div>'
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
    'var fsEnter=fsBtn.querySelector(".enter");'
    'var fsExit=fsBtn.querySelector(".exit");'
    'fsBtn.onclick=function(){'
      'document.fullscreenElement'
        '?document.exitFullscreen&&document.exitFullscreen()'
        ':document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen()'
    '};'
    'document.addEventListener("fullscreenchange",function(){'
      'var f=!!document.fullscreenElement;'
      'fsEnter.style.display=f?"none":"";'
      'fsExit.style.display=f?"":"none"'
    '});'
    'document.getElementById("toggle").onclick=function(){'
      'document.getElementById("wrap").classList.toggle("hidden")'
    '};'
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
    BACKEND.stop()
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
