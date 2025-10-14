# ロードマップ

## 現在の完成度
- `main.py` はプロキシ兼エントリーポイントとして `runtime.setup.setup_runtime` を呼び出し、スケジューラ起動と終了時のオーケストレータ停止のみを担う。ランタイム構築ロジックは `src/llm_generic_bot/runtime/setup/__init__.py` を公開エントリーポイントとしつつ、`src/llm_generic_bot/runtime/setup/reports.py` や `src/llm_generic_bot/runtime/setup/runtime_helpers.py` などの補助モジュールへ分割済み。
- `setup_runtime` は `JobContext` を経由して各ジョブファクトリへ依存を渡し、プロバイダ参照は `src/llm_generic_bot/runtime/jobs/common.py` の `resolve_object` に集約された文字列解決ロジックで `module:attr` / `module.attr` 形式からロードされる。これにより設定差し替えだけでダミー実装や本番実装を切り替えつつ、共通のセットアップフローを維持できる。
- `build_weather_jobs` は OpenWeather からの都市別現在値を配信する Weather 投稿ジョブを構築し、設定で指定された単一/複数スケジュールを 1 件の `ScheduledJob` に束ねつつ today/yesterday キャッシュをローテーションし、30℃/35℃ 閾値や前日比 ΔT をもとに注意枠を生成している。
- Discord/Misskey 送信層には RetryPolicy と構造化ログが導入済みで、送信成否とリトライ結果が JSON ログに集約される。
- PermitGate・CoalesceQueue・ジッタは次の連携で稼働している:
  - `src/llm_generic_bot/runtime/setup/__init__.py` の `setup_runtime` は `src/llm_generic_bot/runtime/setup/runtime_helpers.py` を介して `PermitGate.permit` の結果を `PermitDecision` に包み直し、許可時はジョブ名を差し替えつつ `Orchestrator.enqueue` へ渡す。
  - CoalesceQueue はスケジューラが収集した同一ジョブを閾値に応じてバッチ化し、Permit 判定前のメッセージ束を保持する。`Scheduler.queue.push` で積まれたバッチは `dispatch_ready_batches` を経て `sender.send` で `Orchestrator.enqueue` に載せられ、内部ワーカー `_process` が Permit を評価する。不許可時は `send.denied` を記録してバッチを破棄する。
  - ジッタは `core/scheduler.py` の `Scheduler` で既定有効となり、Permit 判定前のバッチに対して `next_slot` が遅延を決定してからオーケストレータへ渡す。統合テストでは `scheduler.jitter_enabled = False` としてテストの決定性を確保している。
- integration テストは以下で運用経路をカバーしている:
  - `tests/integration/test_main_pipeline.py`: Permit 通過後にチャンネル付き文字列バッチを送出できることと Permit ゲート呼び出しを追跡。
  - `tests/integration/test_permit_bridge.py`: `PermitGate` 経由の送信成否に応じたメトリクスタグ（`retryable` 含む）を直接検証。
  - `tests/integration/test_runtime_weekly_report.py`: 週次サマリジョブの曜日スケジュールおよびテンプレート整形を `weekly_snapshot` / `generate_weekly_summary` の協調呼び出しで検証。
- `tests/integration/test_runtime_multicontent.py`: `setup_runtime` が Weather/News/おみくじ/DM ダイジェストの 4 ジョブを登録し、
  - Weather/News/おみくじは設定どおりのチャンネルへエンキューされることを確認。
  - DM ダイジェストはスケジューラのキューを増やさずに sender が直接 DM を送ることを、DM ジョブ実行後もエンキュー件数が変化しない挙動で検証。
  - `tests/integration/test_runtime_multicontent.py::test_setup_runtime_resolves_string_providers`: サンプル設定 `config/settings.example.json` に含まれる Provider 参照文字列が `resolve_object` により実体化され、コロン／ドット参照形式の指定どおりに `llm_generic_bot.runtime.providers` の実装へ接続されることを検証。
    - `llm_generic_bot.runtime.providers.SAMPLE_NEWS_FEED`: ニュースフィード取得を担うダミー実装。
    - `llm_generic_bot.runtime.providers.SAMPLE_NEWS_SUMMARY`: ニュース要約のサンプル実装。
    - `llm_generic_bot.runtime.providers.SAMPLE_DM_LOG`: DM ログ収集のサンプル実装。
    - `llm_generic_bot.runtime.providers.SAMPLE_DM_SUMMARY`: DM 要約生成のサンプル実装。
    - `llm_generic_bot.runtime.providers.SAMPLE_DM_SENDER`: DM 送信のサンプル実装。
