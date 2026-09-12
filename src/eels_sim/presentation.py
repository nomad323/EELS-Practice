"""Display-only grayscale mapping and lossless scientific array export."""
import base64
import io
import json
import math

import numpy as np
from PIL import Image

from .model import Result


def grayscale(counts, gamma=0.5, vmax=None):
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)) or not math.isfinite(gamma) or not 0.15 <= gamma <= 2:
        raise ValueError("显示 gamma 应在 0.15…2 之间")
    if vmax is not None and (isinstance(vmax, bool) or not isinstance(vmax, (int, float)) or not math.isfinite(vmax) or vmax <= 0):
        raise ValueError("锁定显示上限应为正有限数值")
    maximum = max(float(counts.max()), 1e-12) if vmax is None else float(vmax)
    pixels = np.rint(np.clip(counts/maximum, 0, 1)**gamma * 255).astype(np.uint8)
    return pixels, maximum


def png_bytes(counts, gamma=0.5, vmax=None):
    pixels, maximum = grayscale(counts, gamma, vmax)
    stream = io.BytesIO()
    # NumPy rows ascend in y; PNG/browser screen rows descend.
    Image.fromarray(np.flipud(pixels)).save(stream, format="PNG")
    return stream.getvalue(), maximum


def frame(result: Result, gamma=0.5, vmax=None):
    image, maximum = png_bytes(result.counts, gamma, vmax)
    return {"image_png": base64.b64encode(image).decode("ascii"),
            "energy_mev": result.energy_mev.tolist(), "spectrum": result.spectrum.tolist(),
            "y_range": [float(result.y[0]), float(result.y[-1])],
            "metrics": result.metrics, "transmission": result.transmission,
            "clipped_fraction": result.clipped_fraction, "display_vmax": maximum,
            "pixel_mev": float(result.energy_mev[1]-result.energy_mev[0]),
            "shape": list(result.counts.shape)}


def export_npz(result: Result, labels=None):
    metadata = result.metadata()
    metadata["labels"] = labels
    stream = io.BytesIO()
    # Unicode metadata, no pickled objects: load with allow_pickle=False.
    np.savez_compressed(stream, counts=result.counts, expected_counts=result.expected,
                        energy_mev=result.energy_mev, y=result.y, spectrum=result.spectrum,
                        metadata_json=np.array(json.dumps(metadata, ensure_ascii=False, allow_nan=False)))
    return stream.getvalue()
