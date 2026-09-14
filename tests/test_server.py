import io
import json
import threading
import unittest
import urllib.error
import urllib.request

import numpy as np

from eels_sim.model import TERMS, coefficients
from eels_sim.server import Application, LocalServer
from eels_sim.training import GENERATOR_VERSION


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

    def test_high_order_question_lifecycle_and_lossless_labels(self):
        request = dict(self.request, max_order=5, term_count=20)
        first = self.app.dispatch('/api/frame', dict(request, action='new'))
        self.assertEqual(first['question']['max_order'], 5)
        self.assertEqual(first['question']['generator_version'], GENERATOR_VERSION)
        self.assertNotIn('feedback', first)
        self.assertEqual(len(first['controls']), 20)
        revealed = self.app.dispatch('/api/frame', dict(request, action='reveal'))
        feedback = revealed['feedback']
        self.assertTrue(all(15.75 <= abs(v) <= 45 for v in feedback['initial'].values()))
        self.assertEqual(feedback['generator_version'], GENERATOR_VERSION)
        with np.load(io.BytesIO(self.app.dispatch('/api/export', {'session': self.token})), allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata_json']))
            self.assertEqual(metadata['effective_coefficients'], feedback['initial'])
            self.assertEqual(metadata['labels']['max_order'], 5)
            self.assertEqual(metadata['labels']['generator_version'], GENERATOR_VERSION)
            np.testing.assert_array_equal(data['spectrum'], data['counts'].sum(axis=0))
        # Pending selectors do not replace a question on update/reveal/retry.
        staged = dict(request, max_order=1, term_count=2)
        solved = self.app.dispatch('/api/frame', dict(staged, controls=feedback['answer']))
        self.assertEqual(solved['question']['max_order'], 5)
        self.assertEqual(solved['feedback']['normalized_rms'], 0)
        self.assertAlmostEqual(solved['metrics']['fwhm_mev'], 8, delta=0.2)
        with np.load(io.BytesIO(self.app.dispatch('/api/export', {'session': self.token})), allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata_json']))
            self.assertEqual(metadata['labels']['max_order'], 5)
            self.assertEqual(metadata['labels']['initial'], feedback['initial'])
            self.assertEqual(metadata['terms'], list(TERMS))
            self.assertEqual(metadata['effective_coefficients'], coefficients())
        retried = self.app.dispatch('/api/frame', dict(staged, action='retry'))
        self.assertEqual(retried['question'], first['question'])
        self.assertEqual(retried['image_png'], first['image_png'])
        self.assertNotIn('feedback', retried)
        lower = self.app.dispatch('/api/frame', dict(staged, action='new'))
        self.assertEqual(lower['question']['max_order'], 1)
        self.assertEqual(lower['controls'], coefficients())
        with self.assertRaises(ValueError):
            self.app.dispatch('/api/frame', dict(staged, action='reveal', controls={'D05': 1}))
        unchanged = self.app.dispatch('/api/frame', staged)
        self.assertNotIn('feedback', unchanged)
        self.assertEqual(unchanged['question'], lower['question'])
        self.assertEqual(unchanged['image_png'], lower['image_png'])
        free = self.app.dispatch('/api/frame', dict(staged, mode='free', controls={'D22': 8, 'D05': -9}))
        self.assertEqual(free['controls']['D22'], 8)
        self.assertEqual(free['controls']['D05'], -9)
        self.assertNotIn('question', free)

    def test_clipped_practice_can_widen_field_without_changing_answer(self):
        request = dict(self.request, max_order=5, term_count=20, difficulty='hard',
                       config={'n_rays': 4096, 'energy_half_range_mev': 40})
        first = self.app.dispatch('/api/frame', dict(request, action='new'))
        self.assertNotIn('feedback', first)
        self.assertGreater(first['clipped_fraction'], 0.001)
        self.assertIsNone(first['metrics']['fwhm_mev'])
        self.assertTrue(any('视野截断' in w for w in first['metrics']['warnings']))
        narrow = self.app.dispatch('/api/frame', dict(request, action='reveal'))
        wide_request = dict(request, config={'n_rays': 4096, 'energy_half_range_mev': 240})
        wide = self.app.dispatch('/api/frame', wide_request)
        self.assertEqual(wide['question'], first['question'])
        self.assertEqual(wide['feedback'], narrow['feedback'])
        self.assertLess(wide['clipped_fraction'], 0.001)
        self.assertIsNotNone(wide['metrics']['fwhm_mev'])
        # Even re-creating the same seed in a different field preserves labels.
        self.app.dispatch('/api/frame', dict(wide_request, action='new'))
        recreated = self.app.dispatch('/api/frame', dict(wide_request, action='reveal'))
        self.assertEqual(recreated['feedback']['initial'], narrow['feedback']['initial'])

    def test_bad_order_does_not_mutate_question(self):
        first = self.app.dispatch('/api/frame', dict(self.request, action='new'))
        for invalid in (0, 6, True, 5.0, '5', None):
            with self.assertRaises(ValueError):
                self.app.dispatch('/api/frame', dict(self.request, action='new', max_order=invalid))
        with self.assertRaises(ValueError):
            self.app.dispatch('/api/frame', dict(self.request, action='new', max_order=4, term_count=20))
        unchanged = self.app.dispatch('/api/frame', self.request)
        self.assertEqual(unchanged['question'], first['question'])
        self.assertEqual(unchanged['image_png'], first['image_png'])
        self.assertNotIn('feedback', unchanged)

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
        for path in ('/', '/app.js', '/desktop.js', '/style.css'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
                self.assertGreater(len(response.read()), 100)
        with self.request('/api/meta') as response:
            meta = json.load(response)
            self.assertEqual(meta['defaults']['base_fwhm_mev'], 8)
            self.assertEqual(meta['terms'], list(TERMS))
            self.assertEqual(meta['powers'][-1], [0, 5])
            self.assertEqual(meta['max_order'], 5)
            self.assertEqual(meta['default_practice_order'], 3)
            self.assertEqual(meta['generator_version'], GENERATOR_VERSION)
        with self.request('/api/session', {}) as response:
            token = json.load(response)['session']
        with self.request('/api/frame', {'session': token}) as response:
            self.assertAlmostEqual(json.load(response)['metrics']['fwhm_mev'], 8, delta=0.2)
        with self.request('/api/frame', {'session': token, 'mode': 'practice', 'action': 'new', 'max_order': 4, 'term_count': 14}) as response:
            question = json.load(response)
            self.assertEqual(question['question']['max_order'], 4)
            self.assertEqual(question['question']['term_count'], 14)
            self.assertNotIn('feedback', question)
        with self.request('/api/frame', {'session': token, 'mode': 'practice', 'action': 'reveal'}) as response:
            self.assertNotEqual(json.load(response)['feedback']['initial']['D04'], 0)
        with self.request('/api/export', {'session': token}) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
            with np.load(io.BytesIO(response.read()), allow_pickle=False) as data:
                self.assertIn('counts', data)

    def test_local_only_and_no_arbitrary_files(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for path, data, headers, status in (
            ('/raw/20260912/xiangcha.py', None, {}, 404),
            ('/../AGENTS.md', None, {}, 404),
            ('/api/desktop/events?token=wrong', None, {}, 404),
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
