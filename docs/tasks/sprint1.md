---
sprint: 1
status: draft
updated: 2024-06-08
---

# Sprint 1 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:----------------|
| [ ] | SND-01 | Discord/Misskey RetryPolicy 実装 | `adapters/discord.py`, `adapters/misskey.py` | 429/5xx 応答で指数バックオフを適用し、最大試行回数超過時に失敗イベントを記録する | `tests/adapters/test_retry_policy.py`: 429, Retry-After, 5xx の再送シナリオ |
| [ ] | SND-02 | Permit ゲートでチャンネル別クォータ制御 | `core/arbiter.py`, `config/quotas.py` | クォータ超過時に送信抑止し、メトリクスとログへ拒否理由を残す | `tests/core/test_quota_gate.py`: 上限到達・リセット・許可ケース |
| [ ] | SCH-01 | CoalesceQueue で近接メッセージ併合 | `core/scheduler.py`, `core/queue.py` | 時間窓内のジョブが単一バッチにまとめられ送信層に渡される | `tests/core/test_coalesce_queue.py`: 時間窓・閾値・単発ケース |
| [ ] | SCH-02 | スケジューラにジッタを導入 | `core/scheduler.py` | 指定ジッタ範囲で送信時刻が分散し、設定無効化時は即時送信 | `tests/core/test_scheduler_jitter.py`: オフセット計算と無効化切替 |
| [ ] | OPS-01 | 送信処理の構造化ログ出力 | `adapters/*.py`, `core/orchestrator.py` | 成功/失敗イベントを JSON で出力し、Correlation ID を付与 | `tests/core/test_structured_logging.py`: ログフォーマット・エラー経路 |

## 進行手順
1. `tests/` 配下に先行テストを作成し、期待挙動を固定。
2. 実装を各モジュールに反映し、リトライ・併合・ジッタ・ログ処理を順次実装。
3. `pytest` と `mypy`, `ruff` を実行して品質を確認。
4. 完了時にチェックボックスを更新し、必要に応じて後続スプリントへフィードバック。
