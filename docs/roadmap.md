# ロードマップ

## 現在の完成度
- `main.py` は設定読込後に日次天気ジョブのみをスケジュールし、近傍デデュープ・クールダウン記録を経由して Discord/Misskey 送信クラスへ委譲している。
- 天気機能は OpenWeather から都市ごとの現在値を取得し、30℃/35℃閾値や前日比ΔTをもとに注意枠を生成しつつ today/yesterday キャッシュをローテーションしている。
- Discord/Misskey 送信層には RetryPolicy と構造化ログが導入済みで、送信成否とリトライ結果が JSON ログに集約される。
- スケジューラ、クールダウン、アービタ、デデュープといった基盤コンポーネントは最小限実装のままで、単発ジョブ直送の経路のみが稼働している。Permit ゲートのクォータ統合やスケジューラ経路のバッチ化・ジッタ付与、News/おみくじ機能の本実装が残課題。
- テストはリトライ・クォータ・ジッタ・構造化ログの先行ケースまで追加済み。

## Sprint 1: Sender堅牢化 & オーケストレータ
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）: 429/5xx を指数バックオフ付きで再送し、上限回数で失敗をロギング。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）: チャンネル別クォータをチェックし、拒否時はメトリクスを更新。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）: 近接メッセージを併合し、送信処理にバッチで渡す。
- [SCH-02] ジッタ適用（`core/scheduler.py`）: 送信時刻にランダムオフセットを付与し突発集中を緩和。
- [OPS-01] 構造化ログ/監査（`adapters/*`, `core/orchestrator.py`）: 送信結果とコンテキストを JSON ログで記録。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）: 既存の `pytest` ジョブを軸に、`ruff`/`black` 連携の lint ジョブ、`mypy --strict` の type ジョブ、`pytest -m "not slow"` を分離した test ジョブを順に導入する。lint→type→test の依存を明示し、共通セットアップは再利用可能な composite action 化で集約する。依存: `pyproject.toml` の型/リンタ設定確定および [SND-01]/[OPS-01] でのログ要件確定。

## Sprint 2: UX & コンテンツ
- [UX-01] Engagement 反映ロジック（`features/weather.py`, `core/orchestrator.py`）: 反応履歴を参照し出力頻度を調整。
- [UX-02] ニュース配信実装（`features/news.py`）: フィード取得・要約・クールダウンの統合。
- [UX-03] おみくじ生成（`features/omikuji.py`）: コンテンツ生成とテンプレート、ローテーション制御。
- [UX-04] DM ダイジェスト（`adapters/discord.py`, `features/*`）: 日次ダイジェスト生成とスケジュール接続。

## Sprint 3: 運用・可観測性
- [OPS-02] 週次サマリ（`core/orchestrator.py`, `features/report.py`）: 成果・失敗を集計し運用向けに通知。
- [OPS-03] 設定再読込ログ（`main.py`, `config/*`）: リロード時の差分検出と監査ログ。
- [OPS-04] ランタイムメトリクス（`infra/metrics.py` 新設）: スケジューラ遅延や送信成功率を可視化。

## テストロードマップ
- 既存: `tests/adapters/test_retry_policy.py` で Discord/Misskey の 429/Retry-After、指数バックオフ、非リトライ判定まで網羅済み。`tests/core/test_scheduler_jitter.py` はジッタ有無と `next_slot` 呼出の切替、`tests/test_cooldown.py` はクールダウン係数の境界値を抑えている。
- Sprint 1: `tests/core/test_coalesce_queue.py`, `tests/core/test_quota_gate.py` を追加し、バッチ併合の優先順位・ダウンサンプリングと Permit 判定のエラー経路を補完する。Retry ログの JSON 構造スナップショットを `tests/adapters/test_retry_policy.py` に拡張し、監査項目を固定。
- Sprint 2: `tests/features/test_news.py`, `tests/features/test_omikuji.py` を追加し、コンテンツ生成のキャッシュ/クールダウン統合と、フォールバック文言のパターン網羅を進める。
- Sprint 3: `tests/infra/test_metrics_reporting.py` を追加し、メトリクス発報と設定再読込ログのスナップショット検証をまとめて行う。Permit/クールダウンのダッシュボード連携を integration テストで追跡。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
