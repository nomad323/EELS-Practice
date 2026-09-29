"""Persistent, local-only records for completed blind-practice attempts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import threading

from .model import MODEL_VERSION, TERMS


STATS_VERSION = 2
MAX_ATTEMPT_MS = 24 * 60 * 60 * 1000


def default_stats_path():
    override = os.environ.get("EELS_PRACTICE_STATS_PATH")
    if override:
        return override
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "EELS-Practice" / "practice-stats.sqlite3"


def _finite_number(value, label, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}须为有限数值")
    value = float(value)
    if value < minimum or maximum is not None and value > maximum:
        suffix = f"{minimum:g}…{maximum:g}" if maximum is not None else f"不小于 {minimum:g}"
        raise ValueError(f"{label}应为{suffix}")
    return value


def checked_process(value, eligible):
    if not isinstance(value, dict) or set(value) != {"terms", "scene_changed"} \
            or not isinstance(value["terms"], dict) or not isinstance(value["scene_changed"], bool):
        raise ValueError("盲调过程记录格式无效")
    if set(value["terms"]) - set(eligible):
        raise ValueError("盲调过程包含本题不可调参数")
    allowed = {"focus_ms", "active_ms", "visits", "adjustments", "path_abs", "reversals",
               "cancelled", "step_changes", "first_delta"}
    result = {}
    for name in eligible:
        raw = value["terms"].get(name, {})
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(f"{name} 的过程记录格式无效")
        row = {
            "focus_ms": _finite_number(raw.get("focus_ms", 0), f"{name} 关注用时", 0, MAX_ATTEMPT_MS),
            "active_ms": _finite_number(raw.get("active_ms", 0), f"{name} 调节用时", 0, MAX_ATTEMPT_MS),
            "visits": int(_finite_number(raw.get("visits", 0), f"{name} 进入次数", 0, 1_000_000)),
            "adjustments": int(_finite_number(raw.get("adjustments", 0), f"{name} 操作次数", 0, 10_000_000)),
            "path_abs": _finite_number(raw.get("path_abs", 0), f"{name} 调节行程", 0, 100_000_000),
            "reversals": int(_finite_number(raw.get("reversals", 0), f"{name} 反向次数", 0, 10_000_000)),
            "cancelled": int(_finite_number(raw.get("cancelled", 0), f"{name} 取消次数", 0, 1_000_000)),
            "step_changes": int(_finite_number(raw.get("step_changes", 0), f"{name} 步长变化次数", 0, 1_000_000)),
            "first_delta": _finite_number(raw.get("first_delta", 0), f"{name} 首次变化", -600, 600),
        }
        result[name] = row
    return {"terms": result, "scene_changed": value["scene_changed"]}


def build_attempt_record(*, attempt_id, duration_ms, started_at, process, exercise,
                         feedback, initial_result, final_result, assisted):
    if not isinstance(attempt_id, str) or not 8 <= len(attempt_id) <= 128 \
            or not all(ch.isalnum() or ch in "-_" for ch in attempt_id):
        raise ValueError("练习记录编号无效")
    duration_ms = _finite_number(duration_ms, "总用时", 0, MAX_ATTEMPT_MS)
    if not isinstance(started_at, str) or not started_at or len(started_at) > 64:
        raise ValueError("开始时间无效")
    if not isinstance(assisted, bool):
        raise ValueError("辅助状态无效")

    eligible = feedback["eligible_terms"]
    checked = checked_process(process, eligible)
    process_terms = checked["terms"]
    active = [name for name in eligible if feedback["initial"][name] != 0]
    inactive = [name for name in eligible if feedback["initial"][name] == 0]
    touched = [name for name in eligible if process_terms[name]["adjustments"] > 0]
    # A nonzero control is not evidence that the hidden term was identified:
    # it may even move in the wrong direction. Report observed error reduction.
    improved = [name for name in active if abs(feedback["residual"][name]) < abs(feedback["initial"][name]) - 1e-9]
    false_positive = [name for name in inactive if name in touched]
    first_direction_terms = [name for name in active if process_terms[name]["first_delta"] != 0]
    first_direction_correct = [name for name in first_direction_terms
                               if process_terms[name]["first_delta"] * feedback["answer"][name] > 0]

    initial_rms = math.sqrt(sum(feedback["initial"][name] ** 2 for name in eligible) / len(eligible))
    final_rms = math.sqrt(sum(feedback["residual"][name] ** 2 for name in eligible) / len(eligible))
    improvement = 1 - final_rms / initial_rms if initial_rms else 0
    total_path = sum(row["path_abs"] for row in process_terms.values())
    initial_l1 = sum(abs(feedback["initial"][name]) for name in eligible)
    final_l1 = sum(abs(feedback["residual"][name]) for name in eligible)
    path_efficiency = max(0.0, min(1.0, (initial_l1 - final_l1) / total_path)) if total_path else 0.0
    active_ms = min(duration_ms, sum(row["active_ms"] for row in process_terms.values()))
    focus_ms = min(duration_ms, sum(row["focus_ms"] for row in process_terms.values()))
    scene_changed = checked["scene_changed"] or exercise.creation_config != final_result.metadata()["config"]

    outcomes = {}
    for name in eligible:
        row = process_terms[name]
        outcomes[name] = {
            "initial": feedback["initial"][name],
            "answer": feedback["answer"][name],
            "control": feedback["controls"][name],
            "residual": feedback["residual"][name],
            "active": name in active,
            "touched": name in touched,
            "improved": name in improved,
            "first_direction_correct": (row["first_delta"] * feedback["answer"][name] > 0)
                                       if name in first_direction_terms else None,
            **row,
        }

    return {
        "stats_version": STATS_VERSION,
        "id": attempt_id,
        "started_at": started_at,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": round(duration_ms, 1),
        "active_ms": round(active_ms, 1),
        "focus_ms": round(focus_ms, 1),
        "observation_ms": round(max(0, duration_ms - active_ms), 1),
        "assisted": assisted,
        "scene_changed": scene_changed,
        "question": {
            "seed": exercise.seed,
            "difficulty": exercise.difficulty,
            "term_count": exercise.term_count,
            "max_order": exercise.max_order,
            "amplitude": exercise.amplitude,
            "generator_version": exercise.generator_version,
            "model_version": MODEL_VERSION,
        },
        "scene": {
            "creation": exercise.creation_config,
            "final": final_result.metadata()["config"],
        },
        "score": {
            "initial_rms_mev": initial_rms,
            "final_rms_mev": final_rms,
            "normalized_rms": feedback["normalized_rms"],
            "improvement_ratio": improvement,
            "path_efficiency": path_efficiency,
            "hidden_count": len(active),
            "improved_count": len(improved),
            "improved_terms": improved,
            "not_improved_terms": [name for name in active if name not in improved],
            "false_positive_count": len(false_positive),
            "false_positive_terms": false_positive,
            "first_direction_total": len(first_direction_terms),
            "first_direction_correct": len(first_direction_correct),
            "reversals": sum(row["reversals"] for row in process_terms.values()),
            "visits": sum(row["visits"] for row in process_terms.values()),
        },
        "metrics": {
            "initial_fwhm_mev": initial_result.metrics["fwhm_mev"],
            "final_fwhm_mev": final_result.metrics["fwhm_mev"],
            "initial_rms_mev": initial_result.metrics["rms_mev"],
            "final_rms_mev": final_result.metrics["rms_mev"],
            "initial_clipped_fraction": initial_result.clipped_fraction,
            "final_clipped_fraction": final_result.clipped_fraction,
        },
        "term_outcomes": outcomes,
    }


class StatsStore:
    def __init__(self, path=None):
        target = default_stats_path() if path is None else path
        if str(target) != ":memory:":
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
        self.path = target
        self.lock = threading.Lock()
        self.connection = sqlite3.connect(str(target), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                assisted INTEGER NOT NULL,
                max_order INTEGER NOT NULL,
                term_count INTEGER NOT NULL,
                difficulty TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
        """)
        self.connection.execute("CREATE INDEX IF NOT EXISTS attempts_submitted ON attempts(submitted_at DESC)")
        self.connection.commit()

    def save(self, record):
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        q = record["question"]
        with self.lock:
            try:
                self.connection.execute(
                    "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record["id"], record["submitted_at"], int(record["assisted"]),
                     q["max_order"], q["term_count"], q["difficulty"], payload))
                self.connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("本次练习已经保存") from exc
        return record

    def list(self, limit=200):
        if limit != "all" and (type(limit) is not int or not 1 <= limit <= 5000):
            raise ValueError("历史记录条数应为 1…5000 的整数或 all")
        with self.lock:
            if limit == "all":
                rows = self.connection.execute(
                    "SELECT record_json FROM attempts ORDER BY submitted_at DESC").fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT record_json FROM attempts ORDER BY submitted_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self):
        with self.lock:
            self.connection.close()
