---
sprint: 1
status: draft
updated: 2025-10-11
---

# Sprint 1 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:----------------|
| [x] | SND-01 | Discord/Misskey RetryPolicy 実装 | `adapters/discord.py`<br>`adapters/misskey.py` | 429/5xx 応答で指数バックオフを適用し、最大試行回数超過時に失敗イベントを記録する（`DiscordSender`/`MisskeySender` へ適用済み） | `tests/adapters/test_retry_policy.py`: 429, Retry-After, 5xx の再送シナリオ |
| [x] | SND-02 | Permit ゲートでチャンネル別クォータ制御 | `src/llm_generic_bot/core/arbiter.py`<br>`src/llm_generic_bot/config/quotas.py`<br>`src/llm_generic_bot/core/orchestrator.py` | クォータ超過時に送信抑止し、メトリクスとログへ拒否理由を残す（PermitGate をオーケストレータへ組み込み済み。残課題: quota 設定の運用チューニングと監視ダッシュボード反映） | `tests/core/test_quota_gate.py`: 上限到達・リセット・許可ケース |
| [ ] | SCH-01 | CoalesceQueue で近接メッセージ併合 | `core/scheduler.py`<br>`core/queue.py` | 時間窓内のジョブが単一バッチにまとめられ送信層に渡される（`CoalesceQueue` 実装は完了、スケジューラ経路への本配線が残り） | `tests/core/test_coalesce_queue.py`: 時間窓・閾値・単発ケース |
| [ ] | SCH-02 | スケジューラにジッタを導入 | `core/scheduler.py` | 指定ジッタ範囲で送信時刻が分散し、設定無効化時は即時送信（`next_slot` 実装とテストは完了、実運用パラメータ調整が残課題） | `tests/core/test_scheduler_jitter.py`: オフセット計算と無効化切替 |
| [x] | OPS-01 | 送信処理の構造化ログ出力 | `adapters/*.py`<br>`core/orchestrator.py` | 成功/失敗イベントを JSON で出力し、Correlation ID を付与（`run_with_retry` とオーケストレータで稼働中） | `tests/core/test_structured_logging.py`: ログフォーマット・エラー経路 |
| [ ] | OPS-02 | CI パイプライン整備 | `.github/workflows/`<br>`pyproject.toml` | lint/type/test の各ジョブが PR 時に自動実行され、結果がステータスチェックへ連携される（`lint`: `ruff check .`, `type`: `mypy src`, `test`: `pytest -q` を稼働中） | `act -W .github/workflows/ci.yml -j lint`, `act -W .github/workflows/ci.yml -j type`, `act -W .github/workflows/ci.yml -j test` |

## 進行手順
1. `tests/` 配下に先行テストを作成し、期待挙動を固定。
2. 実装を各モジュールに反映し、リトライ・併合・ジッタ・ログ処理を順次実装。
3. `pytest` と `mypy`, `ruff` を実行して品質を確認。
4. 完了時にチェックボックスを更新し、必要に応じて後続スプリントへフィードバック。
