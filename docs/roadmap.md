# ロードマップ

## 現在の完成度
- `main.py` はプロキシ兼エントリーポイントとして `runtime.setup.setup_runtime` を呼び出し、スケジューラ起動と終了時のオーケストレータ停止のみを担う。ランタイム構築ロジックは `src/llm_generic_bot/runtime/setup/__init__.py` を公開エントリーポイントとしつつ、`src/llm_generic_bot/runtime/setup/reports.py` や `src/llm_generic_bot/runtime/setup/runtime_helpers.py` などの補助モジュールへ分割済み。
- `setup_runtime` は `JobContext` を経由して各ジョブファクトリへ依存を渡し、プロバイダ参照は `src/llm_generic_bot/runtime/jobs/common.py` の `resolve_object` に集約された文字列解決ロジックで `module:attr` / `module.attr` 形式からロードされる。これにより設定差し替えだけでダミー実装や本番実装を切り替えつつ、共通のセットアップフローを維持できる。
- `build_weather_jobs` は OpenWeather からの都市別現在値を配信する Weather 投稿ジョブを構築し、設定で指定された単一/複数スケジュールを 1 件の `ScheduledJob` に束ねる際のジョブ登録と依存解決のみを担う。キャッシュローテーションや 30℃/35℃ 閾値・前日比 ΔT の評価、警告メッセージ生成といった投稿本文のロジックは `features/weather.build_weather_post` に集約されている。
- Discord/Misskey 送信層には RetryPolicy と構造化ログが導入済みで、送信成否とリトライ結果が JSON ログに集約される。
- PermitGate・CoalesceQueue・ジッタは次の連携で稼働している:
  - `src/llm_generic_bot/runtime/setup/__init__.py` の `setup_runtime` は `src/llm_generic_bot/runtime/setup/gates.py::build_permit` を呼び出して `PermitGate.permit` の結果を `PermitDecision` へ包み直した `PermitEvaluator` を構築し、同関数内で `Orchestrator` と `JobContext` へ共有している。
  - CoalesceQueue はスケジューラが収集した同一ジョブを閾値に応じてバッチ化し、Permit 判定前のメッセージ束を保持する。`Scheduler.queue.push` で積まれたバッチは `dispatch_ready_batches` を経て `sender.send` で `Orchestrator.enqueue` に載せられ、内部ワーカー `_process` が Permit を評価する。不許可時は `send.denied` を記録してバッチを破棄する。
  - ジッタは `core/scheduler.py` の `Scheduler` で既定有効となり、Permit 判定前のバッチに対して `next_slot` が遅延を決定してからオーケストレータへ渡す。統合テストでは `scheduler.jitter_enabled = False` としてテストの決定性を確保している。
