import tempfile
from pathlib import Path
import unittest

from eels_sim.server import Application


class BlindPracticeStatsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="eels-stats-")
        self.path = Path(self.temporary.name) / "records.sqlite3"
        self.app = Application(stats_path=self.path)
        self.token = self.app.create_session()["session"]
        self.request = {"session": self.token, "mode": "practice", "action": "new",
                        "seed": 42, "difficulty": "medium", "term_count": 3,
                        "max_order": 3, "config": {"n_rays": 4096}}

    def tearDown(self):
        self.app.close()
        self.temporary.cleanup()

    def process(self, exercise, *, include_false_positive=False):
        rows = {}
        false_positive_used = False
        for name in exercise.feedback({})["eligible_terms"]:
            active = exercise.initial[name] != 0
            touched = active or include_false_positive and not false_positive_used
            if touched and not active:
                false_positive_used = True
            answer = -exercise.initial[name]
            rows[name] = {"focus_ms": 600 if touched else 0, "active_ms": 500 if touched else 0, "visits": int(touched),
                          "adjustments": int(touched), "path_abs": abs(answer) if active else (1 if touched else 0),
                          "reversals": 0, "cancelled": 0, "step_changes": int(touched),
                          "first_delta": answer if active else (1 if touched else 0)}
        return {"terms": rows, "scene_changed": False}

    def submit(self, attempt_id, process):
        return self.app.dispatch("/api/stats/submit", {
            "session": self.token, "attempt_id": attempt_id, "duration_ms": 4000,
            "started_at": "2026-09-22T10:00:00.000Z", "process": process})["attempt"]

    def test_blind_submission_scores_and_persists_without_early_reveal(self):
        first = self.app.dispatch("/api/frame", self.request)
        self.assertNotIn("feedback", first)
        exercise = self.app.sessions[self.token].exercise
        answer = exercise.feedback({})["answer"]
        final = self.app.dispatch("/api/frame", {**self.request, "action": "update", "controls": answer})
        self.assertNotIn("feedback", final)

        record = self.submit("blind-attempt-1", self.process(exercise, include_false_positive=True))
        self.assertFalse(record["assisted"])
        self.assertEqual(record["score"]["hidden_count"], 3)
        self.assertEqual(record["score"]["improved_count"], 3)
        self.assertEqual(record["score"]["false_positive_count"], 1)
        self.assertEqual(record["score"]["first_direction_correct"], 3)
        self.assertAlmostEqual(record["score"]["improvement_ratio"], 1)
        self.assertGreater(record["score"]["path_efficiency"], 0.95)
        self.assertLess(record["score"]["path_efficiency"], 1)  # The deliberate false-positive costs path efficiency.
        self.assertEqual(record["active_ms"], 2000)
        self.assertEqual(record["focus_ms"], 2400)
        self.assertEqual(record["observation_ms"], 2000)
        self.assertTrue(all("initial" in row for row in record["term_outcomes"].values()))
        self.assertEqual(record["stats_version"], 2)
        self.assertEqual(record["comparison"]["initial"]["display_vmax"], record["comparison"]["final"]["display_vmax"])
        self.assertNotIn("feedback", self.app.dispatch("/api/frame", {**self.request, "action": "update"}))

        listed = self.app.dispatch("/api/stats/list", {"session": self.token, "limit": 10})
        self.assertEqual([item["id"] for item in listed["attempts"]], ["blind-attempt-1"])
        exported = self.app.dispatch("/api/stats/list", {"session": self.token, "limit": "all"})
        self.assertEqual(exported["attempts"], listed["attempts"])
        self.assertEqual(self.submit("blind-attempt-1", self.process(exercise))["id"], record["id"])
        self.assertEqual(len(self.app.dispatch("/api/stats/list", {"session": self.token})["attempts"]), 1)
        with self.assertRaisesRegex(ValueError, "已经提交"):
            self.submit("blind-attempt-2", self.process(exercise))

        self.app.close()
        self.app = Application(stats_path=self.path)
        new_token = self.app.create_session()["session"]
        persisted = self.app.dispatch("/api/stats/list", {"session": new_token, "limit": 10})
        self.assertEqual(persisted["attempts"][0]["id"], "blind-attempt-1")

    def test_reveal_marks_assisted_and_retry_resets_submission(self):
        self.app.dispatch("/api/frame", self.request)
        exercise = self.app.sessions[self.token].exercise
        self.app.dispatch("/api/frame", {**self.request, "action": "reveal"})
        assisted = self.submit("assisted-1", self.process(exercise))
        self.assertTrue(assisted["assisted"])

        self.app.dispatch("/api/frame", {**self.request, "action": "retry"})
        retried = self.submit("blind-retry-1", self.process(exercise))
        self.assertTrue(retried["assisted"])
        self.app.dispatch("/api/frame", {**self.request, "action": "retry"})
        self.app.dispatch("/api/export", {"session": self.token})
        process = self.process(exercise)
        process["scene_changed"] = True  # Includes change-and-restore traces from the browser.
        exported = self.submit("exported-labels-1", process)
        self.assertTrue(exported["assisted"])
        self.assertTrue(exported["scene_changed"])
        self.assertEqual(len(self.app.dispatch("/api/stats/list", {"session": self.token})["attempts"]), 3)

    def test_probing_then_returning_to_zero_is_not_identification(self):
        self.app.dispatch("/api/frame", self.request)
        exercise = self.app.sessions[self.token].exercise
        process = self.process(exercise)
        result = self.submit("probe-returned-zero", process)
        self.assertEqual(result["score"]["improved_count"], 0)
        self.assertEqual(result["score"]["hidden_count"], 3)
        self.assertEqual(len(result["score"]["not_improved_terms"]), 3)
        self.assertEqual(sum(row["adjustments"] for row in result["term_outcomes"].values()), 3)

    def test_wrong_direction_is_not_reported_as_improvement(self):
        self.app.dispatch("/api/frame", self.request)
        exercise = self.app.sessions[self.token].exercise
        name = next(name for name, value in exercise.initial.items() if value != 0)
        wrong = {name: exercise.initial[name]}
        self.app.dispatch("/api/frame", {**self.request, "action": "update", "controls": wrong})
        record = self.submit("wrong-direction-1", self.process(exercise))
        self.assertFalse(record["term_outcomes"][name]["improved"])
        self.assertIn(name, record["score"]["not_improved_terms"])
        self.assertEqual(record["score"]["improved_count"], 0)

    def test_post_submission_review_exposes_same_seed_for_retry(self):
        self.app.dispatch("/api/frame", self.request)
        exercise = self.app.sessions[self.token].exercise
        first = self.submit("reviewed-attempt-1", self.process(exercise))
        self.assertFalse(first["assisted"])
        self.app.dispatch("/api/frame", {**self.request, "action": "retry"})
        retried = self.submit("reviewed-attempt-2", self.process(exercise))
        self.assertTrue(retried["assisted"])

    def test_submission_validation_and_free_mode_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "先开始"):
            self.submit("too-early", {"terms": {}, "scene_changed": False})
        self.app.dispatch("/api/frame", self.request)
        exercise = self.app.sessions[self.token].exercise
        invalid = self.process(exercise)
        invalid["terms"]["D10"]["active_ms"] = float("nan")
        with self.assertRaisesRegex(ValueError, "有限数值"):
            self.submit("invalid-nan", invalid)
        with self.assertRaisesRegex(ValueError, "未知字段"):
            self.app.dispatch("/api/stats/list", {"session": self.token, "extra": True})

        self.app.dispatch("/api/frame", {"session": self.token, "mode": "free", "controls": {}})
        with self.assertRaisesRegex(ValueError, "先开始"):
            self.submit("free-mode", self.process(exercise))


if __name__ == "__main__":
    unittest.main()
