---
category: backlog
status: in_progress
updated: 2025-10-29
---

# 残課題バックログ

| 状態 | ID | 要約 | 対象領域 | 完了条件 | 備考 | 先行着手タスク |
|:----:|:---|:-----|:---------|:---------|:-----|:----------------|
| [ ] | OPS-B01 | Permit/ジッタ/バッチ閾値の運用チューニング | `config/settings.example.json` 系列<br>`src/llm_generic_bot/core/scheduler.py`<br>`src/llm_generic_bot/core/arbiter.py` | テストを先に追加し、Permit/ジッタ/バッチ閾値を調整しても `pytest tests/integration/test_runtime_multicontent_failures.py -q` がグリーンであること、および遅延・Permit 通過率が期待値内に収束するメトリクス検証を `tests/infra/` 配下に追加する。 | ロードマップ「残課題」から OPS-B01 に明記。具体的な閾値とモニタリング条件を決定し、設定ファイルに反映する。 | [OPS-08] ジッタ境界テスト済み。 |
| [ ] | OPS-B02 | Permit 失敗時の再評価フロー整備 | `src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/core/orchestrator/processor.py`<br>`src/llm_generic_bot/core/orchestrator_metrics.py` (メトリクス境界更新時の参照先)<br>`src/llm_generic_bot/core/arbiter.py`<br>`tests/integration/` | Permit 拒否後の再評価タイミングをテストで固定し、再評価時にメトリクス/ログへ再試行理由を記録する。`pytest tests/integration/test_runtime_multicontent_failures.py -k permit -q` を新テストと併せてグリーン化する。 | PermitGate のレート制御と重複スキップの両立を確認するため、再評価待ちキューや通知ダッシュボード更新も含めて検証する。 | [OPS-10] Permit 拒否メトリクス取得済み。 |
| [ ] | OPS-B03 | Permit クォータ多段構成とバッチ再送ガード | `src/llm_generic_bot/core/arbiter.py`<br>`src/llm_generic_bot/core/queue.py`<br>`tests/core/` | 多段クォータを導入するテストを先に追加し、再送ガードが二重送信を防ぎつつ `pytest tests/core/test_quota_gate.py -q` を拡張テストと共にグリーン化する。 | スケジューラ併合と連携し、閾値超過時のバッチ破棄・遅延再送の境界条件を明示する。 | Sprint1 [SND-02] 残課題を引継ぎ。 |
| [ ] | OPS-B04 | `tests/infra/test_metrics_reporting.py` の段階的廃止 | `tests/infra/metrics/`<br>`docs/roadmap.md`<br>`docs/tasks/backlog.md` | 1. `tests/infra/metrics/*` への参照整理が完了し、旧 `tests/infra/test_metrics_reporting.py` への依存が残存しないことをリポジトリ全体で確認する。<br>2. CI (`pytest`, `mypy`, `ruff`) をグリーン化し、`tests/infra/metrics/` 経由のレポート統合が回帰しないことを保証する。<br>3. バックログおよび関連ドキュメントから旧パスの言及を更新し、移行完了手順を共有する。 | metrics レポート統合の移行完了までは旧テストファイルを削除しない。 | 2025-10-23: 本行追加。 |
| [ ] | OPS-B05 | `tests/infra/test_metrics_reporting.py` 撤去前チェック | `tests/infra/metrics/`<br>`tests/infra/test_metrics_reporting.py`<br>`docs/` 全般 | 1. `tests/infra/metrics/*` の参照状況を確認し、旧テストファイルへの残存参照がないことを `rg` などで証明する。<br>2. `pytest`, `mypy`, `ruff` を通過させ、メトリクス報告経路が `tests/infra/metrics/*` のみで成立することを確認する。<br>3. バックログ・ロードマップ・関連ガイドから旧テストファイルの言及を更新し、撤去手順完了を文書化する。 | OPS-B04 の作業完了後に削除フラグを立て、段階的撤去へ移行する。 | OPS-B04 |
| [ ] | OPS-B07 | `tests/infra/test_metrics_reporting.py` 本削除 | `tests/infra/test_metrics_reporting.py`<br>`tests/infra/metrics/`<br>`docs/` 全般 | 1. `tests/infra/test_metrics_reporting.py` を削除し、Git 履歴でも撤去完了とする。<br>2. `rg` などで旧ファイル名・パスの残存参照がないことを最終確認し、結果を記録する。<br>3. CI (`pytest`, `mypy`, `ruff`) を全てグリーン化し、メトリクス報告が回帰していないことを証明する。<br>4. バックログと関連ドキュメントを更新し、撤去完了と移行手順の最終版を共有する。 | 2025-10-28: 本行更新（最終更新日同期）。 | OPS-B05 |
| [ ] | OPS-B06 | `core/orchestrator/__init__.py` レガシーシム撤去 | `src/llm_generic_bot/core/orchestrator/__init__.py`<br>`tests/core/orchestrator*`<br>`tests/integration/*` | 1. 既存の直 import を新パスへ全て置換し、再輸出シムを廃止する。<br>2. `tests/core/orchestrator*` と `tests/integration/*` の参照を新パスへ更新し、必要なテストを先に追加して挙動を固定する。<br>3. CI (`pytest`, `mypy`, `ruff`) をグリーン化し、撤去後の回帰がないことを確認する。<br>4. バックログおよび関連ドキュメントへ移行完了手順と更新内容を反映する。 | 段階的削除と互換維持を優先し、削除前に影響範囲のテストを拡充する。 | OPS-B02 |
| [ ] | UX-B01 | Engagement 指標の長期トレンド分析と調整方針 | `src/llm_generic_bot/features/weather.py`<br>`src/llm_generic_bot/core/orchestrator.py`<br>`src/llm_generic_bot/core/orchestrator/processor.py`<br>`src/llm_generic_bot/core/orchestrator_metrics.py` (メトリクス境界更新時の参照先)<br>`tests/features/` | Engagement ログを一定期間蓄積するテストダブルを用意し、Permit クォータ変動時の通知頻度を調整するロジックを `pytest tests/features/test_weather_engagement.py -q` の新ケースで固定する。 | Sprint2 「残課題」から移管。トレンドに応じた通知頻度調整と PermitGate の協調方針を定義する。 | [UX-01] Engagement 反映ロジック実装済み。 |

## 進行手順
1. 各残課題について、テストケースを先に作成し現状挙動を固定する。
2. テスト結果をもとに設定値やフローを調整し、`pytest`, `mypy src`, `ruff check .` を順に実行して回帰を防ぐ。
3. 設定変更は `config/settings.example.json` への反映とリリースノート下書きを忘れず、完了後は当表のチェックボックスを更新する。
