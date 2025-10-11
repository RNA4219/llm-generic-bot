# ロードマップ

## 現在の完成度
- `main.py` は設定読込後に日次天気ジョブのみをスケジュールし、近傍デデュープ・クールダウン記録を経由して Discord/Misskey 送信クラスへ委譲している。
- 天気機能は OpenWeather から都市ごとの現在値を取得し、30℃/35℃閾値や前日比ΔTをもとに注意枠を生成しつつ today/yesterday キャッシュをローテーションしている。
- Discord/Misskey 送信層には RetryPolicy と構造化ログが導入済みで、送信成否とリトライ結果が JSON ログに集約される。
- `setup_runtime` で PermitGate と CoalesceQueue を有効化済みで、Permit が `QuotaConfig` に従って発火しつつバッチ併合が稼働している。
- integration テストでは Permit/Coalesce 経路を含む end-to-end の送信処理を検証し、Permit 拒否や併合結果の JSON 出力をスナップショット化している。
- スケジューラ、クールダウン、アービタ、デデュープといった基盤コンポーネントは最小限実装のままで、単発ジョブ直送の経路のみが稼働している。Permit ゲートのクォータ統合やスケジューラ経路のバッチ化・ジッタ付与、News/おみくじ機能の本実装が残課題。
- テストはリトライ・クォータ・ジッタ・構造化ログ、Permit/Coalesce の integration ケースまで追加済み。

## Sprint 1: Sender堅牢化 & オーケストレータ
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）: 429/5xx を指数バックオフ付きで再送し、上限回数で失敗をロギング。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）: チャンネル別クォータをチェックし、拒否時はメトリクスを更新。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）: 近接メッセージを併合し、送信処理にバッチで渡す。
- [SCH-02] ジッタ適用（`core/scheduler.py`）: 送信時刻にランダムオフセットを付与し突発集中を緩和。
- [OPS-01] 構造化ログ/監査（`adapters/*`, `core/orchestrator.py`）: 送信結果とコンテキストを JSON ログで記録。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）: `ruff check`、`mypy src`、`pytest -q` を独立ジョブとして並列運用している現行構成を維持しつつ、Lint/Type/Test の成否を Slack 通知するガードレールを追加する。依存: 共通セットアップの composite action 化。
- [OPS-06] セキュリティスキャン拡充（`.github/workflows/ci.yml`）: CodeQL 解析と `pip-audit` を週次ジョブで追加し、依存ライブラリの脆弱性検出を自動化する。依存: [OPS-05] の共通セットアップ整備。

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
- 現状認識:
  - リトライ: `tests/adapters/test_retry_policy.py` で Discord/Misskey の 429/Retry-After、指数バックオフ、非リトライ判定までカバー済み。残課題は `_structured_log` が吐き出す JSON フィールド（`llm_generic_bot.adapters._retry`）をスナップショット化し、リトライ限界到達時の監査属性欠落を防ぐこと。
  - 併合: `tests/core/test_coalesce_queue.py` で窓内併合、閾値即時フラッシュ、単発バッチを検証済み。残課題は `CoalesceQueue` の優先度逆転ガードや、`llm_generic_bot.core.queue` のマルチチャンネル分離・`pop_ready` ソート安定性をテーブル駆動で追加すること。
  - ジッタ: `tests/core/test_scheduler_jitter.py` で `Scheduler` のジッタ有無と `next_slot` 呼び出しを制御できている。残課題は `llm_generic_bot.core.scheduler` におけるジッタ範囲最小/最大境界と、Permit 後バッチ遅延との連携をプロパティベースで検証すること。
  - 構造化ログ: `tests/core/test_structured_logging.py` で送信成功/失敗/Permit 拒否のログイベントとメトリクス更新を確認済み。残課題は `Orchestrator` の重複スキップ経路（`send_duplicate_skip`）や `send.duration` メトリクス単位（秒）を追加検証し、ログとメトリクスの整合性を固定すること。
- Sprint 1: `tests/adapters/test_retry_policy.py` に JSON ログのスナップショットケースを追加し、`tests/core/test_coalesce_queue.py` へ優先度逆転ガードの境界ケースを拡張する。同時に `tests/core/test_quota_gate.py` では Permit 拒否理由の種類ごとに `llm_generic_bot.core.arbiter` のタグ付けを検証し、構造化ログ側と整合させる。
- Sprint 2: `tests/features/test_news.py`, `tests/features/test_omikuji.py` を追加し、`features/news.py` と `features/omikuji.py` のキャッシュ/クールダウン統合、フォールバック文言、Permit 連携を網羅する。あわせて `tests/core/test_scheduler_jitter.py` にジッタ境界ケースを盛り込み、News/おみくじのスケジュール遅延仕様を固定する。
- Sprint 3: `tests/infra/test_metrics_reporting.py` を追加し、`infra/metrics.py`（新設予定）と設定再読込監査のログパス（`config` パッケージ想定）をスナップショットで確認する。並行して `tests/core/test_structured_logging.py` を拡張し、`MetricsRecorder.observe` 呼び出しの単位検証を追加する。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
