# eval-threshold-calibrator

离线校准 LLM eval、RAG eval、agent eval 的 pass/fail 阈值，并生成可进入 CI 的 Markdown、JSON、JUnit 报告。

这个项目面向维护 eval 套件的人：你已经有历史 eval 结果、人工标签，也有当前候选模型或提示词的结果；你想知道每个指标应该设在哪里，阈值附近是否稳定，以及这个 gate 会造成多少误杀和漏放。

## 适用场景

- LLM 回答质量 eval：faithfulness、answer relevance、rubric score 等分数阈值校准。
- RAG eval：检索命中、groundedness、引用完整性、生成质量的 per-metric gate。
- Agent eval：任务成功率、工具调用错误率、耗时、成本、token 使用量的辅助分析。
- CI gate：在 pull request 中读取当前候选结果，若未达到推荐阈值则返回非零退出码。
- 离线回放：不依赖外网、不需要真实 token，可在受限 CI 环境运行。

## 安装

Python 3.9+，运行时没有第三方依赖。

```bash
python -m pip install -e .
```

也可以直接在仓库内运行：

```bash
python -m eval_threshold_calibrator --help
```

## 快速开始

```bash
python -m eval_threshold_calibrator \
  --history examples/history.jsonl \
  --current examples/current.jsonl \
  --config examples/config.json \
  --output-md report.md \
  --output-json report.json \
  --output-junit junit.xml \
  --output-policy eval-threshold-policy.json \
  --fail-on-current
```

默认 stdout 输出 Markdown。`--fail-on-current` 开启后，如果当前候选样本通过率低于 `current_min_pass_rate`，CLI 返回退出码 `1`。配置或输入错误返回 `2`。

## Gate Policy 工作流

很多团队不希望每次 PR 都重新扫描历史样本，或者不想把大型历史 eval 数据复制到每个下游仓库。推荐做法是先在有标签历史数据的地方校准一次，把 policy 文件提交进仓库；后续 CI 只用当前候选结果复验。

第一步：校准并导出可评审的 policy。

```bash
eval-threshold-calibrator \
  --history eval/history.jsonl \
  --config eval/calibrator.json \
  --output-md eval/report.md \
  --output-json eval/report.json \
  --output-policy eval/eval-threshold-policy.json
```

第二步：在 PR 或 nightly CI 中复用已提交的 policy。

```bash
eval-threshold-calibrator \
  --policy eval/eval-threshold-policy.json \
  --current eval/current.jsonl \
  --output-json eval/policy-gate.json \
  --output-junit eval/policy-gate.xml \
  --fail-on-current
```

`eval-threshold-policy.v1` 是稳定 JSON schema，包含每个指标的原始阈值、方向、是否必选、校准时 precision/recall/FPR/FNR/F1、稳定区间和全局 `current_min_pass_rate`。这让阈值变化可以像代码一样 code review，也适合 Codex、Claude Code 或其他开发智能体在 CI 中直接读取失败样本。

## 输入格式

支持 JSONL 和 CSV。历史文件必须包含人工 label 字段，默认字段名是 `label`。当前候选文件不需要 label。

JSONL 示例：

```json
{"id":"case-001","label":true,"passed":true,"faithfulness":0.94,"answer_relevance":0.91,"latency_ms":820,"cost_usd":0.012}
```

CSV 示例：

```csv
id,label,passed,faithfulness,answer_relevance,latency_ms,cost_usd
case-001,true,true,0.94,0.91,820,0.012
```

字段说明：

- `label`：人工真值，支持 `true/false`、`pass/fail`、`1/0`、`yes/no`。
- `passed`：已有 gate 的通过失败字段，可用于保留历史上下文；推荐阈值主要由人工 label 与指标扫描得到。
- 指标字段：可以是顶层数值字段，也可以放在 `metrics` object 中。
- 辅助字段：自动识别 `cost_usd`、`latency_ms`、`tokens` 等，也可在配置中声明。

## 配置

配置是 JSON：

