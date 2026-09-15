"""Hidden synthetic aberrations and coefficient-space compensation exercises."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from .model import Config, CONTROL_LIMIT, MAX_ORDER, TERMS, coefficients, terms_through

# Version the question distribution separately from the unchanged forward model.
GENERATOR_VERSION = "eels-exercise-per-term-2"
DIFFICULTY = {"easy": 20.0, "medium": 45.0, "hard": 90.0, "hell": 300.0}
CUSTOM_AMPLITUDE_MIN = 0.1  # Keeps every selected term nonzero after rounding.


@dataclass(frozen=True)
class Exercise:
    seed: int
    difficulty: str
    term_count: int
    initial: dict
    creation_config: dict
    max_order: int = 3
    generator_version: str = GENERATOR_VERSION
    custom_amplitude: float | None = None

    @property
    def amplitude(self):
        return self.custom_amplitude if self.difficulty == "custom" else DIFFICULTY[self.difficulty]

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
                "generator_version": self.generator_version,
                "amplitude": self.amplitude, "control_limit": CONTROL_LIMIT,
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


def new_exercise(seed, difficulty="medium", term_count=9, config=None, max_order=3, custom_amplitude=None):
    """Draw each active |Dij| in [0.35, 1] × difficulty, without a shared budget.

    Scene settings affect the image, not label strength. Large exercises may
    exceed the displayed field; the forward model reports that clipping.
    Custom difficulty requires a finite amplitude ceiling in [0.1, 300] meV;
    other difficulties ignore this optional setting. Existing preset seeds keep
    their coefficients; version 2 adds hell/custom and the 300 meV score scale.
    """
    config = Config() if config is None else config
    if not isinstance(config, Config):
        raise ValueError("config 应为 Config")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("题目种子应为 0…4294967295 的整数")
    eligible = terms_through(max_order)
    if (not isinstance(difficulty, str) or difficulty not in (*DIFFICULTY, "custom")
            or type(term_count) is not int or not 1 <= term_count <= len(eligible)):
        raise ValueError(f"未知难度或项数；最高 {max_order} 阶可选 1…{len(eligible)} 项")
    if difficulty == "custom":
        if (isinstance(custom_amplitude, bool) or not isinstance(custom_amplitude, (int, float))
                or not math.isfinite(custom_amplitude)
                or not CUSTOM_AMPLITUDE_MIN <= custom_amplitude <= CONTROL_LIMIT):
            raise ValueError(f"自定义难度单项上限应为 {CUSTOM_AMPLITUDE_MIN:g}…{CONTROL_LIMIT:g} meV 的有限数值")
        custom_amplitude = float(custom_amplitude)
        amplitude = custom_amplitude
    else:
        custom_amplitude = None
        amplitude = DIFFICULTY[difficulty]
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(eligible), size=term_count, replace=False)
    initial = coefficients()
    for index in selected:
        initial[TERMS[index]] = round(float(rng.choice((-1, 1)) * rng.uniform(0.35, 1) * amplitude), 2)
    # Do not shrink the whole vector by its summed displacement: that dilutes
    # each term as more are enabled, especially with twenty mixed-order terms.
    return Exercise(seed, difficulty, term_count, initial, asdict(config), max_order,
                    custom_amplitude=custom_amplitude)
