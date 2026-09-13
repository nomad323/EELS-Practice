import ast
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from eels_sim import Config, MODEL_VERSION, POWERS, TERMS, coefficients, polynomial, simulate, terms_through
from eels_sim import legacy
from eels_sim.model import FWHM_FACTOR, measure_spectrum
from eels_sim.presentation import export_npz, grayscale, png_bytes
from eels_sim.training import checked_controls, new_exercise


class PolynomialTests(unittest.TestCase):
    def test_nine_terms_and_superposition(self):
        u = np.array([-0.7, 0, 0.4, 1.0])
        v = np.array([0.1, 0.8, -0.3, 0.2])
        expected = [u, v, u*u, u*v, v*v, u*u*u, u*u*v, u*v*v, v*v*v]
        for name, values in zip(TERMS, expected):
            np.testing.assert_allclose(polynomial(u, v, {name: 2.5}), 2.5*values)
        np.testing.assert_allclose(polynomial(u, v, dict.fromkeys(TERMS[:9], 2.5)), 2.5*np.sum(expected, axis=0))

    def test_fourth_fifth_order_basis_and_cross_page_superposition(self):
        self.assertEqual(TERMS[9:], ('D40', 'D31', 'D22', 'D13', 'D04', 'D50', 'D41', 'D32', 'D23', 'D14', 'D05'))
        u, v = np.array([-0.7, 0, 0.4, 1.2]), np.array([0.1, 0.8, -0.3, -0.5])
        expected = [u**4, u**3*v, u**2*v**2, u*v**3, v**4,
                    u**5, u**4*v, u**3*v**2, u**2*v**3, u*v**4, v**5]
        for name, basis in zip(TERMS[9:], expected):
            np.testing.assert_allclose(polynomial(u, v, {name: -2.5}), -2.5*basis)
        np.testing.assert_allclose(polynomial(u, v, {'D01': 3, 'D22': -7, 'D05': 9}), 3*v-7*u**2*v**2+9*v**5)
        np.testing.assert_allclose(polynomial(u, v, dict.fromkeys(TERMS[9:], 2)), 2*np.sum(expected, axis=0))
        for order, count in enumerate((2, 5, 9, 14, 20), 1):
            self.assertEqual(terms_through(order), TERMS[:count])
        for value in (0, 6, True, 3.0, '5', None):
            with self.assertRaises(ValueError): terms_through(value)
        with self.assertRaises(ValueError): coefficients({'D60': 1})
        with self.assertRaises(ValueError): checked_controls({'D05': 120.01})

    def test_aliases_and_validation(self):
        self.assertEqual(coefficients({'x': 1, 'xy': 2, 'x y^2': 3})['D12'], 3)
        for value in ({'x2': 1}, {'D10': float('nan')}, {'D10': True}, {'D10': '2'}, {'x': 1, 'D10': 1}, []):
            with self.assertRaises(ValueError): coefficients(value)
        with self.assertRaises(ValueError): checked_controls({'D10': 121})
        for values in ({'bogus': 1}, {'poisson': 1}, {'energy_bins': 800}, {'n_rays': 1}, {'pupil_x': float('inf')}, {'sample_seed': -1}, {'expected_counts': True}):
            with self.assertRaises(ValueError): Config.from_dict(values)


