# ロードマップ

## 現在の完成度
- `main.py` は設定読込後に日次天気ジョブのみをスケジュールし、近傍デデュープ・クールダウン記録を経由して Discord/Misskey 送信クラスへ委譲している。
- 天気機能は OpenWeather から都市ごとの現在値を取得し、30℃/35℃閾値や前日比ΔTをもとに注意枠を生成しつつ today/yesterday キャッシュをローテーションしている。
- スケジューラ、クールダウン、アービタ、デデュープといった基盤コンポーネントは最小限実装で、スケジューラ経路は単発ジョブを直送するのみでバッチ化やジッタ付与が未統合。
- Discord/Misskey 送信は RetryPolicy と構造化ログを導入済みで、送信成否が JSON ログに収集される。
- Permit ゲートのクォータ統合とスケジューラ経路の拡張が残課題で、News/おみくじもスタブ段階。テストはリトライ・クォータ・ジッタ・構造化ログの先行ケースまで追加済み。

## Sprint 1: Sender堅牢化 & オーケストレータ
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）: 429/5xx を指数バックオフ付きで再送し、上限回数で失敗をロギング。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）: チャンネル別クォータをチェックし、拒否時はメトリクスを更新。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）: 近接メッセージを併合し、送信処理にバッチで渡す。
- [SCH-02] ジッタ適用（`core/scheduler.py`）: 送信時刻にランダムオフセットを付与し突発集中を緩和。
- [OPS-01] 構造化ログ/監査（`adapters/*`, `core/orchestrator.py`）: 送信結果とコンテキストを JSON ログで記録。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）: 既存の `pytest` ジョブを土台に lint/type チェックを段階導入し、`main`/PR へのプッシュ時に品質ゲートを設ける。依存: `pyproject.toml` の型/リンタ設定確定および [SND-01]/[OPS-01] でのログ要件確定。

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
- 現状テストはクールダウン境界のみであり、送信リトライや併合、クォータ制御の網羅が不足している。
- Sprint 1 完了へ向け、`tests/adapters/test_retry_policy.py`, `tests/core/test_coalesce_queue.py`, `tests/core/test_quota_gate.py` を新設し、429/Retry-After モックやバッチ併合、Permit 判定を検証する。
- Sprint 2 ではニュース・おみくじ向けに `tests/features/test_news.py`, `tests/features/test_omikuji.py` を追加し、コンテンツ生成とクールダウン統合を TDD で進める。
- Sprint 3 では運用テレメトリの統合テスト `tests/infra/test_metrics_reporting.py` を追加し、設定再読込ログのスナップショット検証を行う。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