- integration テストは以下で運用経路をカバーしている:
  - `tests/integration/test_main_pipeline.py`: Permit 通過後にチャンネル付き文字列バッチを送出できることと Permit ゲート呼び出しを追跡。
  - `tests/integration/test_permit_bridge.py`: `PermitGate` 経由の送信成否に応じたメトリクスタグ（`retryable` 含む）を直接検証。
  - `tests/integration/runtime_weekly_report/`: 週次サマリジョブの曜日スケジュールおよびテンプレート整形を `weekly_snapshot` / `generate_weekly_summary` の協調呼び出しで検証。
    - `test_scheduler.py`:
      - `test_weekly_report_respects_weekday_schedule`: `Scheduler` が構成した平日スケジュール（例: Tue/Thu 09:00）どおりにジョブを起動できることを確認し、曜日順守を保証。
      - `test_weekly_report_permit_override_applies_to_dispatch`: Permit 上書き設定が dispatch 送信先へ反映され、指定されたプラットフォーム/チャンネル/ジョブで実行されることを検証。
    - `test_templates.py`:
      - `test_weekly_report_config_template_regression`: テンプレート改変が週次サマリ生成へ確実に反映されることを保証。
      - `test_weekly_report_template_line_context`: テンプレート行整形（行コンテキストの付与）が期待どおりに適用されることを固定。
    - `test_fallbacks.py`:
      - `test_weekly_report_skips_self_success_rate`: 自身の成功率が週次サマリから除外されることを検証し、自己スコア混入を防止。
    - `tests/integration/test_runtime_dm_digest.py`: DM ダイジェストジョブが dispatch キューを汚さないことを確認する専用テスト（パイプライン経由の dispatch を通さず、スケジューラへの push 抑止にフォーカスする）。Permit 通過後に直接送信する経路は `tests/integration/runtime_multicontent/test_dm_digest.py` が多経路統合テストとして担保するため、本テストは責務を分離している。
      - `test_dm_digest_job_returns_none_and_skips_dispatch`: キュー未追加と dispatch スキップを保証し、dispatch キューを汚さないことを固定化する。
      - `tests/integration/test_runtime_dm_digest.py::test_dm_digest_job_denied_by_permit`: Permit 拒否時に DM 送信を抑止しつつ、`dm_digest_permit_denied` ログイベントへ `retryable=False` と `job="dm_digest-denied"`（PermitDecision 由来サフィックス）を記録していることを検証する。
    - `tests/integration/weather_engagement/`: Weather Engagement の履歴参照と抑止/再開制御を代表ケース（`test_cache_control.py`・`test_cooldown_coordination.py`・`test_engagement_calculation.py`）で end-to-end に検証し、履歴キャッシュの同期と Permit 前の投稿判断を保証する。
      - Weather Engagement の履歴連携を `history_provider` 呼び出し・再開スコアで確認。
    - `tests/integration/test_runtime_reload.py`: 設定リロード時の差分検出と監査ログ出力をファイル I/O 越しに確認し、リロードシグナル後にランタイムへ副作用なく設定差分を適用できることを担保する。
      - 設定再読込時の差分ログ出力（差分なしケースはログ抑止）。
  - `tests/integration/runtime_multicontent/test_pipeline.py`: `setup_runtime` が Weather/News/おみくじ/DM ダイジェストの 4 ジョブを登録し、
    - Weather/News/おみくじは設定どおりのチャンネルへエンキューされることを確認。
    - スケジューラ dispatch 中の DM ダイジェスト監視を担い、オーケストレータ経由での配送状況を確認する（直接送信の保証は専用ジョブテストに委譲）。
    - `test_weekly_report_job_uses_metrics_and_template`: `MetricsService.collect_weekly_snapshot` を介した週次スナップショット取得と、`metrics_module.weekly_snapshot` によるテンプレート整形を統合パイプライン内で保証。
  - `tests/integration/runtime_multicontent/test_dm_digest.py`: DM 専用ジョブが Permit 通過後にキューへ積まず直接送信する経路を担保する（`tests/integration/test_runtime_dm_digest.py` で確認済みの dispatch キュー無汚染・Permit 拒否監査ログと責務分担）。
    - `test_dm_digest_job_sends_without_scheduler_queue`: スケジューラキューの件数が変化しないまま sender が DM を送ることを検証し、Permit 通過時に scheduler queue を経由しない直接送信保証を明示する。
- `tests/integration/runtime_multicontent/test_providers.py::test_setup_runtime_resolves_string_providers`: 動的に生成した `tests.integration.fake_providers` モジュールへ `news_feed` / `news_summary` / `dm_logs` / `dm_summary` / `dm_sender` を束ねた `SimpleNamespace` を登録し、`monkeypatch.setitem(sys.modules, module_name, provider_module)` で差し込んだ状態で `module:attr` 形式のプロバイダ文字列が `resolve_object` により正しく解決されることを確認する。
- `tests/integration/test_runtime_multicontent_failures.py`: [OPS-10] で追加された異常系結合テスト。Permit 拒否やプロバイダ障害時の再送挙動を再現し、News/おみくじ/DM ダイジェスト経路の例外処理を網羅済み。→ 実装済み
- `tests/integration/test_runtime_news_cooldown.py`: News ジョブがクールダウン継続中はエンキューを抑止し、Permit 呼び出しを行わないことを確認。
- 残課題は以下の運用チューニングに限定される（詳細は `docs/tasks/backlog.md` の OPS-B01〜OPS-B03 参照）:
  - Permit/ジッタ/バッチ閾値のパラメータ調整。→ OPS-B01 で継続対応中。
  - Permit 失敗時の再評価フロー整備。→ OPS-B02 で継続対応中。
  - Permit クォータの多段構成設計とバッチ再送ガード強化。→ OPS-B03 で継続対応中。
  - Engagement 指標の長期トレンド分析と Permit クォータ連動方針の確立。→ UX-B01 で継続対応中。