class ModelTests(unittest.TestCase):
    def test_default_8_mev_and_count_conservation(self):
        r = simulate()
        self.assertAlmostEqual(r.metrics['fwhm_mev'], 8, delta=0.2)
        self.assertAlmostEqual(r.metrics['rms_mev'], 8/FWHM_FACTOR, delta=0.01)
        self.assertAlmostEqual(r.counts.sum(), 1_000_000, delta=1e-6)
        self.assertLess(r.clipped_fraction, 1e-10)
        np.testing.assert_array_equal(r.spectrum, r.counts.sum(axis=0))
        self.assertEqual(r.counts.shape, (181, 801))
        self.assertTrue(np.isfinite(r.counts).all())
        self.assertGreaterEqual(r.counts.min(), 0)

    def test_sampling_pixel_and_field_convergence(self):
        widths = []
        for config in (Config(n_rays=4096, energy_half_range_mev=40),
                       Config(n_rays=262144, energy_bins=1601),
                       Config(n_rays=16384, energy_half_range_mev=480),
                       Config(sample_seed=123)):
            width = simulate(config=config).metrics['fwhm_mev']
            self.assertAlmostEqual(width, 8, delta=0.2)
            widths.append(width)
        self.assertLess(max(widths)-min(widths), 0.2)

    def test_tilt_broadens_integrated_spectrum(self):
        r = simulate({'D01': 40})
        self.assertGreater(r.metrics['fwhm_mev'], 60)
        self.assertAlmostEqual(r.metrics['centroid_mev'], 0, delta=1e-8)

    def test_reproducibility(self):
        config = Config(poisson=True, n_rays=16384)
        a, b = simulate({'D11': 25}, config), simulate({'D11': 25}, config)
        np.testing.assert_array_equal(a.counts, b.counts)
        c = simulate({'D11': 25}, replace(config, noise_seed=18))
        np.testing.assert_array_equal(a.expected, c.expected)
        self.assertFalse(np.array_equal(a.counts, c.counts))

    def test_pupil_parity_degeneracy(self):
        a = {'D10': 12, 'D11': 8, 'D30': -20, 'D12': 3, 'D02': 7}
        b = {k: (-v if k in ('D10', 'D11', 'D30', 'D12') else v) for k, v in a.items()}
        np.testing.assert_allclose(simulate(a).counts, simulate(b).counts, atol=1e-9)

    def test_high_order_forward_conservation_and_parity(self):
        baseline = simulate().counts
        for name in TERMS[9:]:
            r = simulate({name: 20})
            self.assertFalse(np.array_equal(r.counts, baseline), name)
            self.assertAlmostEqual(r.counts.sum(), 1e6, delta=1e-6)
            self.assertLess(r.clipped_fraction, 1e-10)
            np.testing.assert_array_equal(r.spectrum, r.counts.sum(axis=0))
        a = {n: (-1)**i*(i+1) for i, n in enumerate(TERMS)}
        b = {n: (-a[n] if i % 2 else a[n]) for n, (i,j) in zip(TERMS, POWERS)}
        np.testing.assert_allclose(simulate(a).counts, simulate(b).counts, atol=1e-9)
        clipped = simulate({'D05': 500}, Config(energy_half_range_mev=40))
        self.assertGreater(clipped.clipped_fraction, 0.001)
        self.assertIsNone(clipped.metrics['fwhm_mev'])

    def test_extra_gaussian_in_quadrature(self):
        sigma = 4
        r = simulate(config=Config(extra_sigma_mev=sigma, y_psf_sigma=0.05))
        self.assertAlmostEqual(r.metrics['fwhm_mev'], np.hypot(8, FWHM_FACTOR*sigma), delta=0.2)

    def test_angular_slit_transmission_not_renormalized(self):
        r = simulate(config=Config(angular_slit_half=0.4))
        self.assertGreater(r.transmission, 0)
        self.assertLess(r.transmission, 1)
        self.assertAlmostEqual(r.counts.sum(), 1_000_000*r.transmission, delta=1e-6)
        self.assertAlmostEqual(r.metrics['fwhm_mev'], 8, delta=0.2)

    def test_clipping_is_reported(self):
        r = simulate({'D10': 500}, Config(energy_half_range_mev=40))
        self.assertGreater(r.clipped_fraction, 0.5)
        self.assertIsNone(r.metrics['fwhm_mev'])
        self.assertTrue(r.metrics['warnings'])

    def test_background_and_invalid_fwhm_cases(self):
        r = simulate(config=Config(background_per_pixel=3))
        self.assertAlmostEqual(r.metrics['fwhm_mev'], 8, delta=0.2)
        self.assertAlmostEqual(r.counts.sum(), 1e6+3*r.counts.size, delta=1e-6)
        x = np.linspace(-10, 10, 201)
        for signal in (np.zeros_like(x), np.ones_like(x), np.exp(-(x-5)**2)+np.exp(-(x+5)**2)):
            self.assertIsNone(measure_spectrum(x, signal)['fwhm_mev'])
        self.assertIsNone(simulate(config=Config(expected_counts=100, poisson=True)).metrics['fwhm_mev'])


