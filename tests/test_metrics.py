import math
import unittest

from eval_threshold_calibrator.io import config_from_dict
from eval_threshold_calibrator.metrics import (
    compare_result_field,
    compute_stability_interval,
    confusion_from_predictions,
    constraints_satisfied,
    filter_labeled_records,
    normalize_value,
    rates,
    raw_from_normalized,
    scan_metric,
    score_threshold,
    threshold_candidates,
)
from eval_threshold_calibrator.models import CalibrationConfig, MetricConfig


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"label": True, "score": 0.9, "latency_ms": 10},
            {"label": True, "score": 0.8, "latency_ms": 20},
            {"label": False, "score": 0.4, "latency_ms": 30},
            {"label": False, "score": 0.3, "latency_ms": 40},
        ]
        self.labels = [True, True, False, False]

    def test_normalize_higher_with_range(self):
        m = MetricConfig("score", min_value=0, max_value=1)
        self.assertEqual(normalize_value(0.7, m), 0.7)

    def test_normalize_lower_with_range(self):
        m = MetricConfig("latency", direction="lower", min_value=0, max_value=100)
        self.assertEqual(normalize_value(20, m), 0.8)

    def test_normalize_lower_without_range(self):
        self.assertEqual(normalize_value(20, MetricConfig("latency", direction="lower")), -20)

    def test_raw_from_normalized_higher(self):
        m = MetricConfig("score", min_value=0, max_value=10)
        self.assertEqual(raw_from_normalized(0.5, m), 5)

    def test_raw_from_normalized_lower(self):
        m = MetricConfig("latency", direction="lower", min_value=0, max_value=100)
        self.assertAlmostEqual(raw_from_normalized(0.8, m), 20)

    def test_confusion(self):
        c = confusion_from_predictions([True, True, False, False], [True, False, True, False])
        self.assertEqual((c.tp, c.fp, c.tn, c.fn), (1, 1, 1, 1))

    def test_rates(self):
        c = confusion_from_predictions([True, True, False, False], [True, False, True, False])
        r = rates(c)
        self.assertEqual(r["precision"], 0.5)
        self.assertEqual(r["recall"], 0.5)
        self.assertEqual(r["fpr"], 0.5)
        self.assertEqual(r["fnr"], 0.5)
        self.assertEqual(r["f1"], 0.5)

    def test_threshold_candidates(self):
        candidates = threshold_candidates([0.2, 0.2, 0.8])
        self.assertEqual(len(candidates), 4)
        self.assertLess(candidates[0], 0.2)
        self.assertGreater(candidates[-1], 0.8)

    def test_score_threshold_perfect(self):
        point = score_threshold([0.9, 0.8, 0.4, 0.3], [0.9, 0.8, 0.4, 0.3], self.labels, 0.8, 0.8, "f1")
        self.assertEqual(point.confusion.tp, 2)
        self.assertEqual(point.confusion.fp, 0)
        self.assertEqual(point.f1, 1.0)

    def test_score_threshold_auxiliary(self):
        point = score_threshold(
            [0.9, 0.1],
            [0.9, 0.1],
            [True, False],
            0.5,
            0.5,
            "f1",
            [{"cost_usd": 1}, {"cost_usd": 3}],
        )
        self.assertEqual(point.auxiliaries["cost_usd_avg_all"], 2)
        self.assertEqual(point.auxiliaries["cost_usd_sum_accepted"], 1)

    def test_constraints_satisfied(self):
        cfg = CalibrationConfig(target_precision=0.9)
        point = score_threshold([0.9, 0.1], [0.9, 0.1], [True, False], 0.5, 0.5, "f1")
        self.assertTrue(constraints_satisfied(point, cfg, MetricConfig("score")))

    def test_constraints_reject_precision(self):
        cfg = CalibrationConfig(target_precision=1.0)
        point = score_threshold([0.9, 0.8], [0.9, 0.8], [True, False], 0.5, 0.5, "f1")
        self.assertFalse(constraints_satisfied(point, cfg, MetricConfig("score")))

    def test_filter_labeled_records(self):
        records, labels, skipped = filter_labeled_records([{"label": "yes"}, {"label": "?"}], "label")
        self.assertEqual(len(records), 1)
        self.assertEqual(labels, [True])
        self.assertEqual(skipped, 1)

    def test_scan_metric_best_threshold(self):
        metric = MetricConfig("score", min_value=0, max_value=1)
        report = scan_metric(self.records, self.labels, metric, CalibrationConfig(), ["latency_ms"])
        self.assertAlmostEqual(report.best.f1, 1.0)
        self.assertLessEqual(report.threshold, 0.8)
        self.assertIn("latency_ms_avg_all", report.best.auxiliaries)

    def test_scan_metric_lower_direction(self):
        records = [
            {"label": True, "latency": 10},
            {"label": False, "latency": 90},
        ]
        report = scan_metric(records, [True, False], MetricConfig("latency", direction="lower"), CalibrationConfig(), [])
        self.assertGreaterEqual(report.threshold, 10)

    def test_scan_metric_missing_warns(self):
        report = scan_metric([{"label": True, "score": 1}, {"label": False}], [True, False], MetricConfig("score"), CalibrationConfig(), [])
        self.assertTrue(report.warnings)

    def test_scan_metric_no_values(self):
        with self.assertRaises(ValueError):
            scan_metric([{"label": True}], [True], MetricConfig("score"), CalibrationConfig(), [])

    def test_scan_metric_constraint_fallback_warns(self):
        cfg = CalibrationConfig(target_precision=1.1)
        report = scan_metric(self.records, self.labels, MetricConfig("score"), cfg, [])
        self.assertTrue(any("回退" in w for w in report.warnings))

    def test_compute_stability_interval(self):
        metric = MetricConfig("score")
        cfg = CalibrationConfig(stability_tolerance=0.0)
        report = scan_metric(self.records, self.labels, metric, cfg, [])
        interval = compute_stability_interval(report.points, report.best, cfg, metric)
        self.assertGreaterEqual(interval.count, 1)

    def test_compare_result_field(self):
        point = compare_result_field(
            [{"passed": True}, {"passed": False}, {"passed": True}],
            [True, True, False],
            "passed",
        )
        self.assertIsNotNone(point)
        self.assertEqual(point.confusion.tp, 1)

    def test_compare_result_field_none_without_field(self):
        self.assertIsNone(compare_result_field([{}], [True], None))

    def test_compare_result_field_none_without_predictions(self):
        self.assertIsNone(compare_result_field([{"passed": "?"}], [True], "passed"))

    def test_config_objective_precision_affects_score(self):
        cfg = config_from_dict({"objective": "precision", "metrics": {"score": {}}})
        report = scan_metric(self.records, self.labels, cfg.metrics["score"], cfg, [])
        self.assertEqual(report.best.objective_value, report.best.precision)

    def test_no_nan_in_compare_result_objective(self):
        point = compare_result_field([{"passed": True}], [True], "passed")
        self.assertFalse(math.isnan(point.objective_value))


if __name__ == "__main__":
    unittest.main()
