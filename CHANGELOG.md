# Changelog

## 0.2.0 - 2026-06-09

### 中文

- 新增 `eval-threshold-policy.v1` gate policy 导出，可把校准后的阈值提交到仓库中评审和复用。
- 新增 `--policy --current` 校验模式，后续 CI 可只读取当前候选 eval 结果，不再依赖历史样本文件。
- 新增 policy gate JSON 与 JUnit 输出，便于 GitHub Actions、GitLab CI、Jenkins 展示失败样本。
- 加强 policy schema 校验，覆盖阈值数值、必选指标布尔值、通过率范围等错误输入。
- CI 增加 policy 导出与复用烟测。

### English

- Added `eval-threshold-policy.v1` exports so calibrated gates can be committed, reviewed, and reused.
- Added `--policy --current` mode for future CI runs that only need current candidate eval records.
- Added policy gate JSON and JUnit outputs for CI report surfaces.
- Tightened policy schema validation for numeric thresholds, boolean required flags, and pass-rate bounds.
- Added CI smoke coverage for policy export and policy reuse.

## 0.1.0 - 2026-06-08

### 中文

- 首个公开版本：离线校准 LLM/RAG/agent eval 的 per-metric 阈值。
- 支持 JSONL/CSV 输入、Markdown/JSON/JUnit 输出、当前候选 gate、辅助成本和延迟指标汇总。

### English

- Initial public release for offline per-metric threshold calibration across LLM, RAG, and agent evals.
- Supported JSONL/CSV inputs, Markdown/JSON/JUnit outputs, current-candidate gates, and auxiliary cost/latency summaries.
