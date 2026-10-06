import os
import re
import signal
import subprocess
import threading

PIXFMT = {'420': 'yuvj420p', '422': 'yuvj422p', '444': 'yuvj444p'}


def jpeg_frames(stream):
    buf = b''
    while True:
        chunk = stream.read1(65536)
        if not chunk:
            return
        buf += chunk
        while True:
            start = buf.find(b'\xff\xd8')
            if start == -1:
                buf = buf[-1:] if buf.endswith(b'\xff') else b''
                break
            end = buf.find(b'\xff\xd9', start + 2)
            if end == -1:
                buf = buf[start:]
                break
            yield buf[start:end + 2]
            buf = buf[end + 2:]


class CaptureBackend:
    name = ''
    kind = ''

    def __init__(self, fps, quality, chroma, scale, env=None):
        self.fps = fps
        self.quality = quality
        self.chroma = chroma
        self.scale = scale
        self.env = env if env is not None else os.environ.copy()
        self._proc = None
        self._lock = threading.Lock()

    def list_outputs(self):
        raise NotImplementedError

    def start(self, output):
        raise NotImplementedError

    def frames(self):
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        try:
            yield from jpeg_frames(proc.stdout)
        finally:
            self.stop()

    def spawn(self, argv):
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=self.env, start_new_session=True)
        with self._lock:
            self._proc = proc
        return proc

    def stop(self):
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        proc.wait()


class WlrBackend(CaptureBackend):
    name = 'wlr'
    kind = 'wlr'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pixfmt = PIXFMT[self.chroma]

    def argv(self, output):
        cmd = ['wf-recorder', '-c', 'mjpeg', '-m', 'mpjpeg', '-r', str(self.fps), '-D',
               '-x', self.pixfmt, '-p', f'qmin={self.quality}', '-p', f'qmax={self.quality}']
        if self.scale:
            cmd += ['-F', f'scale=-2:{self.scale}']
        if output:
            cmd += ['-o', output]
        return cmd + ['-f', '/dev/stdout']

    def list_outputs(self):
        try:
            out = subprocess.run(['wf-recorder', '-L'], capture_output=True, text=True,
                                 env=self.env, timeout=5).stdout
            return re.findall(r'Name:\s*(\S+)', out)
        except Exception:
            return None

    def start(self, output):
        proc = self.spawn(self.argv(output))
        try:
            proc.stdin.write(b'y\n')
            proc.stdin.close()
        except OSError:
            pass


class X11Backend(CaptureBackend):
    name = 'x11'
    kind = 'x11'

    def argv(self, output):
        display = self.env.get('DISPLAY', ':0')
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab',
               '-framerate', str(self.fps), '-i', f'{display}+0,0',
               '-pix_fmt', PIXFMT[self.chroma]]
        if self.scale:
            cmd += ['-vf', f'scale=-2:{self.scale}']
        return cmd + ['-c:v', 'mjpeg', '-q:v', str(self.quality),
                      '-f', 'image2pipe', '-vcodec', 'mjpeg', '-']

    def list_outputs(self):
        display = self.env.get('DISPLAY')
        return [display] if display else []

    def start(self, output):
        proc = self.spawn(self.argv(output))
        try:
            proc.stdin.close()
        except OSError:
            pass


BACKENDS = {'wlr': WlrBackend, 'x11': X11Backend}


def detect(env):
    if env.get('WAYLAND_DISPLAY') or env.get('XDG_SESSION_TYPE') == 'wayland':
        return 'wlr'
    if env.get('DISPLAY'):
        return 'x11'
    return 'wlr'


def create_backend(kind='auto', **kwargs):
    env = kwargs.get('env') or os.environ.copy()
    kwargs['env'] = env
    if kind in (None, '', 'auto'):
        kind = detect(env)
    if kind not in BACKENDS:
        raise ValueError('unknown backend: %s (choose from %s)' % (kind, ', '.join(sorted(BACKENDS))))
    return BACKENDS[kind](**kwargs)