- `tests/integration/test_runtime_news_cooldown.py`: News ジョブがクールダウン継続中はエンキューを抑止し、Permit 呼び出しを行わないことを確認。
- 残課題は Permit/ジッタ/バッチ閾値のパラメータ調整と Permit 失敗時の再評価フロー整備、Permit クォータの多段構成およびバッチ再送ガードの強化など運用チューニングである（News/おみくじ/DM ダイジェスト経路の異常系結合テストは `tests/integration/test_runtime_multicontent_failures.py` で完了済み）。

## Sprint 1: Sender堅牢化 & オーケストレータ
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）: 429/5xx を指数バックオフ付きで再送し、上限回数で失敗をロギング。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）: チャンネル別クォータをチェックし、拒否時はメトリクスを更新。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）: 近接メッセージを併合し、送信処理にバッチで渡す。
- [SCH-02] ジッタ適用（`core/scheduler.py`）: 送信時刻にランダムオフセットを付与し突発集中を緩和。
- [OPS-01] 構造化ログ/監査（`adapters/*`, `core/orchestrator.py`）: 送信結果とコンテキストを JSON ログで記録。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）: `ruff check`、`mypy src`、`pytest -q` を独立ジョブとして並列運用している現行構成を維持しつつ、Lint/Type/Test の成否を Slack 通知するガードレールを追加する。依存: 共通セットアップを各ジョブで手動繰り返し適用している暫定運用の解消。
- [OPS-06] セキュリティスキャン拡充（`.github/workflows/ci.yml`）: CodeQL 解析と `pip-audit` を週次ジョブで追加し、依存ライブラリの脆弱性検出を自動化する。依存: [OPS-05] の共通セットアップ整備。→ 実装済み

## Sprint 2: UX & コンテンツ
### 完了済み
- [UX-01] Engagement 反映ロジック（`features/weather.py`, `core/orchestrator.py`）: リアクション履歴をもとに出力頻度を調整し、`tests/features/test_weather_engagement.py` で閾値・クールダウン・再開シナリオを固定。
- [UX-02] ニュース配信実装（`features/news.py`）: フィード取得・要約・クールダウンを統合し、`tests/features/test_news.py` で正常系とフォールバック・クールダウン抑止を検証。
- [UX-03] おみくじ生成（`features/omikuji.py`）: テンプレートローテーションとユーザー別シードを実装し、`tests/features/test_omikuji.py` でローテーションとフォールバック挙動をカバー。
- [UX-04] DM ダイジェスト（`adapters/discord.py`, `features/*`）: 日次ダイジェストを PermitGate 経由で送信し、`tests/features/test_dm_digest.py` で集計・リトライ・PermitGate 連携を確認。

### 残課題
- Engagement 指標の長期トレンド分析と、Permit クォータ変動時の通知頻度チューニング方針を整理する。（OPS-08～OPS-10 で異常系テスト強化は完了済み）

## Sprint 3: 運用・可観測性
- [OPS-02] 週次サマリ（`core/orchestrator.py`, `features/report.py`）: 成果・失敗を集計し運用向けに通知。
- [OPS-03] 設定再読込ログ（`src/llm_generic_bot/config/loader.py`, `src/llm_generic_bot/runtime/setup/__init__.py`, `config/*`）: リロード時の差分検出と監査ログ。
- [OPS-04] ランタイムメトリクス（`src/llm_generic_bot/infra/metrics/__init__.py`, `src/llm_generic_bot/infra/metrics/reporting.py`, `src/llm_generic_bot/infra/metrics/service.py`）: スケジューラ遅延や送信成功率を可視化。
- [OPS-07] Weather 複数スケジュール（`src/llm_generic_bot/runtime/jobs/weather.py`, `tests/runtime/test_weather_jobs.py`）: 都市ごとに定義された複数スケジュールが `build_weather_jobs` で 1 件の `ScheduledJob` に複数時刻を集約し、ジョブ登録時に想定通りの時間帯へ割り当てられることを検証。

