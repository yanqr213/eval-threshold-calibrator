import json
import os
import tempfile
import unittest

from eval_threshold_calibrator.errors import ConfigError, InputError
from eval_threshold_calibrator.io import (
    config_from_dict,
    discover_metrics,
    load_config,
    read_csv,
    read_jsonl,
    read_metric_value,
    read_records,
)
from eval_threshold_calibrator.models import CalibrationConfig


class IoTests(unittest.TestCase):
    def temp_file(self, suffix, content):
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False)
        self.addCleanup(lambda: os.path.exists(fh.name) and os.unlink(fh.name))
        with fh:
            fh.write(content)
        return fh.name

    def test_read_jsonl(self):
        path = self.temp_file(".jsonl", '{"a":1}\n\n{"b":2}\n')
        self.assertEqual(read_jsonl(path), [{"a": 1}, {"b": 2}])

    def test_read_jsonl_invalid(self):
        path = self.temp_file(".jsonl", "{bad}\n")
        with self.assertRaises(InputError):
            read_jsonl(path)

    def test_read_jsonl_requires_object(self):
        path = self.temp_file(".jsonl", "[1]\n")
        with self.assertRaises(InputError):
            read_jsonl(path)

    def test_read_csv(self):
        path = self.temp_file(".csv", "id,label,score\n1,true,0.9\n")
        self.assertEqual(read_csv(path)[0]["score"], "0.9")

    def test_read_records_dispatch(self):
        path = self.temp_file(".csv", "id,label,score\n1,true,0.9\n")
        self.assertEqual(len(read_records(path)), 1)

    def test_read_records_rejects_extension(self):
        path = self.temp_file(".txt", "x")
        with self.assertRaises(InputError):
            read_records(path)

    def test_config_from_dict_defaults(self):
        cfg = config_from_dict({})
        self.assertEqual(cfg.label_field, "label")

    def test_config_unknown_field(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"bad": 1})

    def test_config_metrics_unknown_field(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"metrics": {"score": {"bad": 1}}})

    def test_config_invalid_objective(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"objective": "auc"})

    def test_config_invalid_direction(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"metrics": {"score": {"direction": "sideways"}}})

    def test_config_invalid_range(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"metrics": {"score": {"min_value": 1, "max_value": 1}}})

    def test_config_invalid_rate(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"max_fpr": 2})

    def test_config_auxiliary_must_be_list(self):
        with self.assertRaises(ConfigError):
            config_from_dict({"auxiliary_fields": "latency"})

    def test_load_config(self):
        path = self.temp_file(".json", json.dumps({"objective": "precision"}))
        self.assertEqual(load_config(path).objective, "precision")

    def test_load_config_invalid_json(self):
        path = self.temp_file(".json", "{bad")
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_discover_metrics_top_level(self):
        cfg = CalibrationConfig()
        metrics = discover_metrics([{"label": True, "score": 1, "latency_ms": 2}], cfg)
        self.assertIn("score", metrics)
        self.assertNotIn("latency_ms", metrics)

    def test_discover_metrics_nested(self):
        metrics = discover_metrics([{"label": True, "metrics": {"score": "0.4"}}], CalibrationConfig())
        self.assertIn("score", metrics)

    def test_discover_metrics_uses_config(self):
        cfg = config_from_dict({"metrics": {"score": {}}})
        self.assertEqual(list(discover_metrics([], cfg)), ["score"])

    def test_read_metric_value_nested_preferred(self):
        record = {"score": 0.1, "metrics": {"score": 0.9}}
        self.assertEqual(read_metric_value(record, "score"), 0.9)

    def test_read_metric_value_missing(self):
        self.assertIsNone(read_metric_value({}, "score"))


if __name__ == "__main__":
    unittest.main()
