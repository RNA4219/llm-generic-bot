---
sprint: 3
status: completed
updated: 2025-10-14
known_issues: []
---

# Sprint 3 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 確認テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:-------------|
| [x] | OPS-02 | 週次サマリ生成と通知 | `src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/features/report.py`<br>`src/llm_generic_bot/runtime/setup/__init__.py`<br>`src/llm_generic_bot/runtime/setup/reports.py` | オーケストレータから週次メトリクスを収集し、runtime/setup で週次ジョブ登録と Permit 設定を確定。検証: `tests/features/test_report.py::test_weekly_report_formats_real_snapshot`, `tests/integration/test_runtime_weekly_report.py::test_weekly_report_respects_weekday_schedule` | runtime/setup でジョブ登録/Permit 設定を実行しつつ、週次ジョブ用通知チャンネルを config サンプルへ反映。 | `tests/features/test_report.py`: 週次集計・通知整形の正常系/欠損フォールバック<br>`tests/integration/test_runtime_weekly_report.py`: runtime/setup の週次ジョブ登録経路 |
| [x] | OPS-03 | 設定再読込ログ強化 | `src/llm_generic_bot/config/loader.py`<br>`src/llm_generic_bot/runtime/setup/__init__.py` | `Settings.reload` で設定ファイルの差分を検出し、`settings_reload` イベントとして `previous`・`current`・`diff`（`old`/`new` のペイロード）を含む構造化ログを出力する。検証: `tests/integration/test_runtime_reload.py::test_settings_reload_logs_diff`, `tests/integration/test_runtime_reload.py::test_settings_reload_skips_log_when_no_diff` | 差分検知とログ出力は JSON 構造を維持し、差分なしの場合はロギングを抑制する現行実装を踏襲する。 | `tests/integration/test_runtime_reload.py`: リロード時の差分検出とロギング |
| [x] | OPS-04 | ランタイムメトリクス導入 | `src/llm_generic_bot/infra/metrics/__init__.py`<br>`src/llm_generic_bot/infra/metrics/service.py`<br>`src/llm_generic_bot/core/orchestrator.py` | Scheduler 遅延/送信成功率など主要メトリクスを集計し、既存ロガーと連携。検証: `tests/infra/test_metrics_reporting.py::test_metrics_records_expected_labels_and_snapshot`, `tests/infra/test_metrics_reporting.py::test_metrics_weekly_snapshot_latency_boundaries` | 既存メトリクス API を汚染しないファサードを用意し、Permit ゲートと整合。 | `tests/infra/test_metrics_reporting.py`: メトリクス収集・ラベル整合のスナップショット |
| [x] | OPS-07 | Weather ジョブの複数スケジュール対応 | `src/llm_generic_bot/runtime/jobs/weather.py` | `ScheduledJob` 1 件に複数 `schedules` を集約する。 | `collect_schedules` がリスト/タプル指定を 1 ジョブの `schedules` へ統合する仕様を確定。 | `tests/runtime/test_weather_jobs.py`: 複数時刻を束ねた単一ジョブ生成を検証。 |

## 進行手順
1. ✅ 完了済み: `tests/` に対応テストファイルのスケルトンを追加し、計測対象とログフォーマットを固定済み。
2. `config/settings.example.json` を参照し、週次サマリ用 Permit・通知チャンネル設定の追加差分を設計する。
3. `src/llm_generic_bot/runtime/setup/__init__.py` と `src/llm_generic_bot/runtime/setup/runtime_helpers.py` の連携を調査し、週次レポート登録とランタイム初期化の挙動を把握する。
4. ✅ 完了済み: `src/llm_generic_bot/core/orchestrator.py` と `infra/metrics.py` の API 合意を整理し、メトリクス配信とログの整合を担保済み。
5. `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲート通過を確認する。

## 準備メモ
- 完了済み: `src/llm_generic_bot/runtime/providers.py` のサンプル実装を確認し、週次サマリ通知で再利用可能な抽象化を把握した。
- 完了済み: `tests/core/test_structured_logging.py` の検証手法を整理し、メトリクス/ログ整合のテストへ適用済み。
- `tests/runtime/test_weather_jobs.py` のケースを精査し、複数スケジュール対応時の `collect_schedules` 仕様を確認する。