class TrainingTests(unittest.TestCase):
    def test_random_reproducibility_and_reachable_answer(self):
        for count in (1, 3, 9):
            for difficulty in ('easy', 'medium', 'hard'):
                exercise = new_exercise(1234, difficulty, count)
                self.assertEqual(exercise, new_exercise(1234, difficulty, count))
                self.assertEqual(sum(v != 0 for v in exercise.initial.values()), count)
                answer = {k: -v for k, v in exercise.initial.items()}
                self.assertLessEqual(max(abs(v) for v in answer.values()), 120)
                feedback = exercise.feedback(answer)
                self.assertEqual(feedback['normalized_rms'], 0)
                self.assertEqual(feedback['residual'], coefficients())
                self.assertLess(simulate(exercise.initial).clipped_fraction, 0.001)
        self.assertNotEqual(new_exercise(1).initial, new_exercise(2).initial)

    def test_difficulty_does_not_collapse_under_field_limit(self):
        for count in (1, 3, 9):
            sizes = [sum(v*v for v in new_exercise(42, level, count).initial.values())
                     for level in ('easy', 'medium', 'hard')]
            self.assertLess(sizes[0], sizes[1])
            self.assertLess(sizes[1], sizes[2])

    def test_compensation_recovers_baseline(self):
        exercise = new_exercise(89)
        answer = {k: -v for k, v in exercise.initial.items()}
        np.testing.assert_array_equal(simulate(exercise.residual(answer)).counts, simulate().counts)

    def test_default_third_order_seed_and_score_are_unchanged(self):
        old = {'D10': -5.77, 'D01': -4.41, 'D20': -5.83, 'D11': 6.74, 'D02': 6.72,
               'D30': -5.39, 'D21': 3.78, 'D12': 4.88, 'D03': -4.49}
        q = new_exercise(42)
        self.assertEqual(q.initial, coefficients(old))
        self.assertEqual(q.max_order, 3)
        self.assertAlmostEqual(q.feedback({})['normalized_rms'], np.sqrt(np.mean(np.square(list(old.values()))))/120)

    def test_all_orders_reproducible_reachable_and_bounded(self):
        baseline = simulate().counts
        for order in range(1, 6):
            eligible = terms_through(order)
            for count in (1, len(eligible)):
                for level in ('easy', 'medium', 'hard'):
                    q = new_exercise(42, level, count, max_order=order)
                    self.assertEqual(q, new_exercise(42, level, count, max_order=order))
                    self.assertEqual(sum(v != 0 for v in q.initial.values()), count)
                    self.assertTrue(all(q.initial[n] == 0 for n in TERMS if n not in eligible))
                    self.assertLess(simulate(q.initial).clipped_fraction, 0.001)
                    feedback = q.feedback({})
                    self.assertEqual(feedback['eligible_terms'], eligible)
                    self.assertEqual(feedback['max_order'], order)
                    expected_score = np.sqrt(np.mean([q.initial[n]**2 for n in eligible]))/120
                    self.assertAlmostEqual(feedback['normalized_rms'], expected_score)
                    self.assertEqual(q.feedback(feedback['answer'])['normalized_rms'], 0)
                    np.testing.assert_array_equal(simulate(q.residual(feedback['answer'])).counts, baseline)
        for order in (4, 5):
            sizes = [sum(v*v for v in new_exercise(42, level, len(terms_through(order)), max_order=order).initial.values())
                     for level in ('easy', 'medium', 'hard')]
            self.assertLess(sizes[0], sizes[1]); self.assertLess(sizes[1], sizes[2])
        q = new_exercise(42)
        with self.assertRaises(ValueError): q.feedback({'D04': 1})
        with self.assertRaises(ValueError): q.residual({'D05': 1})

    def test_bad_training_inputs(self):
        for args in ((-1,), (42, 'unknown'), (42, 'easy', 0), (42, 'easy', 10), (True,)):
            with self.assertRaises(ValueError): new_exercise(*args)
        for kwargs in ({'max_order': True}, {'max_order': 6}, {'max_order': 0}, {'max_order': 4.0},
                       {'max_order': 4, 'term_count': 15}, {'max_order': 5, 'term_count': 21},
                       {'max_order': 1, 'term_count': 3}, {'max_order': 5, 'term_count': True}):
            with self.assertRaises(ValueError): new_exercise(42, **kwargs)