```json
{
  "label_field": "label",
  "result_field": "passed",
  "id_field": "id",
  "objective": "f1",
  "stability_tolerance": 0.02,
  "target_precision": 0.8,
  "min_recall": 0.75,
  "current_min_pass_rate": 0.66,
  "metrics": {
    "faithfulness": {"direction": "higher", "min_value": 0, "max_value": 1},
    "latency_ms": {"direction": "lower", "required": false}
  }
}
```

关键选项：

- `objective`：`f1`、`precision`、`recall`、`accuracy`、`balanced_accuracy`。
- `direction`：`higher` 表示越高越好，`lower` 表示越低越好。
- `min_value/max_value`：用于归一化到 0..1；没有配置时仍可扫描原始值。
- `target_precision/min_recall/max_fpr/max_fnr`：阈值约束，可全局配置，也可在单个指标中覆盖。
- `required`：当前候选 gate 是否必须满足该指标。
- `current_min_pass_rate`：当前候选样本的最小通过率。

配置会做严格校验：未知字段、非法方向、非法范围都会返回退出码 `2`。

## 校准方法

每个指标独立校准：

1. 读取历史样本，过滤缺少人工 label 或缺少该指标数值的记录。
2. 按指标方向归一化为“越大越好”。`lower` 指标会反向处理。
3. 扫描所有候选阈值，计算混淆矩阵和 precision、recall、FPR、FNR、F1、accuracy。
4. 先筛选满足约束的阈值，再按目标函数选择最优点。
5. 在 `best_score - stability_tolerance` 内寻找稳定区间，报告区间宽度和候选数。
6. 对成本、延迟、token 等辅助字段计算全量均值、通过样本均值、通过样本总和。

如果没有阈值能满足所有约束，工具会回退到目标函数最优阈值，并在报告中写出警告。

## 输出

Markdown 报告包含摘要、每指标推荐阈值、误杀/漏放权衡、稳定区间、辅助指标、当前候选明细。

JSON 报告适合机器消费，保留扫描点、混淆矩阵、约束结果和当前候选逐条判定。

JUnit XML 适合 GitHub Actions、GitLab CI、Jenkins 等测试报告系统。

Policy JSON 适合提交到仓库，后续用 `--policy --current` 复用阈值。policy gate 模式也能输出 JSON 和 JUnit，方便 CI 保存机器可读报告和测试报告。

## CI 集成

GitHub Actions 示例：

```yaml
name: eval-gate
on: [pull_request]
jobs:
  eval-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install eval-threshold-calibrator
      - run: |
          eval-threshold-calibrator \
            --history eval/history.jsonl \
            --current eval/current.jsonl \
            --config eval/calibrator.json \
            --output-md eval-report.md \
            --output-json eval-report.json \
            --output-junit eval-junit.xml \
            --output-policy eval-threshold-policy.json \
            --fail-on-current
```

如果已经把 policy 提交到仓库，CI 可以更轻：

```yaml
      - run: |
          eval-threshold-calibrator \
            --policy eval/eval-threshold-policy.json \
            --current eval/current.jsonl \
            --output-json eval-policy-gate.json \
            --output-junit eval-policy-gate.xml \
            --fail-on-current
```

本仓库自带 `.github/workflows/ci.yml`，使用 `python -m unittest discover -s tests` 在 Python 3.9 到 3.12 上测试。

## Python API

```python
from eval_threshold_calibrator import CalibrationConfig, MetricConfig, calibrate

history = [
    {"id": "a", "label": True, "faithfulness": 0.9},
    {"id": "b", "label": False, "faithfulness": 0.4},
]
config = CalibrationConfig(metrics={
    "faithfulness": MetricConfig("faithfulness", direction="higher", min_value=0, max_value=1)
})
report = calibrate(history, config)
print(report.metrics["faithfulness"].threshold)
```

## 限制

- 阈值是 per-metric 独立扫描，不做多指标联合优化。
- 小样本历史数据会导致稳定区间偏乐观，应配合人工复核。
- 工具只做离线统计，不调用模型、不访问外网、不管理 eval 运行本身。
- JUnit 输出用于 CI 可视化，不替代完整 Markdown/JSON 报告。

## 开发指南

```bash
python -m pip install -e .
python -m unittest discover -s tests
python -m eval_threshold_calibrator --history examples/history.jsonl --config examples/config.json
```

源码布局：

