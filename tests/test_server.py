import io
import json
import threading
import unittest
import urllib.error
import urllib.request

import numpy as np

from eels_sim.model import coefficients
from eels_sim.server import Application, LocalServer


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.token = self.app.create_session()['session']
        self.request = dict(session=self.token, mode='practice', seed=42, term_count=9,
                            difficulty='medium', config={'n_rays': 4096})

    def test_hidden_reveal_compensate_retry_and_export(self):
        first = self.app.dispatch('/api/frame', dict(self.request, action='new'))
        self.assertNotIn('feedback', first)
        self.assertNotIn('effective_coefficients', first)
        self.assertNotIn('initial', first)
        self.assertEqual(first['controls'], coefficients())
        revealed = self.app.dispatch('/api/frame', dict(self.request, action='reveal'))
        feedback = revealed['feedback']
        self.assertEqual(first['image_png'], revealed['image_png'])
        solved = self.app.dispatch('/api/frame', dict(self.request, controls=feedback['answer']))
        self.assertEqual(solved['feedback']['normalized_rms'], 0)
        self.assertAlmostEqual(solved['metrics']['fwhm_mev'], 8, delta=0.2)
        with np.load(io.BytesIO(self.app.dispatch('/api/export', {'session': self.token})), allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata_json']))
            self.assertEqual(metadata['labels']['initial'], feedback['initial'])
            self.assertEqual(metadata['effective_coefficients'], coefficients())
        retry = self.app.dispatch('/api/frame', dict(self.request, action='retry'))
        self.assertNotIn('feedback', retry)
        self.assertEqual(retry['image_png'], first['image_png'])

    def test_sessions_are_isolated_and_free_mode_is_direct(self):
        other = self.app.create_session()['session']
        a = self.app.dispatch('/api/frame', dict(self.request, action='reveal'))
        b = self.app.dispatch('/api/frame', dict(self.request, session=other, seed=99, action='new'))
        self.assertNotIn('feedback', b)
        self.assertNotEqual(a['image_png'], b['image_png'])
        free = self.app.dispatch('/api/frame', dict(self.request, mode='free', controls={'D01': 20}))
        self.assertNotIn('feedback', free)
        self.assertEqual(free['controls']['D01'], 20)
        self.assertEqual(free['mode'], 'free')

    def test_invalid_requests(self):
        for data in ({}, {'session': 'bad'}, dict(self.request, controls={'D10': 999}),
                     dict(self.request, config={'energy_bins': 999999}), dict(self.request, gamma=0),
                     dict(self.request, mode='hardware'), dict(self.request, unknown=1)):
            with self.assertRaises(ValueError): self.app.dispatch('/api/frame', data)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, data=None, headers=None):
        hdr = {} if headers is None else dict(headers)
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            hdr.setdefault('Content-Type', 'application/json')
        request = urllib.request.Request(self.url+path, data=body, headers=hdr)
        # Loopback tests must not inherit environment HTTP proxy routing.
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30)

    def test_static_meta_and_http_frame(self):
        for path in ('/', '/app.js', '/style.css'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
                self.assertGreater(len(response.read()), 100)
        with self.request('/api/meta') as response:
            self.assertEqual(json.load(response)['defaults']['base_fwhm_mev'], 8)
        with self.request('/api/session', {}) as response:
            token = json.load(response)['session']
        with self.request('/api/frame', {'session': token}) as response:
            self.assertAlmostEqual(json.load(response)['metrics']['fwhm_mev'], 8, delta=0.2)
        with self.request('/api/export', {'session': token}) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
            with np.load(io.BytesIO(response.read()), allow_pickle=False) as data:
                self.assertIn('counts', data)

    def test_local_only_and_no_arbitrary_files(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for path, data, headers, status in (
            ('/raw/20260912/xiangcha.py', None, {}, 404),
            ('/../AGENTS.md', None, {}, 404),
            ('/api/session', {}, {'Origin': 'https://example.invalid'}, 403),
            ('/api/session', {}, {'Content-Type': 'text/plain'}, 415),
            ('/api/meta', None, {'Host': 'attacker.invalid'}, 403),
            ('/api/frame', {'session': 'missing'}, {}, 400),
        ):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, data, headers)
            try:
                self.assertEqual(error.exception.code, status)
            finally:
                error.exception.close()


if __name__ == '__main__':
    unittest.main()
