import time
import unittest

from support import (http_get, jpeg_ok, md5, percentile, read_argv, read_writes,
                     recv_frames, start_server, stop_server)


class StreamBehavior(unittest.TestCase):
    def test_requires_auth(self):
        srv = start_server()
        self.addCleanup(stop_server, srv)

        status, headers, _ = http_get(srv.port, '/')
        self.assertEqual(status, 401)
        self.assertIn('WWW-Authenticate', headers)

        status, _, _ = http_get(srv.port, '/', password='wrong')
        self.assertEqual(status, 401)

        status, _, body = http_get(srv.port, '/', password=srv.password)
        self.assertEqual(status, 200)
        self.assertIn(b'<img id="s" src="/stream">', body)

    def test_stream_delivers_complete_frames(self):
        srv = start_server(fps=20, frame_size=100000)
        self.addCleanup(stop_server, srv)

        frames = recv_frames(srv.port, srv.password, duration=2.0)
        written = {m for _, m, _ in read_writes(srv.write_log)}

        self.assertGreaterEqual(len(frames), 15, 'expected ~40 frames in 2s at 20fps')
        self.assertGreater(len({md5(f) for _, f in frames}), 5, 'frames should keep changing')
        for _, data in frames:
            self.assertTrue(jpeg_ok(data), 'frame must be a complete JPEG (SOI..EOI)')
            self.assertGreaterEqual(len(data), 100000)
            self.assertIn(md5(data), written, 'received frame was never produced by the capture')

    def test_frames_reach_the_client_as_soon_as_they_are_written(self):
        srv = start_server(fps=20, frame_size=100000)
        self.addCleanup(stop_server, srv)

        frames = recv_frames(srv.port, srv.password, duration=2.5)
        writes = {m: t for t, m, _ in read_writes(srv.write_log)}
        lat = [(t - writes[md5(data)]) * 1000.0 for t, data in frames if md5(data) in writes]

        self.assertGreaterEqual(len(lat), 15)
        p50 = percentile(lat, 50)
        self.assertLess(p50, 25.0,
                        'median write->receive latency %.1fms: frames are waiting for the next one'
                        % p50)

    def test_frame_split_across_reads_is_not_lost(self):
        srv = start_server(fps=20, frame_size=20000, split=True)
        self.addCleanup(stop_server, srv)

        frames = recv_frames(srv.port, srv.password, duration=2.5)
        written = {m for _, m, _ in read_writes(srv.write_log)}

        self.assertGreaterEqual(len(frames), 10,
                                'every frame starts with a lone 0xFF: the parser drops them')
        for _, data in frames:
            self.assertTrue(jpeg_ok(data))
            self.assertIn(md5(data), written)

    def test_monitor_list_is_cached(self):
        srv = start_server()
        self.addCleanup(stop_server, srv)

        status, _, body = http_get(srv.port, '/monitors', password=srv.password)
        self.assertEqual(status, 200)
        self.assertIn(b'"SYNTH-A"', body)
        self.assertIn(b'"SYNTH-B"', body)

        http_get(srv.port, '/monitors', password=srv.password)
        time.sleep(0.2)
        list_calls = [a for a in read_argv(srv.argv_log) if '-L' in a]
        self.assertEqual(len(list_calls), 1, 'second /monitors should be served from cache')

    def test_switch_output(self):
        srv = start_server(output='SYNTH-A')
        self.addCleanup(stop_server, srv)

        status, _, body = http_get(srv.port, '/switch?output=SYNTH-B', password=srv.password)
        self.assertEqual(status, 200)
        self.assertIn(b'"current":"SYNTH-B"', body.replace(b' ', b''))

        recaptured = False
        for _ in range(60):
            if any(a[a.index('-o') + 1] == 'SYNTH-B' for a in read_argv(srv.argv_log) if '-o' in a):
                recaptured = True
                break
            time.sleep(0.1)
        self.assertTrue(recaptured, 'switching must relaunch the capture on the new output')

        status, _, body = http_get(srv.port, '/switch?output=NOPE', password=srv.password)
        self.assertEqual(status, 400)
        self.assertIn(b'"ok": false', body)

    def test_capture_command_and_prompt_answer(self):
        cases = [('', 'yuvj420p'), ('422', 'yuvj422p'), ('444', 'yuvj444p')]
        for chroma, pixfmt in cases:
            with self.subTest(chroma=chroma or 'default'):
                extra = ['--quality', '2', '--fps', '15', '--scale', '720']
                if chroma:
                    extra += ['--chroma', chroma]
                srv = start_server(extra=extra)
                self.addCleanup(stop_server, srv)

                spawn = None
                for _ in range(50):
                    spawns = [a for a in read_argv(srv.argv_log) if '-c' in a]
                    if spawns:
                        spawn = spawns[0]
                        break
                    time.sleep(0.1)
                self.assertIsNotNone(spawn, 'wf-recorder was never launched')

                expected_pairs = [('-c', 'mjpeg'), ('-m', 'mpjpeg'), ('-r', '15'),
                                  ('-x', pixfmt), ('-p', 'qmin=2'), ('-p', 'qmax=2'),
                                  ('-F', 'scale=-2:720'), ('-o', 'SYNTH-A'),
                                  ('-f', '/dev/stdout')]
                self.assertIn('-D', spawn, 'wf-recorder must run with -D (no-damage)')
                adjacent = list(zip(spawn, spawn[1:]))
                for pair in expected_pairs:
                    self.assertIn(pair, adjacent,
                                  '%s not bound in capture command %s' % (pair, spawn))
                with open(srv.stdin_log, 'rb') as f:
                    self.assertIn(b'y', f.read(), "wf-recorder's overwrite prompt must be answered")


if __name__ == '__main__':
    unittest.main()