class DisplayExportTests(unittest.TestCase):
    def test_grayscale_direction_orientation_and_no_mutation(self):
        a = np.array([[0., 5.], [2., 10.]])
        before = a.copy()
        pixels, maximum = grayscale(a, gamma=1)
        self.assertEqual(maximum, 10)
        self.assertEqual(pixels[0, 0], 0)
        self.assertEqual(pixels[1, 1], 255)
        blob, _ = png_bytes(a, gamma=1)
        image = Image.open(io.BytesIO(blob))
        self.assertEqual(image.mode, 'L')
        np.testing.assert_array_equal(np.asarray(image), np.flipud(pixels))
        np.testing.assert_array_equal(a, before)
        locked, _ = grayscale(a, gamma=1, vmax=20)
        self.assertEqual(locked.max(), 128)

    def test_export_lossless_and_pickle_free(self):
        r = simulate({'D20': 15, 'D22': -4, 'D05': 7})
        original_width = r.metrics['fwhm_mev']
        png_bytes(r.counts, gamma=0.2)
        self.assertEqual(original_width, r.metrics['fwhm_mev'])
        with np.load(io.BytesIO(export_npz(r, {'seed': 42})), allow_pickle=False) as data:
            np.testing.assert_array_equal(data['counts'], r.counts)
            np.testing.assert_array_equal(data['spectrum'], data['counts'].sum(axis=0))
            metadata = json.loads(str(data['metadata_json']))
            self.assertEqual(metadata['effective_coefficients'], coefficients({'D20': 15, 'D22': -4, 'D05': 7}))
            self.assertEqual(metadata['model_version'], MODEL_VERSION)
            self.assertEqual(metadata['terms'], list(TERMS))
            self.assertEqual(metadata['powers'], [list(p) for p in POWERS])
            self.assertEqual(metadata['labels']['seed'], 42)
            self.assertEqual(metadata['units']['energy'], 'meV')


class LegacyTests(unittest.TestCase):
    def test_frozen_default_regression(self):
        _, result = legacy.simulate()
        self.assertEqual(len(result['x_det']), 490940)
        self.assertEqual(result['survival_fraction'], 0.98188)
        self.assertAlmostEqual(result['x_det'].std(), 0.007175429422932736, places=14)
        self.assertEqual(legacy.detector_histogram(result['x_det'], result['y_det'])[0].sum(), 490940)

    def test_reviewed_raw_numerics_match(self):
        path = Path(__file__).resolve().parents[1]/'raw/20260912/xiangcha.py'
        if not path.exists(): self.skipTest('raw 原件未分发；固定数值回归仍会运行')
        # Only the previously inspected numerical functions/constants; never the
        # matplotlib import, gallery, main block, output writes or source commands.
        tree = ast.parse(path.read_text())
        allowed = {'sample_uniform_disk', 'generate_initial_rays', 'propagate_to_slot', 'apply_slot',
                   'transform_angles', 'aberration_polynomial', 'propagate_to_detector', 'simulate'}
        nodes = [n for n in tree.body if isinstance(n, ast.Assign) or isinstance(n, ast.FunctionDef) and n.name in allowed]
        namespace = {'np': np}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
        coeff = {'x': 0.1, 'y': -.06, 'x^2': .14, 'xy': .2, 'y^2': .18,
                 'x^3': .06, 'x^2 y': -.1, 'x y^2': .09, 'y^3': .12}
        _, original = namespace['simulate'](coeff, seed=1234, n_rays=50000)
        _, adopted = legacy.simulate(coeff, seed=1234, n_rays=50000)
        self.assertEqual(set(original), set(adopted))
        for key in original:
            np.testing.assert_allclose(adopted[key], original[key], rtol=1e-14, atol=1e-16, err_msg=key)


if __name__ == '__main__':
    unittest.main()
