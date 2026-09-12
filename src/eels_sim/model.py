"""Offline, energy-equivalent geometric EELS teaching model (not a Cc calibration).

Polynomial basis adapted from raw/20260912/xiangcha.py; original retained.
The new forward model marginalizes a fixed Gaussian energy response instead of
re-sampling dE each frame. No instrument API or external service is used.
"""
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
import math

import numpy as np

MODEL_VERSION = "eels-effective-1.0"
TERMS = ("D10", "D01", "D20", "D11", "D02", "D30", "D21", "D12", "D03")
POWERS = ((1, 0), (0, 1), (2, 0), (1, 1), (0, 2), (3, 0), (2, 1), (1, 2), (0, 3))
ALIASES = dict(zip(("x", "y", "x^2", "xy", "y^2", "x^3", "x^2 y", "x y^2", "y^3"), TERMS))
CONTROL_LIMIT = 120.0
FWHM_FACTOR = math.sqrt(8 * math.log(2))


def coefficients(values=None):
    """Canonical, complete coefficient dictionary; aliases cannot conflict."""
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ValueError("系数必须是对象")
    result = dict.fromkeys(TERMS, 0.0)
    seen = set()
    for name, value in values.items():
        term = ALIASES.get(name, name)
        if term not in TERMS or term in seen:
            raise ValueError(f"未知或重复系数: {name}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数值")
        if abs(value) > 1000:
            raise ValueError("有效系数绝对值不可超过 1000 meV")
        seen.add(term)
        result[term] = float(value)
    return result


def polynomial(u, v, values=None):
    u, v = np.broadcast_arrays(np.asarray(u, dtype=float), np.asarray(v, dtype=float))
    c = coefficients(values)
    result = np.zeros_like(u)
    for name, (i, j) in zip(TERMS, POWERS):
        result += c[name] * u**i * v**j
    return result


@dataclass(frozen=True)
class Config:
    base_fwhm_mev: float = 8.0
    extra_sigma_mev: float = 0.0
    pupil_x: float = 1.0
    pupil_y: float = 1.0
    angular_slit_half: float = 1.3
    y_psf_sigma: float = 0.0
    expected_counts: float = 1_000_000.0
    background_per_pixel: float = 0.0
    poisson: bool = False
    noise_seed: int = 17
    sample_seed: int = 42
    n_rays: int = 65_536
    energy_half_range_mev: float = 120.0
    energy_bins: int = 801
    y_bins: int = 181

    def __post_init__(self):
        ranges = {
            "base_fwhm_mev": (2, 40), "extra_sigma_mev": (0, 20),
            "pupil_x": (0.2, 1.3), "pupil_y": (0.2, 1.3),
            "angular_slit_half": (0.05, 1.3), "y_psf_sigma": (0, 0.2),
            "expected_counts": (100, 10_000_000), "background_per_pixel": (0, 20),
            "energy_half_range_mev": (40, 480),
        }
        for name, (lo, hi) in ranges.items():
            x = getattr(self, name)
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
                raise ValueError(f"{name} 应在 [{lo}, {hi}] 内")
        for name, lo, hi in (("noise_seed", 0, 2**32-1), ("sample_seed", 0, 2**32-1),
                             ("n_rays", 4096, 262144), ("energy_bins", 401, 1601), ("y_bins", 81, 241)):
            x = getattr(self, name)
            if type(x) is not int or not lo <= x <= hi:
                raise ValueError(f"{name} 应为 [{lo}, {hi}] 内的整数")
        if self.n_rays % 4 or self.energy_bins % 2 != 1 or self.y_bins % 2 != 1:
            raise ValueError("n_rays 须为 4 的倍数，像素数须为奇数")
        if type(self.poisson) is not bool:
            raise ValueError("poisson 必须是布尔值")

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict) or set(values) - {f.name for f in fields(cls)}:
            raise ValueError("未知场景设置")
        return cls(**values)

    @property
    def sigma_mev(self):
        return math.hypot(self.base_fwhm_mev / FWHM_FACTOR, self.extra_sigma_mev)