## Sprint 1: Sender堅牢化 & オーケストレータ
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）: 429/5xx を指数バックオフ付きで再送し、上限回数で失敗をロギング。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）: チャンネル別クォータをチェックし、拒否時はメトリクスを更新。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）: 近接メッセージを併合し、送信処理にバッチで渡す。
- [SCH-02] ジッタ適用（`core/scheduler.py`）: 送信時刻にランダムオフセットを付与し突発集中を緩和。
- [OPS-01] 構造化ログ/監査（`adapters/*`, `core/orchestrator.py`→`core/orchestrator/processor.py`）: 送信結果とコンテキストを JSON ログで記録。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）: `ruff check`、`mypy src`、`pytest -q` を独立ジョブとして並列運用している現行構成を維持しつつ、Lint/Type/Test 各ジョブに `Notify Slack on failure` ガードレールを追加済み。依存: 共通セットアップを各ジョブで手動繰り返し適用している暫定運用の解消。→ 実装済み
- [OPS-06] セキュリティスキャン拡充（`.github/workflows/ci.yml`）: CodeQL 解析と `pip-audit` を週次ジョブで追加し、依存ライブラリの脆弱性検出を自動化する。依存: [OPS-05] の共通セットアップ整備。→ 実装済み

## Sprint 2: UX & コンテンツ
### 完了済み
- [UX-01] Engagement 反映ロジック（`features/weather.py`, `core/orchestrator.py`→`core/orchestrator/processor.py`）: リアクション履歴をもとに出力頻度を調整し、`tests/features/test_weather_engagement.py` で閾値・クールダウン・再開シナリオを固定。
- [UX-02] ニュース配信実装（`features/news.py`）: フィード取得・要約・クールダウンを統合し、`tests/features/test_news.py` で正常系とフォールバック・クールダウン抑止を検証。
- [UX-03] おみくじ生成（`features/omikuji.py`）: テンプレートローテーションとユーザー別シードを実装し、`tests/features/test_omikuji.py` でローテーションとフォールバック挙動をカバー。
- [UX-04] DM ダイジェスト（`adapters/discord.py`, `features/*`）: 日次ダイジェストを PermitGate 経由で送信し、`tests/features/test_dm_digest.py` で集計・リトライ・PermitGate 連携を確認。

### 残課題
- Engagement 指標の長期トレンド分析と、Permit クォータ変動時の通知頻度チューニング方針を整理する。（OPS-08～OPS-10 で異常系テスト強化は完了済み）

## Sprint 3: 運用・可観測性
- [OPS-02] 週次サマリ（`core/orchestrator.py`→`core/orchestrator/processor.py`, `features/report.py`）: 成果・失敗を集計し運用向けに通知。
- [OPS-03] 設定再読込ログ（`src/llm_generic_bot/config/loader.py`, `src/llm_generic_bot/runtime/setup/__init__.py`, `config/*`）: リロード時の差分検出と監査ログ。
- [OPS-04] ランタイムメトリクス（`src/llm_generic_bot/infra/metrics/aggregator.py`, `src/llm_generic_bot/infra/metrics/aggregator_state.py`, `src/llm_generic_bot/infra/metrics/reporting.py`, `src/llm_generic_bot/infra/metrics/service.py`）: `aggregator.py` が送信/Permit 事象の公開ファサードとなり、`aggregator_state.py` がロック付きの履歴保持と週次スナップショット生成を担いつつ、`service.py` のバックエンド構成と `reporting.py` の集約ロジックへ橋渡しする。
- [OPS-07] Weather 複数スケジュール（`src/llm_generic_bot/runtime/jobs/weather.py`, `tests/runtime/test_weather_jobs.py`）: 都市ごとに定義された複数スケジュールが `build_weather_jobs` で 1 件の `ScheduledJob` に複数時刻を集約し、ジョブ登録時に想定通りの時間帯へ割り当てられることを検証。

## Sprint 4: テスト強化 & 異常系整備
- [OPS-08] ジッタ境界と Permit 連携テスト: `tests/core/test_scheduler_jitter.py` の 3 ケース（`test_scheduler_applies_jitter`、`test_scheduler_immediate_when_jitter_disabled`、`test_scheduler_jitter_respects_range`）でジッタ有無の分岐と遅延レンジ境界を固定し、Permit 判定後のジョブ名維持は `test_scheduler_jitter_respects_range` が担保する。→ 実装済み
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
- Sprint 3: ランタイムメトリクスの結合テストは `tests/infra/metrics/test_reporting_freeze_time.py`・`tests/infra/metrics/test_reporting_recording_metrics.py`・`tests/infra/metrics/test_reporting_service.py` へ分割済みで、旧単一ファイル版はレガシーシムとして互換維持用に残存。並行して `tests/core/test_structured_logging.py` を拡張し、`MetricsRecorder.observe` 呼び出しの単位検証を追加する。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
- Sprint 2 詳細: [`docs/tasks/sprint2.md`](tasks/sprint2.md)
- Sprint 3 詳細: [`docs/tasks/sprint3.md`](tasks/sprint3.md)
- Sprint 4 詳細: [`docs/tasks/sprint4.md`](tasks/sprint4.md)
