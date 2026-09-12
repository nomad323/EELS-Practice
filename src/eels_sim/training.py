"""Hidden synthetic aberrations and coefficient-space compensation exercises."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from .model import Config, CONTROL_LIMIT, POWERS, TERMS, coefficients

DIFFICULTY = {"easy": 20.0, "medium": 45.0, "hard": 90.0}


@dataclass(frozen=True)
class Exercise:
    seed: int
    difficulty: str
    term_count: int
    initial: dict
    creation_config: dict

    def residual(self, controls):
        c = checked_controls(controls)
        return {name: self.initial[name] + c[name] for name in TERMS}

    def feedback(self, controls):
        c = checked_controls(controls)
        residual = self.residual(c)
        return {"seed": self.seed, "difficulty": self.difficulty, "term_count": self.term_count,
                "creation_config": self.creation_config, "initial": self.initial, "controls": c,
                "answer": {name: -self.initial[name] for name in TERMS},
                "residual": residual,
                "normalized_rms": math.sqrt(sum((r/CONTROL_LIMIT)**2 for r in residual.values())/len(TERMS)),
                "note": "与生成标签的差距，不是唯一图像反演或真实仪器误差"}


def checked_controls(values):
    result = coefficients(values)
    if any(abs(v) > CONTROL_LIMIT for v in result.values()):
        raise ValueError(f"滑块补偿范围为 ±{CONTROL_LIMIT:g} meV")
    return result


def new_exercise(seed, difficulty="medium", term_count=9, config=None):
    config = Config() if config is None else config
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("题目种子应为 0…4294967295 的整数")
    if difficulty not in DIFFICULTY or type(term_count) is not int or term_count not in (1, 3, 9):
        raise ValueError("未知难度或项数")
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(TERMS), size=term_count, replace=False)
    initial = coefficients()
    for index in selected:
        initial[TERMS[index]] = float(rng.choice((-1, 1)) * rng.uniform(0.35, 1) * DIFFICULTY[difficulty])
    # Triangle inequality bounds displacement for this pupil. Reserve room for
    # six-sigma energy spread, including user-selected extra broadening.
    max_u = min(config.pupil_x, config.angular_slit_half)
    bound = sum(abs(initial[name])*max_u**i*config.pupil_y**j for name, (i, j) in zip(TERMS, POWERS))
    field_fraction = {"easy": 0.20, "medium": 0.40, "hard": 0.65}[difficulty]
    budget = max(2, min(config.energy_half_range_mev*field_fraction, config.energy_half_range_mev-6*config.sigma_mev))
    factor = min(1.0, budget/bound) if bound else 1.0
    initial = {name: round(value*factor, 2) for name, value in initial.items()}
    return Exercise(seed, difficulty, term_count, initial, asdict(config))
