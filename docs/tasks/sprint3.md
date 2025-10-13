---
sprint: 3
status: planned
updated: 2025-10-20
known_issues: []
---

# Sprint 3 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 確認テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:-------------|
| [ ] | OPS-02 | 週次サマリ生成と通知 | `src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/features/report.py` | オーケストレータから週次メトリクスを収集し、Report Feature が通知フォーマットを生成。Permit/送信層に影響しない。 | 週次ジョブ用 Permit 設定と通知チャンネルを config サンプルへ反映。 | `tests/features/test_report.py`: 週次集計・通知整形の正常系/欠損フォールバック |
| [ ] | OPS-03 | 設定再読込ログ強化 | `src/llm_generic_bot/runtime/setup.py`<br>`config/` | 設定リロード時に差分検出を行い、監査ログへ差分サマリを構造化出力。 | 既存 CLI/API に互換な JSON ログを維持しつつ、差分イベントを追加。 | `tests/integration/test_runtime_reload.py`: リロード時の差分検出とロギング |
| [ ] | OPS-04 | ランタイムメトリクス導入 | `src/llm_generic_bot/infra/metrics.py`<br>`src/llm_generic_bot/core/orchestrator.py` | Scheduler 遅延/送信成功率など主要メトリクスを集計し、既存ロガーと連携。 | 既存メトリクス API を汚染しないファサードを用意し、Permit ゲートと整合。 | `tests/infra/test_metrics_reporting.py`: メトリクス収集・ラベル整合のスナップショット |

## 進行手順
1. `tests/` に対応テストファイルのスケルトンを追加し、計測対象とログフォーマットを固定する。
2. `config/settings.example.json` を参照し、週次サマリ用 Permit・通知チャンネル設定の追加差分を設計する。
3. `src/llm_generic_bot/runtime/setup.py` のリロード経路を調査し、差分検出ロジックの挿入ポイントを確定する。
4. `src/llm_generic_bot/core/orchestrator.py` と新設予定の `infra/metrics.py` の API 合意を整理し、メトリクス配信とログの整合を担保する。
5. `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲート通過を確認する。

## 準備メモ
- `src/llm_generic_bot/runtime/providers.py` のサンプル実装を参照し、週次サマリ通知で再利用可能な抽象化を把握する。
- `tests/core/test_structured_logging.py` を読み、メトリクス/ログ整合の既存検証手法を流用する。
- `config/` 配下のサンプル設定と `tests/integration/test_runtime_multicontent.py` の期待値を比較し、追加ジョブによる副作用を洗い出す。