- `eval_threshold_calibrator/io.py`：JSONL/CSV 读取、配置校验、字段发现。
- `eval_threshold_calibrator/metrics.py`：归一化、阈值扫描、指标计算、稳定区间。
- `eval_threshold_calibrator/calibrator.py`：校准编排和当前候选 gate。
- `eval_threshold_calibrator/policy.py`：已提交 policy 的 schema 校验和当前候选复验。
- `eval_threshold_calibrator/reports.py`：Markdown/JSON/JUnit 输出。
- `eval_threshold_calibrator/cli.py`：命令行入口和退出码。

测试要求：所有新行为都应加入 `tests/`，保持标准库 `unittest` 可直接运行。

## English

`eval-threshold-calibrator` is an offline threshold calibration tool for LLM, RAG, and agent evaluation pipelines. It reads historical eval results, human labels, and optional current candidate results, then recommends per-metric pass/fail thresholds with precision, recall, false-positive rate, false-negative rate, F1, stability intervals, and CI-friendly reports.

### Use Cases

- Calibrate faithfulness, answer relevance, rubric scores, retrieval scores, or agent success metrics.
- Compare false rejects and false accepts before changing a production eval gate.
- Generate Markdown, JSON, and JUnit reports in pull request workflows.
- Run in restricted CI environments without network calls, model tokens, or external runtime dependencies.

### Installation

Python 3.9+ is required. The package has no runtime dependencies.

```bash
python -m pip install -e .
```

### CLI

```bash
eval-threshold-calibrator \
  --history examples/history.jsonl \
  --current examples/current.jsonl \
  --config examples/config.json \
  --output-md report.md \
  --output-json report.json \
  --output-junit junit.xml \
  --output-policy eval-threshold-policy.json \
  --fail-on-current
```

### Gate Policy Workflow

Use a two-step workflow when you want reviewable thresholds and lightweight future CI checks:

```bash
eval-threshold-calibrator \
  --history eval/history.jsonl \
  --config eval/calibrator.json \
  --output-policy eval/eval-threshold-policy.json

eval-threshold-calibrator \
  --policy eval/eval-threshold-policy.json \
  --current eval/current.jsonl \
  --output-json eval/policy-gate.json \
  --output-junit eval/policy-gate.xml \
  --fail-on-current
```

The `eval-threshold-policy.v1` file stores calibrated thresholds, metric directions, required flags, calibration quality metrics, stability intervals, and the required current pass rate. Commit it when you want threshold changes to be code-reviewed and reused by developer agents or CI jobs without replaying historical data.

Exit codes:

- `0`: calibration completed and the current candidate gate passed, or no current gate was requested.
- `1`: calibration completed but `--fail-on-current` was enabled and the current candidate failed.
- `2`: configuration, input, or output error.

### Input Format

JSONL and CSV are supported. Historical records need a human label field, defaulting to `label`. Current records do not need labels. Metrics may be top-level numeric fields or values under a `metrics` object. Boolean labels accept values such as `true/false`, `pass/fail`, `yes/no`, and `1/0`.

### Calibration Method

For each metric, the tool normalizes values so larger is better, scans candidate thresholds, computes confusion-matrix metrics, filters thresholds by configured constraints, selects the best objective score, and reports a stable interval within `best_score - stability_tolerance`. Auxiliary cost, latency, and token fields are summarized for operational tradeoff review.

### API

```python
from eval_threshold_calibrator import CalibrationConfig, MetricConfig, calibrate

report = calibrate(
    [{"id": "a", "label": True, "score": 0.9}, {"id": "b", "label": False, "score": 0.2}],
    CalibrationConfig(metrics={"score": MetricConfig("score")}),
)
```

### CI

Use the JUnit output for CI test reports and `--fail-on-current` for gating. Keep historical labeled data or the generated policy under version control when possible so threshold changes are reviewable.

### Limitations

The current release performs independent per-metric threshold scans rather than joint multi-metric optimization. Small historical datasets can produce fragile recommendations, so teams should review stability intervals and warnings before enforcing strict gates.

### Development

```bash
python -m unittest discover -s tests
```

Contributions should keep the runtime dependency-free and compatible with Python 3.9+.
