import json
import unittest

from support import http_get, jpeg_ok, read_argv, recv_frames, start_server, stop_server

import backends


class SplitStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read1(self, _size):
        return self.chunks.pop(0) if self.chunks else b''


class BackendSelection(unittest.TestCase):
    def test_auto_detects_wlr_on_wayland(self):
        backend = backends.create_backend('auto', fps=20, quality=4, chroma='420',
                                          scale=None, env={'WAYLAND_DISPLAY': 'wayland-1'})
        self.assertEqual(backend.name, 'wlr')

    def test_auto_detects_x11_without_wayland(self):
        backend = backends.create_backend('auto', fps=20, quality=4, chroma='420',
                                          scale=None, env={'DISPLAY': ':0'})
        self.assertEqual(backend.name, 'x11')

    def test_auto_falls_back_to_wlr(self):
        backend = backends.create_backend('auto', fps=20, quality=4, chroma='420',
                                          scale=None, env={})
        self.assertEqual(backend.name, 'wlr')

    def test_explicit_backend_wins_over_detection(self):
        backend = backends.create_backend('x11', fps=20, quality=4, chroma='420',
                                          scale=None, env={'WAYLAND_DISPLAY': 'wayland-1'})
        self.assertEqual(backend.name, 'x11')

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            backends.create_backend('portal', fps=20, quality=4, chroma='420',
                                    scale=None, env={})


class WlrAdapter(unittest.TestCase):
    def make(self, chroma='420', scale=None):
        return backends.WlrBackend(fps=15, quality=4, chroma=chroma, scale=scale, env={})

    def test_argv_is_the_expected_wf_recorder_command(self):
        self.assertEqual(
            self.make().argv('DP-1'),
            ['wf-recorder', '-c', 'mjpeg', '-m', 'mpjpeg', '-r', '15', '-D',
             '-x', 'yuvj420p', '-p', 'qmin=4', '-p', 'qmax=4', '-o', 'DP-1',
             '-f', '/dev/stdout'])

    def test_argv_omits_optional_flags_when_unused(self):
        argv = self.make(chroma='444').argv(None)
        self.assertNotIn('-o', argv)
        self.assertNotIn('-F', argv)
        self.assertEqual(argv[argv.index('-x') + 1], 'yuvj444p')

    def test_chroma_maps_to_pixel_format(self):
        for chroma, pixfmt in backends.PIXFMT.items():
            argv = self.make(chroma=chroma).argv('X')
            self.assertEqual(argv[argv.index('-x') + 1], pixfmt)

    def test_scale_becomes_a_filter(self):
        argv = self.make(scale=720).argv(None)
        self.assertEqual(argv[argv.index('-F') + 1], 'scale=-2:720')


class X11Adapter(unittest.TestCase):
    def make(self, chroma='420', scale=None, display=':0'):
        return backends.X11Backend(fps=25, quality=4, chroma=chroma, scale=scale,
                                   env={'DISPLAY': display})

    def test_argv_grabs_the_x11_display(self):
        argv = self.make().argv(None)
        self.assertEqual(argv[0], 'ffmpeg')
        self.assertIn('x11grab', argv)
        self.assertEqual(argv[argv.index('-i') + 1], ':0+0,0')

    def test_argv_maps_quality_chroma_and_scale(self):
        argv = self.make(chroma='444', scale=720).argv(None)
        self.assertEqual(argv[argv.index('-pix_fmt') + 1], 'yuvj444p')
        self.assertEqual(argv[argv.index('-q:v') + 1], '4')
        self.assertEqual(argv[argv.index('-vf') + 1], 'scale=-2:720')
        self.assertIn('image2pipe', argv)

    def test_list_outputs_is_the_display(self):
        self.assertEqual(self.make(display=':1').list_outputs(), [':1'])
        bare = backends.X11Backend(fps=1, quality=1, chroma='420', scale=None, env={})
        self.assertEqual(bare.list_outputs(), [])


class JpegParser(unittest.TestCase):
    def test_recovers_from_a_split_marker(self):
        frame1 = b'\xff\xd8' + b'A' * 100 + b'\xff\xd9'
        frame2 = b'\xff\xd8' + b'B' * 50 + b'\xff\xd9'
        stream = SplitStream([b'\xff',
                              b'\xd8' + b'A' * 100 + b'\xff\xd9' + b'\xff\xd8' + b'B' * 40,
                              b'B' * 10 + b'\xff\xd9'])
        self.assertEqual(list(backends.jpeg_frames(stream)), [frame1, frame2])

    def test_trailing_lone_ff_is_kept_for_the_next_chunk(self):
        stream = SplitStream([b'\xff\xd8' + b'C' * 20 + b'\xff\xd9' + b'\xff',
                              b'\xd8' + b'D' * 20 + b'\xff\xd9'])
        self.assertEqual(len(list(backends.jpeg_frames(stream))), 2)

    def test_partial_tail_is_dropped_at_eof(self):
        stream = SplitStream([b'\xff\xd8' + b'E' * 10 + b'\xff\xd9' + b'\xff\xd8' + b'partial'])
        self.assertEqual(len(list(backends.jpeg_frames(stream))), 1)


class X11EndToEnd(unittest.TestCase):
    def test_server_streams_frames_through_ffmpeg(self):
        srv = start_server(extra=('--backend', 'x11'), output=None, fps=15,
                           env_extra={'DISPLAY': ':0', 'WAYLAND_DISPLAY': None})
        self.addCleanup(stop_server, srv)

        frames = recv_frames(srv.port, srv.password, duration=1.5, max_frames=3)
        self.assertGreaterEqual(len(frames), 3, 'x11 backend produced no frames')
        for _, data in frames:
            self.assertTrue(jpeg_ok(data))

        argv = read_argv(srv.argv_log)
        self.assertTrue(argv, 'ffmpeg was never spawned')
        for entry in argv:
            self.assertEqual(entry[0], '-loglevel', 'unexpected capturer spawned')

        status, _, body = http_get(srv.port, '/monitors', password=srv.password)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'monitors': [':0'], 'current': ':0'})


if __name__ == '__main__':
    unittest.main()
