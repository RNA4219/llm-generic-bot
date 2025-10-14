---
sprint: 4
status: planning
updated: 2025-10-14
known_issues:
  - Pending tests for jitter boundary, duplicate skip metrics, failure recoveries
---

# Sprint 4 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:----------------|
| [ ] | OPS-08 | ジッタ境界と Permit 連携テスト追加 | `tests/core/test_scheduler_jitter.py` | ジッタの最小/最大遅延と Permit 判定の相互作用をカバーするテストを先に追加し、必要なら `Scheduler.next_slot` の境界処理を補強する。 | 既存テストはジッタ有無の分岐のみ。境界ケースと Permit 連携は未検証。 | `pytest tests/core/test_scheduler_jitter.py -q` |
| [ ] | OPS-09 | `send_duplicate_skip` ログ/メトリクス検証 | `tests/core/test_structured_logging.py` | Orchestrator の重複スキップ経路で構造化ログとメトリクスタグが一致することをテストから固定し、必要なログ/メトリクス更新を実装する。 | Sprint3 で後回しにしたメトリクス整合性のタスク。 | `pytest tests/core/test_structured_logging.py -q` |
| [ ] | OPS-10 | News/おみくじ/DM 異常系結合テスト | `tests/integration/test_runtime_multicontent_failures.py` | Permit 拒否・クールダウン解除後再送・プロバイダ失敗時のリカバリを再現する結合テストを追加し、必要に応じて実装を調整する。 | Sprint2 残課題を統合テストで解消。既存ファイルと衝突しない新規テストファイルで管理。 | `pytest tests/integration/test_runtime_multicontent_failures.py -q` |

## 進行手順
1. 各タスクのテストケースを先行追加して期待挙動を固定する。
2. テスト失敗を起点に実装を調整し、Permit/メトリクス/異常系の残課題を解消する。
3. `pytest -q`, `mypy src`, `ruff check .` を順に実行して品質ゲートを通過させる。

## 準備メモ
- ジッタ境界検証では PermitGate のモックが必要となる見込み。既存の `tests/core/test_quota_gate.py` を参照してモック方針を合わせる。
- 重複スキップ時のメトリクスタグは `retryable=false`, `status=duplicate` を想定。`infra/metrics/service.py` のタグ命名と整合させる。
- 異常系結合テストでは `config/settings.example.json` のサンプル設定を流用し、Mock プロバイダでエラーシナリオを制御する。
