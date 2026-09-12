"""Generate derived examples and a reproducible offline validation summary.

Run from the checkout with PYTHONPATH=src. Only processed/ is written; rerunning
refreshes these derived validation artifacts, never raw/ or instrument settings.
"""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
from PIL import __version__ as pillow_version

from eels_sim import Config, MODEL_VERSION, simulate
from eels_sim.presentation import export_npz, png_bytes
from eels_sim.server import Application
from eels_sim.training import new_exercise


def main():
    root = Path(__file__).resolve().parents[1]
    out = root/'processed/examples'
    out.mkdir(parents=True, exist_ok=True)
    question = new_exercise(42)
    examples = {}
    for name, coeff, labels in [('baseline', {}, None), ('training_seed42', question.initial, question.feedback({}))]:
        result = simulate(coeff)
        (out/f'{name}.png').write_bytes(png_bytes(result.counts)[0])
        (out/f'{name}.npz').write_bytes(export_npz(result, labels))
        examples[name] = {'coefficients': result.effective, 'metrics': result.metrics,
                          'counts_sum': float(result.counts.sum()), 'clipped_fraction': result.clipped_fraction}
    convergence = []
    for n, bins, half in [(4096, 801, 40), (65536, 801, 120), (262144, 1601, 120), (16384, 801, 480)]:
        result = simulate(config=Config(n_rays=n, energy_bins=bins, energy_half_range_mev=half))
        convergence.append({'rays': n, 'energy_bins': bins, 'half_range_mev': half,
                            'fwhm_mev': result.metrics['fwhm_mev']})
    app = Application()
    request = {'session': app.create_session()['session'], 'mode': 'free',
               'controls': {'D01': 20, 'D20': -25, 'D11': 15}}
    app.dispatch('/api/frame', request)
    milliseconds = []
    for i in range(30):
        request['controls']['D01'] = i
        start = perf_counter()
        app.dispatch('/api/frame', request)
        milliseconds.append((perf_counter()-start)*1000)
    summary = {'recorded_at': datetime.now().astimezone().isoformat(), 'model_version': MODEL_VERSION,
               'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pillow': pillow_version,
                               'system': platform.system(), 'release': platform.release(), 'machine': platform.machine()},
               'examples': examples, 'convergence': convergence,
               'warm_frame_benchmark': {'samples': 30, 'median_ms': float(np.median(milliseconds)),
                                       'p95_ms': float(np.percentile(milliseconds, 95)), 'max_ms': max(milliseconds),
                                       'scope': 'Application.dispatch frame: core + PNG + response data; excludes HTTP/browser/Windows WSL forwarding',
                                       'config': asdict(Config())}}
    path = root/'processed/validation/numerical-summary.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary, ensure_ascii=False, indent=2)+'\n'
    path.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
