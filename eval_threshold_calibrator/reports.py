from __future__ import annotations

import html
from typing import List

from .models import CalibrationReport
from .serialization import to_json
from .utils import fmt_float


def render_json(report: CalibrationReport) -> str:
    return to_json(report)


def render_markdown(report: CalibrationReport) -> str:
    lines: List[str] = []
    lines.append("# Eval Threshold Calibrator 报告")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- 历史样本: {report.history_count}")
    lines.append(f"- 人工正例: {report.positive_count}")
    lines.append(f"- 人工负例: {report.negative_count}")
    if report.current:
        lines.append(f"- 当前候选: {report.current.passed}/{report.current.total} 通过，pass_rate={report.current.pass_rate:.4f}")
        lines.append(f"- CI gate: {'PASS' if report.current.gate_passed else 'FAIL'}")
    if report.existing_gate:
        gate = report.existing_gate
        lines.append(
            f"- 历史已有 gate: precision={gate.precision:.4f}, recall={gate.recall:.4f}, "
            f"FPR={gate.fpr:.4f}, FNR={gate.fnr:.4f}, F1={gate.f1:.4f}"
        )
    if report.warnings:
        lines.append("")
        lines.append("## 警告")
        lines.append("")
        for warning in report.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("## 指标阈值建议")
    lines.append("")
    lines.append("| 指标 | 方向 | 推荐阈值 | 稳定区间 | Precision | Recall | FPR | FNR | F1 | 接受率 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for metric in report.metrics.values():
        best = metric.best
        stable = metric.stable_interval
        lines.append(
            "| "
            + " | ".join(
                [
                    metric.name,
                    metric.direction,
                    fmt_float(metric.threshold),
                    f"{fmt_float(stable.raw_low)}..{fmt_float(stable.raw_high)}",
                    f"{best.precision:.4f}",
                    f"{best.recall:.4f}",
                    f"{best.fpr:.4f}",
                    f"{best.fnr:.4f}",
                    f"{best.f1:.4f}",
                    f"{best.acceptance_rate:.4f}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 推荐解释")
    lines.append("")
    for metric in report.metrics.values():
        lines.append(f"### {metric.name}")
        lines.append("")
        lines.append(metric.reason)
        if metric.best.auxiliaries:
            lines.append("")
            lines.append("| 辅助指标 | 值 |")
            lines.append("| --- | ---: |")
            for name, value in sorted(metric.best.auxiliaries.items()):
                lines.append(f"| {name} | {fmt_float(value)} |")
        if metric.warnings:
            lines.append("")
            for warning in metric.warnings:
                lines.append(f"- {warning}")
        lines.append("")

    if report.current:
        lines.append("## 当前候选明细")
        lines.append("")
        lines.append("| ID | 结果 | 失败/缺失指标 |")
        lines.append("| --- | --- | --- |")
        for decision in report.current.decisions:
            failed = [name for name, ok in decision.metric_passed.items() if not ok]
            failed.extend([f"{name}(missing)" for name in decision.missing_metrics if name not in failed])
            lines.append(f"| {decision.record_id} | {'PASS' if decision.passed else 'FAIL'} | {', '.join(failed) or '-'} |")
        lines.append("")
    return "\n".join(lines)


def render_junit(report: CalibrationReport, suite_name: str = "eval-threshold-calibrator") -> str:
    tests = []
    failures = 0
    for metric in report.metrics.values():
        tests.append((f"metric.{metric.name}", True, metric.reason))
    if report.current:
        for decision in report.current.decisions:
            ok = decision.passed
            if not ok:
                failures += 1
            message = ", ".join([name for name, passed in decision.metric_passed.items() if not passed])
            tests.append((f"current.{decision.record_id}", ok, message or "passed"))
    xml = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuite name="{html.escape(suite_name)}" tests="{len(tests)}" failures="{failures}">',
    ]
    for name, ok, message in tests:
        xml.append(f'  <testcase name="{html.escape(name)}">')
        if not ok:
            xml.append(f'    <failure message="{html.escape(message)}">{html.escape(message)}</failure>')
        xml.append("  </testcase>")
    xml.append("</testsuite>")
    return "\n".join(xml) + "\n"
