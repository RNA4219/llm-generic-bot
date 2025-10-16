---
sprint: 3
status: completed
updated: 2025-10-14
known_issues: []
---

# Sprint 3 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 確認テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:-------------|
| [x] | OPS-02 | 週次サマリ生成と通知 | `src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/core/orchestrator/processor.py`<br>`src/llm_generic_bot/features/report.py`<br>`src/llm_generic_bot/runtime/setup/__init__.py`<br>`src/llm_generic_bot/runtime/setup/reports.py` | オーケストレータから週次メトリクスを収集し、`processor.py` で Permit 判定・送信記録・メトリクス通知を担いつつ runtime/setup で週次ジョブ登録と Permit 設定を確定。検証: `tests/features/test_report.py::test_weekly_report_formats_real_snapshot`, `tests/integration/runtime_weekly_report/test_scheduler.py::test_weekly_report_respects_weekday_schedule` | runtime/setup でジョブ登録/Permit 設定を実行しつつ、週次ジョブ用通知チャンネルを config サンプルへ反映。 | `tests/features/test_report.py`: 週次集計・通知整形の正常系/欠損フォールバック<br>`tests/integration/runtime_weekly_report/`: runtime/setup の週次ジョブ登録経路 |
| [x] | OPS-03 | 設定再読込ログ強化 | `src/llm_generic_bot/config/loader.py` | `Settings.reload` で設定差分を検出し、差分がある場合にのみ `settings_reload` イベントを構造化ログとして出力する。ログには `previous`・`current`・`diff`（`old`/`new`）を含め、差分が無ければ既存フォーマットを崩さずログを抑制する。 | 設定スナップショットを保持して差分比較する仕組みを明文化。 | `tests/integration/test_runtime_reload.py`: 差分あり/なしのログ出力検証 |
| [x] | OPS-04 | ランタイムメトリクス導入 | `src/llm_generic_bot/infra/metrics/__init__.py`<br>`src/llm_generic_bot/infra/metrics/reporting.py`<br>`src/llm_generic_bot/infra/metrics/service.py`<br>`src/llm_generic_bot/infra/metrics/aggregator.py`<br>`src/llm_generic_bot/infra/metrics/aggregator_state.py`<br>`src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/core/orchestrator/processor.py` | `_GlobalMetricsAggregator` を介して送信成功/失敗・Permit 否認・送信レイテンシを記録し、新しいメトリクスファサード経由で `aggregator.py` がバックエンド集約と履歴管理を担保する。`processor.py` が Permit 判定と送信結果記録をトリガーにメトリクス通知を実行し、バックエンド設定時のみ履歴を保持して週次スナップショットを生成し、`weekly_snapshot` は成功率・レイテンシ分布・Permit 否認のタグを返す。 | オーケストレータがメトリクスファサードを介してバックエンドと同期する現実装に合わせて整理。 | `tests/infra/test_metrics_reporting.py`: ラベル整合と週次スナップショット境界の検証 |
| [x] | OPS-07 | Weather ジョブの複数スケジュール対応 | `src/llm_generic_bot/runtime/jobs/weather.py` | `ScheduledJob` 1 件に複数 `schedules` を集約する。 | `collect_schedules` がリスト/タプル指定を 1 ジョブの `schedules` へ統合する仕様を確定。 | `tests/runtime/test_weather_jobs.py`: 複数時刻を束ねた単一ジョブ生成を検証。 |

## 進行手順
1. ✅ 完了済み: `tests/` に対応テストファイルのスケルトンを追加し、計測対象とログフォーマットを固定済み。
2. `config/settings.example.json` を参照し、週次サマリ用 Permit・通知チャンネル設定の追加差分を設計する。
3. `src/llm_generic_bot/config/loader.py` のリロード経路（必要に応じて `runtime/setup/__init__.py` との連携）を調査し、差分検出ロジックの挿入ポイントを確定する。
4. ✅ 完了済み: `src/llm_generic_bot/core/orchestrator.py`・`src/llm_generic_bot/core/orchestrator/processor.py` と `src/llm_generic_bot/infra/metrics/`（`__init__.py`、`reporting.py`、`service.py`、`aggregator.py`、`aggregator_state.py`）の API 合意を整理し、`aggregator.py` が新ファサード経由で集約と履歴管理を担い、`processor.py` での週次サマリ生成・Permit 判定・メトリクス通知を `reporting.configure_backend` を含む現行ファサードで担保済み。
5. `src/llm_generic_bot/runtime/setup/__init__.py` と `src/llm_generic_bot/runtime/setup/runtime_helpers.py` の連携を調査し、週次レポート登録とランタイム初期化の挙動を把握する。
6. `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲート通過を確認する。

## 準備メモ
- 完了済み: `src/llm_generic_bot/runtime/providers.py` のサンプル実装を確認し、週次サマリ通知で再利用可能な抽象化を把握した。
- 完了済み: `tests/core/test_structured_logging.py` の検証手法を整理し、メトリクス/ログ整合のテストへ適用済み。
- `tests/runtime/test_weather_jobs.py` のケースを精査し、複数スケジュール対応時の `collect_schedules` 仕様を確認する。
