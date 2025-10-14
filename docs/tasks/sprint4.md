---
sprint: 4
status: completed
updated: 2025-10-14
known_issues: []
---

# Sprint 4 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:----------------|
| [x] | OPS-08 | ジッタ境界と Permit 連携テスト追加 | `tests/core/test_scheduler_jitter.py` | ジッタの最小/最大遅延と Permit 判定の相互作用をカバーするテストを先に追加し、必要なら `Scheduler.next_slot` の境界処理を補強する。 | `test_scheduler_jitter_respects_range` ほか境界ケースを追加し、Permit 連携を `pytest tests/core/test_scheduler_jitter.py::test_scheduler_jitter_respects_range -q` で確認済み。 | ✅ `pytest tests/core/test_scheduler_jitter.py -q` |
| [x] | OPS-09 | `send_duplicate_skip` ログ/メトリクス検証 | `tests/core/test_structured_logging.py` | Orchestrator の重複スキップ経路で構造化ログとメトリクスタグが一致することをテストから固定し、必要なログ/メトリクス更新を実装する。 | `test_orchestrator_logs_duplicate_skip` が `send_duplicate_skip` のログ/タグ整合を固定し、`metrics.last_tags` を `pytest tests/core/test_structured_logging.py::test_orchestrator_logs_duplicate_skip -q` で検証済み。 | ✅ `pytest tests/core/test_structured_logging.py -q` |
| [x] | OPS-10 | News/おみくじ/DM 異常系結合テスト | `tests/integration/test_runtime_multicontent_failures.py` | Permit 拒否・クールダウン解除後再送・プロバイダ失敗時のリカバリを再現する結合テストを追加し、必要に応じて実装を調整する。 | `test_permit_denied_records_metrics`・`test_cooldown_resume_allows_retry`・`test_summary_provider_retry_and_fallback` ほかを追加し、`pytest tests/integration/test_runtime_multicontent_failures.py -q` で統合検証済み。 | ✅ `pytest tests/integration/test_runtime_multicontent_failures.py -q` |

## 進行手順
1. ✅ 完了済み: 各タスクのテストケースを追加し、`tests/core/test_scheduler_jitter.py`・`tests/core/test_structured_logging.py`・`tests/integration/test_runtime_multicontent_failures.py` で期待挙動を固定済み。
2. ✅ 完了済み: テストドリブンで Permit/メトリクス/異常系の残課題を実装し、対応テストがすべてパスしている。
3. ✅ 完了済み: `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲートを通過した。

## 準備メモ
- 完了済み: ジッタ境界検証では PermitGate のモック方針を `tests/core/test_scheduler_jitter.py::test_scheduler_jitter_respects_range` で確立した。
- 完了済み: 重複スキップ時のメトリクスタグを `tests/core/test_structured_logging.py::test_orchestrator_logs_duplicate_skip` で `retryable=false`・`status=duplicate` として固定した。
- 完了済み: 異常系結合テストは `tests/integration/test_runtime_multicontent_failures.py` で `config/settings.example.json` を参照し、モックプロバイダによるエラー制御を実証した。
