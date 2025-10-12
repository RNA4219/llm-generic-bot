---
sprint: 1
status: draft
updated: 2025-10-12
---

# Sprint 1 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:----------------|
| [x] | SND-01 | Discord/Misskey RetryPolicy 実装 | `src/llm_generic_bot/adapters/discord.py`<br>`src/llm_generic_bot/adapters/misskey.py` | 429/5xx 応答で指数バックオフが発火し、最大試行超過時に失敗イベントを構造化ログへ記録する。 | 本番で監視済み（失敗時は `event=send_retry_exhausted` を確認）。 | `tests/adapters/test_retry_policy.py`: 429・Retry-After・5xx の再送シナリオ |
| [x] | SND-02 | Permit ゲートでチャンネル別クォータ制御 | `src/llm_generic_bot/core/arbiter.py`<br>`src/llm_generic_bot/config/quotas.py`<br>`src/llm_generic_bot/core/orchestrator.py` | PermitGate/PermitBridge がオーケストレータ経由でバッチ送信時もクォータ超過を抑止し、拒否理由をメトリクス/ログへ出力する。 | 残課題: クォータ閾値の運用チューニングと監視ダッシュボードへの反映。 | `tests/core/test_quota_gate.py`: 上限到達・リセット・許可ケース<br>`tests/integration/test_main_pipeline.py`: オーケストレータ経由バッチで PermitGate がクォータ制御する正常系<br>`tests/integration/test_permit_bridge.py`: PermitBridge が拒否理由を伝搬しメトリクス更新する統合経路 |
| [x] | SCH-01 | CoalesceQueue で近接メッセージ併合 | `src/llm_generic_bot/core/scheduler.py`<br>`src/llm_generic_bot/core/queue.py` | スケジューラが `CoalesceQueue` からバッチを取得し送信層へ受け渡す。 | 残課題: 優先度逆転対策とマルチチャンネル分離の検証を次スプリントへ引継ぎ。 | `tests/core/test_coalesce_queue.py`: 時間窓・閾値・単発ケース |
| [x] | SCH-02 | スケジューラにジッタを導入 | `src/llm_generic_bot/core/scheduler.py`<br>`src/llm_generic_bot/core/arbiter.py` | `Scheduler` が `next_slot` でジッタを適用し、無効化フラグ時は即時送信へフォールバックする。 | 残課題: ジッタ範囲の境界テストと運用パラメータ調整。 | `tests/core/test_scheduler_jitter.py`: オフセット計算と無効化切替 |
| [x] | OPS-01 | 送信処理の構造化ログ出力 | `src/llm_generic_bot/adapters/*.py`<br>`src/llm_generic_bot/core/orchestrator.py` | 成功/失敗イベントを JSON 形式で出力し、Correlation ID を常に付与する。 | 追加要望: 可観測性チームとフォーマット拡張を検討中。 | `tests/core/test_structured_logging.py`: ログフォーマット・エラー経路 |
| [x] | OPS-02 | CI パイプライン整備 | `.github/workflows/ci.yml`<br>`pyproject.toml` | `push`／`pull_request` イベントで `ruff check .`・`mypy src`・`pytest -q`・CodeQL を個別 GitHub ジョブとして起動し、PermitGate 連携環境で 3 ジョブが稼働する。CodeQL は同イベントのみで起動し、`schedule` トリガーは未設定。 | 残課題: Slack 通知連携、キャッシュヒット率最適化、CodeQL 定期運用の設計（週次 `schedule` 追加は要検討）。 | `act -W .github/workflows/ci.yml -j lint`<br>`act -W .github/workflows/ci.yml -j type`<br>`act -W .github/workflows/ci.yml -j test` |

重複 ID は未検出。現行実装と乖離する旧行は存在しないため、上記テーブルを正とする。

## 進行手順
1. `tests/` 配下に先行テストを作成し、期待挙動を固定。
2. 実装を各モジュールに反映し、リトライ・併合・ジッタ・ログ処理を順次実装。
3. `pytest` と `mypy`, `ruff` を実行して品質を確認。
4. 完了時にチェックボックスを更新し、必要に応じて後続スプリントへフィードバック。