@lru_cache(maxsize=4)
def _pupil(n, seed, px, py, slit):
    """Fourfold paired MC sampling: stable frames and exact pupil parity."""
    rng = np.random.default_rng(seed)
    r = np.sqrt(rng.random(n // 4))
    theta = rng.random(n // 4) * np.pi / 2
    x, y = r * np.cos(theta) * px, r * np.sin(theta) * py
    u = np.concatenate((x, -x, x, -x))
    v = np.concatenate((y, y, -y, -y))
    keep = np.abs(u) <= slit
    u, v = u[keep], v[keep]
    basis = np.array([u**i * v**j for i, j in POWERS])
    basis.flags.writeable = False
    v.flags.writeable = False
    return basis, v


def _kernel(sigma_pixels):
    if sigma_pixels < 1e-10:
        return np.ones(1)
    radius = max(1, math.ceil(6 * sigma_pixels))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-0.5 * (x / sigma_pixels)**2)
    return k / k.sum()


def _convolve_axis(data, kernel, axis):
    """Zero-padded linear convolution, not periodic FFT wrapping."""
    if len(kernel) == 1:
        return data
    n = data.shape[axis] + len(kernel) - 1
    fft_n = 1 << (n - 1).bit_length()
    shape = [1] * data.ndim
    shape[axis] = -1
    frequency = np.fft.rfft(data, n=fft_n, axis=axis)
    frequency *= np.fft.rfft(kernel, n=fft_n).reshape(shape)
    out = np.fft.irfft(frequency, n=fft_n, axis=axis)
    slices = [slice(None)] * data.ndim
    start = len(kernel) // 2
    slices[axis] = slice(start, start + data.shape[axis])
    return np.maximum(out[tuple(slices)], 0.0)


def measure_spectrum(energy, spectrum, background=0.0, clipped_fraction=0.0, noisy=False):
    """Half-height connected-component FWHM, with invalid/ambiguous cases explicit.

    Known *synthetic* uniform background is subtracted, not fitted. No display
    gamma, Gaussian fitting, or undocumented smoothing is used.
    """
    x, values = np.asarray(energy, float), np.asarray(spectrum, float)
    if x.ndim != 1 or values.shape != x.shape or len(x) < 3 or np.any(np.diff(x) <= 0):
        raise ValueError("无效谱线坐标")
    if not np.isfinite(x).all() or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("谱线必须是非负有限计数")
    signal = np.maximum(values - background, 0)
    total = float(signal.sum())
    warnings = []
    result = {"fwhm_mev": None, "left_mev": None, "right_mev": None,
              "half_height": None, "centroid_mev": None, "rms_mev": None,
              "warnings": warnings, "status": "invalid"}
    if total <= 0:
        warnings.append("无可测量信号")
        return result
    centroid = float(np.dot(x, signal) / total)
    result.update(centroid_mev=centroid, rms_mev=float(np.sqrt(np.dot((x-centroid)**2, signal)/total)))
    half = float(signal.max()) / 2
    result["half_height"] = half + background
    above = signal >= half
    starts = np.flatnonzero(above & ~np.r_[False, above[:-1]])
    ends = np.flatnonzero(above & ~np.r_[above[1:], False])
    if clipped_fraction > 0.001:
        warnings.append("视野截断超过 0.1%，峰宽不可作为完整光斑的验收值")
    if len(starts) != 1:
        warnings.append("半高区存在多段（多峰或噪声）；不报告单一 FWHM")
    if above[0] or above[-1]:
        warnings.append("半高交点超出能量视野")
    if noisy and (total < 10_000 or signal.max() < 10 * math.sqrt(float(values.max()) + 1)):
        warnings.append("计数信噪比不足，FWHM 不可靠")
    if warnings:
        return result
    a, b = int(starts[0]), int(ends[0])
    left = x[a-1] + (half-signal[a-1])/(signal[a]-signal[a-1])*(x[a]-x[a-1])
    right = x[b] + (half-signal[b])/(signal[b+1]-signal[b])*(x[b+1]-x[b])
    result.update(fwhm_mev=float(right-left), left_mev=float(left), right_mev=float(right), status="ok")
    return result


@dataclass
class Result:
    counts: np.ndarray
    expected: np.ndarray
    energy_mev: np.ndarray
    y: np.ndarray
    spectrum: np.ndarray
    metrics: dict
    config: Config
    effective: dict
    transmission: float
    clipped_fraction: float

    def metadata(self):
        return {"model_version": MODEL_VERSION, "config": asdict(self.config),
                "effective_coefficients": self.effective, "metrics": self.metrics,
                "transmission": self.transmission, "clipped_fraction": self.clipped_fraction,
                "units": {"energy": "meV", "y": "reference-pupil normalized angle",
                          "Dij": "meV per dimensionless angular monomial"},
                "orientation": "counts[row=y ascending, column=energy ascending]",
                "scope": "synthetic effective response; not instrument-calibrated Cc"}


def simulate(values=None, config=None):
    config = Config() if config is None else config
    if not isinstance(config, Config):
        raise ValueError("config 应为 Config")
    c = coefficients(values)
    basis, v = _pupil(config.n_rays, config.sample_seed, config.pupil_x, config.pupil_y, config.angular_slit_half)
    shifts = np.zeros(len(v))
    for name, term in zip(TERMS, basis):
        shifts += c[name] * term
    energy = np.linspace(-config.energy_half_range_mev, config.energy_half_range_mev, config.energy_bins)
    y = np.linspace(-1.6, 1.6, config.y_bins)
    de, dy = energy[1]-energy[0], y[1]-y[0]
    kx, ky = _kernel(config.sigma_mev/de), _kernel(config.y_psf_sigma/dy)
    px, py = len(kx)//2 + 1, len(ky)//2 + 1
    nx, ny = len(energy)+2*px, len(y)+2*py
    # Extended domain includes light which can blur INTO the displayed field.
    # Cloud-in-cell energy deposition avoids slider quantization into pixel jumps.
    positions = (shifts-energy[0])/de + px
    ix = np.floor(positions).astype(int)
    fraction = positions-ix
    iy = np.rint((v-y[0])/dy).astype(int) + py
    histogram = np.zeros((ny, nx))
    for offset, weight in ((0, 1-fraction), (1, fraction)):
        xx = ix + offset
        valid = (xx >= 0) & (xx < nx) & (iy >= 0) & (iy < ny)
        histogram += np.bincount(iy[valid]*nx+xx[valid], weights=weight[valid], minlength=ny*nx).reshape(ny, nx)
    blurred = _convolve_axis(_convolve_axis(histogram, kx, 1), ky, 0)
    visible = blurred[py:py+len(y), px:px+len(energy)]
    accepted = len(v)
    transmission = accepted / config.n_rays
    clipped = float(np.clip(1-visible.sum()/accepted, 0, 1)) if accepted else 0.0
    expected = visible * (config.expected_counts/config.n_rays) + config.background_per_pixel
    counts = np.random.default_rng(config.noise_seed).poisson(expected).astype(float) if config.poisson else expected.copy()
    spectrum = counts.sum(axis=0)
    metrics = measure_spectrum(energy, spectrum, config.background_per_pixel*len(y), clipped, config.poisson)
    if not accepted:
        metrics["warnings"].append("角接受窗口内没有采样光线")
    return Result(counts, expected, energy, y, spectrum, metrics, config, c, transmission, clipped)
