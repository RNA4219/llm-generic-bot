---
sprint: 1
status: draft
updated: 2025-10-11
---

# Sprint 1 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:----------------|
| [x] | SND-01 | Discord/Misskey RetryPolicy 実装 | `src/llm_generic_bot/adapters/discord.py`<br>`src/llm_generic_bot/adapters/misskey.py` | 429/5xx 応答で指数バックオフを適用し、最大試行回数超過時に失敗イベントを記録する（`DiscordSender`/`MisskeySender` に導入済み） | `tests/adapters/test_retry_policy.py`: 429, Retry-After, 5xx の再送シナリオ |
| [x] | SND-02 | Permit ゲートでチャンネル別クォータ制御 | `src/llm_generic_bot/core/arbiter.py`<br>`src/llm_generic_bot/config/quotas.py`<br>`src/llm_generic_bot/core/orchestrator.py` | クォータ超過時に送信抑止し、メトリクスとログへ拒否理由を残す（PermitGate をオーケストレータへ組み込み済み。残課題: quota 設定の運用チューニングと監視ダッシュボード反映） | `tests/core/test_quota_gate.py`: 上限到達・リセット・許可ケース |
| [x] | SCH-01 | CoalesceQueue で近接メッセージ併合 | `src/llm_generic_bot/core/scheduler.py`<br>`src/llm_generic_bot/core/queue.py` | スケジューラが `CoalesceQueue` からバッチを取り出し送信層へ渡す。残課題: 優先度逆転対策とマルチチャンネル分離の追加検証 | `tests/core/test_coalesce_queue.py`: 時間窓・閾値・単発ケース |
| [x] | SCH-02 | スケジューラにジッタを導入 | `src/llm_generic_bot/core/scheduler.py`<br>`src/llm_generic_bot/core/arbiter.py` | `Scheduler` が `next_slot` を通じてジッタを適用し、無効化時は即時送信する。残課題: ジッタ範囲の境界テストと運用パラメータ調整 | `tests/core/test_scheduler_jitter.py`: オフセット計算と無効化切替 |
| [x] | OPS-01 | 送信処理の構造化ログ出力 | `src/llm_generic_bot/adapters/*.py`<br>`src/llm_generic_bot/core/orchestrator.py` | 成功/失敗イベントを JSON で出力し、Correlation ID を付与（`run_with_retry` とオーケストレータで稼働中） | `tests/core/test_structured_logging.py`: ログフォーマット・エラー経路 |
| [x] | OPS-02 | CI パイプライン整備 | `.github/workflows/ci.yml`<br>`pyproject.toml` | PR 時に `ruff check .`・`mypy src`・`pytest -q`・CodeQL 解析を個別ジョブで実行し、GitHub Checks へ反映（`pip install -e .[dev]` を共通セットアップとして使用） | `act -W .github/workflows/ci.yml -j lint`<br>`act -W .github/workflows/ci.yml -j type`<br>`act -W .github/workflows/ci.yml -j test` |

## 進行手順
1. `tests/` 配下に先行テストを作成し、期待挙動を固定。
2. 実装を各モジュールに反映し、リトライ・併合・ジッタ・ログ処理を順次実装。
3. `pytest` と `mypy`, `ruff` を実行して品質を確認。
4. 完了時にチェックボックスを更新し、必要に応じて後続スプリントへフィードバック。
