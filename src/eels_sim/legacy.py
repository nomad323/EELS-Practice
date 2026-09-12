"""Numerical-only preservation of raw/20260912/xiangcha.py's default model.

Source SHA256: 1a9baa4ecbaae4d3118c530a94a816a1487857145a618d3fa55cca9ba0b720e9
The original CRLF source is untouched. Defaults, RNG order, slit and detector
mapping are preserved here; matplotlib, gallery and filesystem effects removed.
This path uses the original ARBITRARY units, NOT the new 8 meV model.
"""
import numpy as np

from .model import polynomial


N_RAYS = 500_000
RANDOM_SEED = 42


def sample_uniform_disk(n, radius=1.0, rng=None):
    rng = np.random.default_rng() if rng is None else rng
    r = radius*np.sqrt(rng.random(n))
    theta = 2*np.pi*rng.random(n)
    return r*np.cos(theta), r*np.sin(theta)


def generate_initial_rays(n_rays=N_RAYS, source_sigma_x=0.015, source_sigma_y=0.015,
                          angle_radius=1.0, energy_sigma=0.015, seed=RANDOM_SEED):
    rng = np.random.default_rng(seed)
    x0 = rng.normal(0, source_sigma_x, n_rays)
    y0 = rng.normal(0, source_sigma_y, n_rays)
    ax0, ay0 = sample_uniform_disk(n_rays, angle_radius, rng)
    dE = rng.normal(0, energy_sigma, n_rays)
    return dict(x0=x0, y0=y0, ax0=ax0, ay0=ay0, dE=dE)


def propagate_to_slot(rays):
    return dict(rays, x_slot=rays['x0']+0.02*rays['ax0']+1.2*rays['dE'],
                y_slot=rays['y0']+0.02*rays['ay0'])


def apply_slot(rays):
    mask = np.abs(rays['x_slot']) < 0.12/2
    clipped = {key: value[mask] for key, value in rays.items()}
    clipped['survival_fraction'] = float(np.mean(mask))
    return clipped


def transform_angles(rays):
    return dict(rays, ux=rays['ax0'], uy=rays['ay0'])


def aberration_polynomial(ux, uy, coeffs):
    return polynomial(ux, uy, coeffs)


def propagate_to_detector(rays, aberration_coeffs):
    dx_ab = aberration_polynomial(rays['ux'], rays['uy'], aberration_coeffs)
    return dict(rays, x_det=0.3*rays['x_slot']+dx_ab, y_det=rays['uy'], dx_ab=dx_ab)


def simulate(aberration_coeffs=None, seed=RANDOM_SEED, n_rays=N_RAYS):
    before = propagate_to_slot(generate_initial_rays(n_rays=n_rays, seed=seed))
    rays = propagate_to_detector(transform_angles(apply_slot(before)), aberration_coeffs)
    return before, rays


def detector_histogram(x, y, bins=420, xlim=(-1.25, 1.25), ylim=(-1.05, 1.05)):
    h, xe, ye = np.histogram2d(x, y, bins=[bins, bins], range=[xlim, ylim])
    return h.T, xe, ye