## Sprint 4: テスト強化 & 異常系整備
- [OPS-08] ジッタ境界と Permit 連携テスト: `tests/core/test_scheduler_jitter.py` の 4 ケース（`test_scheduler_applies_jitter`、`test_scheduler_immediate_when_jitter_disabled`、`test_scheduler_jitter_respects_range`、`test_scheduler_preserves_job_with_jitter`）でジッタ有無の分岐と遅延レンジ境界、Permit 判定後のジョブ名維持を固定。→ 実装済み
- [OPS-09] `send_duplicate_skip` のログ/メトリクス整合: `tests/core/test_structured_logging.py` の `test_orchestrator_logs_success_with_correlation_id` / `test_orchestrator_logs_failure_and_metrics` / `test_orchestrator_logs_permit_denial` / `test_orchestrator_logs_duplicate_skip` が重複抑止時の構造化ログ、Permit 拒否・失敗・成功経路の JSON ログ、および `send.duration` の秒単位タグを検証。→ 実装済み
- [OPS-10] News/おみくじ/DM 異常系結合テスト: `tests/integration/test_runtime_multicontent_failures.py` の `test_permit_denied_records_metrics` / `test_cooldown_resume_allows_retry` / `test_summary_provider_retry_and_fallback` / `test_dm_digest_permit_denied_records_metrics` が Permit 拒否メトリクス、クールダウン解除後の再送成功、サマリーリトライとフォールバック記録、DM ダイジェスト拒否時の送信スキップを週次スナップショットまで確認。→ 実装済み

## テストロードマップ
- 現状認識:
  - リトライ: `tests/adapters/test_retry_policy.py` で Discord/Misskey の 429/Retry-After、指数バックオフ、非リトライ判定までカバー済み。残課題だった `_structured_log` の JSON フィールド（`llm_generic_bot.adapters._retry`）スナップショットは `tests/adapters/test_retry_policy.py::test_retry_logging_snapshot` で完了し、リトライ限界到達時の監査属性欠落を防止済み。
  - 併合: `tests/core/test_coalesce_queue.py` で窓内併合、閾値即時フラッシュ、単発バッチを検証済み。残課題だった `CoalesceQueue` の優先度逆転ガードは `tests/core/test_coalesce_queue.py::test_coalesce_queue_separates_incompatible_batches` で完了し、`llm_generic_bot.core.queue` のマルチチャンネル分離・`pop_ready` ソート安定性もテーブル駆動で確認済み。
  - ジッタ: `tests/core/test_scheduler_jitter.py` で `Scheduler` のジッタ有無と `next_slot` 呼び出しを制御できており、同テストでジッタ範囲の最小/最大境界と Permit 連携も固定済み（[OPS-08] 完了）。
  - 構造化ログ: `tests/core/test_structured_logging.py` で送信成功/失敗/Permit 拒否のログイベントとメトリクス更新を確認済みで、`send_duplicate_skip` 経路と `send.duration` メトリクスの整合も同テストで固定済み（[OPS-09] 完了）。
- Sprint 1: `tests/adapters/test_retry_policy.py` に JSON ログのスナップショットケースを追加し、`tests/core/test_coalesce_queue.py` へ優先度逆転ガードの境界ケースを拡張する。同時に `tests/core/test_quota_gate.py` では Permit 拒否理由の種類ごとに `llm_generic_bot.core.arbiter` のタグ付けを検証し、構造化ログ側と整合させる。
- Sprint 2: `tests/features/test_news.py`, `tests/features/test_omikuji.py`, `tests/features/test_dm_digest.py` を追加済み。正常系とフォールバック、PermitGate 連携はカバーしており、ジッタ境界と異常系結合テストは OPS-08/OPS-10 で完遂。
- Sprint 3: `tests/infra/test_metrics_reporting.py` を追加し、`src/llm_generic_bot/infra/metrics/__init__.py`（新設予定）と `src/llm_generic_bot/infra/metrics/reporting.py`/`src/llm_generic_bot/infra/metrics/service.py` の連携、および設定再読込監査のログパス（`config` パッケージ想定）をスナップショットで確認する。並行して `tests/core/test_structured_logging.py` を拡張し、`MetricsRecorder.observe` 呼び出しの単位検証を追加する。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
- Sprint 2 詳細: [`docs/tasks/sprint2.md`](tasks/sprint2.md)
- Sprint 3 詳細: [`docs/tasks/sprint3.md`](tasks/sprint3.md)
- Sprint 4 詳細: [`docs/tasks/sprint4.md`](tasks/sprint4.md)
