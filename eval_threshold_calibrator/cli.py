from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .calibrator import calibrate
from .errors import CalibrationError
from .io import load_config, read_records
from .policy import evaluate_current_with_policy, load_policy
from .reports import render_junit, render_json, render_markdown, render_policy_json
from .serialization import to_json


def render_policy_gate_junit(gate, suite_name: str = "eval-threshold-policy") -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuite name="{html.escape(suite_name)}" tests="{gate.total}" failures="{gate.failed}">',
    ]
    for decision in gate.decisions:
        lines.append(f'  <testcase name="{html.escape(decision.record_id)}">')
        if not decision.passed:
            failed = ", ".join(name for name, ok in decision.metric_passed.items() if not ok)
            failed_xml = html.escape(failed)
            lines.append(f'    <failure message="{failed_xml}">{failed_xml}</failure>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval-threshold-calibrator",
        description="离线校准 LLM/RAG/agent eval 的 pass/fail 阈值，并输出 CI gate 报告。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--history", help="历史 eval 结果，支持 .jsonl/.csv，必须包含人工 label")
    parser.add_argument("--current", help="当前候选 eval 结果，支持 .jsonl/.csv")
    parser.add_argument("--config", help="JSON 配置文件")
    parser.add_argument("--policy", help="已提交的 gate policy JSON；搭配 --current 可直接校验候选结果")
    parser.add_argument("--output-md", help="写出 Markdown 报告")
    parser.add_argument("--output-json", help="写出 JSON 报告")
    parser.add_argument("--output-junit", help="写出 JUnit XML 报告")
    parser.add_argument("--output-policy", help="写出可提交到仓库的 gate policy JSON")
    parser.add_argument("--stdout", choices=["markdown", "json", "junit", "policy"], default="markdown", help="stdout 输出格式")
    parser.add_argument("--fail-on-current", action="store_true", help="当前候选未达到 gate 时返回退出码 1")
    parser.add_argument("--current-min-pass-rate", type=float, help="当前候选最小通过率，默认来自配置或 1.0")
    return parser


def write_text(path: Optional[str], content: str) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.policy:
            if not args.current:
                parser.error("--policy 需要搭配 --current")
            policy = load_policy(args.policy)
            if args.current_min_pass_rate is not None:
                policy = dict(policy)
                policy["current_min_pass_rate"] = args.current_min_pass_rate
            current = read_records(args.current)
            gate = evaluate_current_with_policy(current, policy)
            output = to_json({"schema_version": "eval-threshold-policy-gate.v1", "current": gate})
            junit = render_policy_gate_junit(gate)
            write_text(args.output_json, output)
            write_text(args.output_junit, junit)
            if args.stdout == "junit":
                print(junit, end="")
            else:
                print(output)
            if args.fail_on_current and not gate.gate_passed:
                return 1
            return 0

        if not args.history:
            parser.error("--history 是必填项，除非使用 --policy --current")
        cfg = load_config(args.config)
        if args.fail_on_current:
            cfg.fail_on_current = True
        if args.current_min_pass_rate is not None:
            cfg.current_min_pass_rate = args.current_min_pass_rate
        history = read_records(args.history)
        current = read_records(args.current) if args.current else None
        report = calibrate(history, cfg, current)
        markdown = render_markdown(report)
        json_report = render_json(report)
        junit = render_junit(report)
        policy = render_policy_json(report)
        write_text(args.output_md, markdown)
        write_text(args.output_json, json_report)
        write_text(args.output_junit, junit)
        write_text(args.output_policy, policy)
        if args.stdout == "json":
            print(json_report)
        elif args.stdout == "junit":
            print(junit, end="")
        elif args.stdout == "policy":
            print(policy, end="")
        else:
            print(markdown)
        if cfg.fail_on_current and report.current and not report.current.gate_passed:
            return 1
        return 0
    except CalibrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: 写文件失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
