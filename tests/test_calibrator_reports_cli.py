import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from eval_threshold_calibrator.calibrator import calibrate, evaluate_current
from eval_threshold_calibrator.cli import main
from eval_threshold_calibrator.errors import ConfigError, InputError
from eval_threshold_calibrator.io import config_from_dict
from eval_threshold_calibrator.models import CalibrationConfig, MetricConfig
from eval_threshold_calibrator.policy import evaluate_current_with_policy, validate_policy
from eval_threshold_calibrator.reports import render_junit, render_json, render_markdown, render_policy_json


class CalibratorReportCliTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"id": "a", "label": True, "score": 0.95, "quality": 0.9, "cost_usd": 1},
            {"id": "b", "label": True, "score": 0.82, "quality": 0.8, "cost_usd": 2},
            {"id": "c", "label": False, "score": 0.45, "quality": 0.4, "cost_usd": 3},
            {"id": "d", "label": False, "score": 0.2, "quality": 0.3, "cost_usd": 4},
        ]
        self.cfg = CalibrationConfig(metrics={"score": MetricConfig("score", min_value=0, max_value=1)})

    def temp_file(self, suffix, content=""):
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False)
        self.addCleanup(lambda: os.path.exists(fh.name) and os.unlink(fh.name))
        with fh:
            fh.write(content)
        return fh.name

    def test_calibrate_basic(self):
        report = calibrate(self.history, self.cfg)
        self.assertIn("score", report.metrics)
        self.assertEqual(report.positive_count, 2)
        self.assertEqual(report.negative_count, 2)

    def test_calibrate_discovers_metrics(self):
        report = calibrate(self.history, CalibrationConfig())
        self.assertIn("score", report.metrics)
        self.assertIn("quality", report.metrics)

    def test_calibrate_requires_labels(self):
        with self.assertRaises(InputError):
            calibrate([{"score": 1}], self.cfg)

    def test_calibrate_requires_metrics(self):
        with self.assertRaises(InputError):
            calibrate([{"label": True}], CalibrationConfig())

    def test_calibrate_warns_skipped_labels(self):
        report = calibrate(self.history + [{"id": "x", "label": "?", "score": 1}], self.cfg)
        self.assertTrue(report.warnings)

    def test_evaluate_current_passes(self):
        report = calibrate(self.history, self.cfg, [{"id": "new", "score": 0.9}])
        self.assertTrue(report.current.gate_passed)
        self.assertEqual(report.current.passed, 1)

    def test_evaluate_current_fails_low_score(self):
        report = calibrate(self.history, self.cfg, [{"id": "new", "score": 0.1}])
        self.assertFalse(report.current.gate_passed)
        self.assertEqual(report.current.failed, 1)

    def test_evaluate_current_missing_metric(self):
        metric_reports = calibrate(self.history, self.cfg).metrics
        current = evaluate_current([{"id": "new"}], self.cfg, metric_reports)
        self.assertFalse(current.decisions[0].passed)
        self.assertEqual(current.decisions[0].missing_metrics, ["score"])

    def test_optional_metric_not_required_for_current(self):
        cfg = CalibrationConfig(metrics={"score": MetricConfig("score", required=False)})
        report = calibrate(self.history, cfg, [{"id": "new"}])
        self.assertTrue(report.current.decisions[0].passed)

    def test_current_min_pass_rate(self):
        cfg = CalibrationConfig(metrics={"score": MetricConfig("score")}, current_min_pass_rate=0.5)
        report = calibrate(self.history, cfg, [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.1}])
        self.assertTrue(report.current.gate_passed)

    def test_render_markdown(self):
        md = render_markdown(calibrate(self.history, self.cfg, [{"id": "new", "score": 0.9}]))
        self.assertIn("指标阈值建议", md)
        self.assertIn("score", md)
        self.assertIn("当前候选明细", md)

    def test_render_json(self):
        data = json.loads(render_json(calibrate(self.history, self.cfg)))
        self.assertIn("metrics", data)
        self.assertIn("score", data["metrics"])

    def test_render_policy_json_contains_gate_thresholds(self):
        data = json.loads(render_policy_json(calibrate(self.history, self.cfg)))

        self.assertEqual(data["schema_version"], "eval-threshold-policy.v1")
        self.assertIn("score", data["metrics"])
        self.assertIn("threshold", data["metrics"]["score"])
        self.assertEqual(data["metrics"]["score"]["direction"], "higher")

    def test_policy_evaluates_lower_direction(self):
        cfg = config_from_dict({"metrics": {"latency": {"direction": "lower"}}})
        report = calibrate(
            [{"label": True, "latency": 10}, {"label": False, "latency": 90}],
            cfg,
        )
        policy = json.loads(render_policy_json(report))
        gate = evaluate_current_with_policy([{"id": "fast", "latency": 5}], policy)

        self.assertTrue(gate.gate_passed)
        self.assertTrue(gate.decisions[0].passed)

    def test_policy_requires_boolean_required(self):
        policy = json.loads(render_policy_json(calibrate(self.history, self.cfg)))
        policy["metrics"]["score"]["required"] = 1

        with self.assertRaises(ConfigError):
            validate_policy(policy)

    def test_render_junit(self):
        xml = render_junit(calibrate(self.history, self.cfg, [{"id": "bad", "score": 0.1}]))
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "testsuite")
        self.assertEqual(root.attrib["failures"], "1")

    def test_cli_markdown_success(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--history", history])
        self.assertEqual(code, 0)
        self.assertIn("报告", out.getvalue())

    def test_cli_json_stdout(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--history", history, "--stdout", "json"])
        self.assertEqual(code, 0)
        self.assertIn('"metrics"', out.getvalue())

    def test_cli_junit_stdout(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--history", history, "--stdout", "junit"])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("<?xml"))

    def test_cli_writes_outputs(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        md = self.temp_file(".md")
        js = self.temp_file(".json")
        junit = self.temp_file(".xml")
        policy = self.temp_file(".json")
        with redirect_stdout(StringIO()):
            code = main(
                [
                    "--history",
                    history,
                    "--output-md",
                    md,
                    "--output-json",
                    js,
                    "--output-junit",
                    junit,
                    "--output-policy",
                    policy,
                ]
            )
        self.assertEqual(code, 0)
        self.assertGreater(os.path.getsize(md), 0)
        self.assertGreater(os.path.getsize(js), 0)
        self.assertGreater(os.path.getsize(junit), 0)
        with open(policy, encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.read())["schema_version"], "eval-threshold-policy.v1")

    def test_cli_creates_output_directories(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        nested = os.path.join(tempfile.gettempdir(), "eval-threshold-calibrator-test", "nested", "report.json")
        if os.path.exists(nested):
            os.unlink(nested)
        with redirect_stdout(StringIO()):
            code = main(["--history", history, "--output-json", nested])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(nested))
        os.unlink(nested)

    def test_cli_fail_on_current(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        current = self.temp_file(".jsonl", json.dumps({"id": "bad", "score": 0.1}) + "\n")
        with redirect_stdout(StringIO()):
            code = main(["--history", history, "--current", current, "--fail-on-current"])
        self.assertEqual(code, 1)

    def test_cli_config_file(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        config = self.temp_file(".json", json.dumps({"objective": "precision", "metrics": {"score": {}}}))
        with redirect_stdout(StringIO()):
            code = main(["--history", history, "--config", config])
        self.assertEqual(code, 0)

    def test_cli_bad_input_returns_2(self):
        err = StringIO()
        with redirect_stderr(err):
            code = main(["--history", "missing.jsonl"])
        self.assertEqual(code, 2)
        self.assertIn("error:", err.getvalue())

    def test_cli_current_min_pass_rate_override(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        current = self.temp_file(".jsonl", json.dumps({"id": "bad", "score": 0.1}) + "\n")
        with redirect_stdout(StringIO()):
            code = main(["--history", history, "--current", current, "--fail-on-current", "--current-min-pass-rate", "0"])
        self.assertEqual(code, 0)

    def test_cli_policy_gate_passes_current(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        config = self.temp_file(".json", json.dumps({"metrics": {"score": {}}}))
        policy = self.temp_file(".json")
        current = self.temp_file(".jsonl", json.dumps({"id": "ok", "score": 0.9}) + "\n")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--history", history, "--config", config, "--output-policy", policy]), 0)

        out = StringIO()
        with redirect_stdout(out):
            code = main(["--policy", policy, "--current", current, "--stdout", "json", "--fail-on-current"])

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["current"]["gate_passed"])

    def test_cli_policy_gate_fails_current(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        policy = self.temp_file(".json")
        current = self.temp_file(".jsonl", json.dumps({"id": "bad", "score": 0.1}) + "\n")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--history", history, "--output-policy", policy]), 0)

        with redirect_stdout(StringIO()):
            code = main(["--policy", policy, "--current", current, "--fail-on-current"])

        self.assertEqual(code, 1)

    def test_cli_policy_current_min_pass_rate_override(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        policy = self.temp_file(".json")
        current = self.temp_file(".jsonl", json.dumps({"id": "bad", "score": 0.1}) + "\n")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--history", history, "--output-policy", policy]), 0)
        with redirect_stdout(StringIO()):
            code = main(["--policy", policy, "--current", current, "--fail-on-current", "--current-min-pass-rate", "0"])

        self.assertEqual(code, 0)

    def test_cli_policy_gate_writes_junit(self):
        history = self.temp_file(".jsonl", "\n".join(json.dumps(r) for r in self.history))
        policy = self.temp_file(".json")
        junit = self.temp_file(".xml")
        current = self.temp_file(".jsonl", json.dumps({"id": "bad&case", "score": 0.1}) + "\n")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--history", history, "--output-policy", policy]), 0)
        with redirect_stdout(StringIO()):
            code = main(["--policy", policy, "--current", current, "--output-junit", junit, "--stdout", "junit"])

        self.assertEqual(code, 0)
        root = ET.parse(junit).getroot()
        self.assertEqual(root.attrib["failures"], "1")
        self.assertEqual(root.find("testcase").attrib["name"], "bad&case")

    def test_cli_csv_history(self):
        history = self.temp_file(".csv", "id,label,score\na,true,0.9\nb,false,0.1\n")
        with redirect_stdout(StringIO()):
            code = main(["--history", history])
        self.assertEqual(code, 0)

    def test_markdown_includes_warnings(self):
        report = calibrate(self.history + [{"label": "?"}], self.cfg)
        self.assertIn("警告", render_markdown(report))

    def test_json_contains_current_gate(self):
        report = calibrate(self.history, self.cfg, [{"id": "new", "score": 0.9}])
        data = json.loads(render_json(report))
        self.assertTrue(data["current"]["gate_passed"])

    def test_junit_no_current_has_metric_testcases(self):
        xml = render_junit(calibrate(self.history, self.cfg))
        self.assertIn("metric.score", xml)

    def test_nested_metric_current(self):
        history = [{"label": True, "metrics": {"score": 0.9}}, {"label": False, "metrics": {"score": 0.1}}]
        report = calibrate(history, CalibrationConfig(), [{"id": "n", "metrics": {"score": 0.95}}])
        self.assertTrue(report.current.decisions[0].passed)

    def test_lower_direction_current(self):
        cfg = config_from_dict({"metrics": {"latency": {"direction": "lower"}}})
        history = [{"label": True, "latency": 10}, {"label": False, "latency": 90}]
        report = calibrate(history, cfg, [{"id": "n", "latency": 5}])
        self.assertTrue(report.current.decisions[0].passed)

    def test_multi_metric_current_fails_one(self):
        cfg = config_from_dict({"metrics": {"score": {}, "quality": {}}})
        report = calibrate(self.history, cfg, [{"id": "n", "score": 0.9, "quality": 0.1}])
        self.assertFalse(report.current.decisions[0].passed)

    def test_metric_threshold_from_config_does_not_break(self):
        cfg = config_from_dict({"metrics": {"score": {"threshold": 0.5}}})
        report = calibrate(self.history, cfg)
        self.assertIn("score", report.metrics)


if __name__ == "__main__":
    unittest.main()
