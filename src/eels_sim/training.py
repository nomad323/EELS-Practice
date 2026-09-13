"""Hidden synthetic aberrations and coefficient-space compensation exercises."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from .model import Config, CONTROL_LIMIT, MAX_ORDER, POWERS, TERMS, coefficients, terms_through

DIFFICULTY = {"easy": 20.0, "medium": 45.0, "hard": 90.0}


@dataclass(frozen=True)
class Exercise:
    seed: int
    difficulty: str
    term_count: int
    initial: dict
    creation_config: dict
    max_order: int = 3

    def residual(self, controls):
        c = checked_controls(controls, self.max_order)
        return {name: self.initial.get(name, 0.0) + c[name] for name in TERMS}

    def feedback(self, controls):
        c = checked_controls(controls, self.max_order)
        residual = self.residual(c)
        eligible = terms_through(self.max_order)
        initial = coefficients(self.initial)
        return {"seed": self.seed, "difficulty": self.difficulty, "term_count": self.term_count,
                "max_order": self.max_order, "eligible_terms": eligible,
                "creation_config": self.creation_config, "initial": initial, "controls": c,
                "answer": {name: -initial[name] for name in TERMS},
                "residual": residual,
                "normalized_rms": math.sqrt(sum((residual[n]/CONTROL_LIMIT)**2 for n in eligible)/len(eligible)),
                "note": "与生成标签的差距，不是唯一图像反演或真实仪器误差"}


def checked_controls(values, max_order=MAX_ORDER):
    eligible = terms_through(max_order)
    result = coefficients(values)
    if any(abs(v) > CONTROL_LIMIT for v in result.values()):
        raise ValueError(f"滑块补偿范围为 ±{CONTROL_LIMIT:g} meV")
    if any(value != 0 for name, value in result.items() if name not in eligible):
        raise ValueError(f"本题最高 {max_order} 阶，不能施加更高阶补偿")
    return result


def new_exercise(seed, difficulty="medium", term_count=9, config=None, max_order=3):
    config = Config() if config is None else config
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("题目种子应为 0…4294967295 的整数")
    eligible = terms_through(max_order)
    if difficulty not in DIFFICULTY or type(term_count) is not int or not 1 <= term_count <= len(eligible):
        raise ValueError(f"未知难度或项数；最高 {max_order} 阶可选 1…{len(eligible)} 项")
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(eligible), size=term_count, replace=False)
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
    return Exercise(seed, difficulty, term_count, initial, asdict(config), max_order)
