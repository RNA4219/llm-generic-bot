<!-- markdownlint-disable MD013 MD022 MD032 -->
# ロードマップ

## 現在の完成度
- `main.py` はプロキシ兼エントリーポイントとして `runtime.setup.setup_runtime` を呼び出し、スケジューラ起動と終了時のオーケストレータ停止のみを担う。ランタイム構築ロジックは `src/llm_generic_bot/runtime/setup/__init__.py` を公開エントリーポイントとしつつ、`src/llm_generic_bot/runtime/setup/reports.py` や `src/llm_generic_bot/runtime/setup/runtime_helpers.py` などの補助モジュールへ分割済み。
- `setup_runtime` は `JobContext` を経由して各ジョブファクトリへ依存を渡し、プロバイダ参照は `src/llm_generic_bot/runtime/jobs/common.py` の `resolve_object` に集約された文字列解決ロジックで `module:attr` / `module.attr` 形式からロードされる。これにより設定差し替えだけでダミー実装や本番実装を切り替えつつ、共通のセットアップフローを維持できる。
- `build_weather_jobs` は OpenWeather からの都市別現在値を配信する Weather 投稿ジョブを構築し、設定で指定された単一/複数スケジュールを 1 件の `ScheduledJob` に束ねる際のジョブ登録と依存解決のみを担う。キャッシュローテーションや 30℃/35℃ 閾値・前日比 ΔT の評価、警告メッセージ生成といった投稿本文のロジックは `features/weather.build_weather_post` に集約されている。
  - `tests/features/test_weather_cache_rotation.py`: `today` スロットがローテーション時に `yesterday` へ確実に繰り下がり、直近レスポンスを新規 `today` として再書き込みすることを検証する。加えて、OpenWeather 呼び出しが失敗した場合でもキャッシュに保持された前回値へフェイルオーバーし、通知本文とキャッシュ両方で気温が保持されることを固定化する。
- Discord/Misskey 送信層には RetryPolicy と構造化ログが導入済みで、送信成否とリトライ結果が JSON ログに集約される。
- PermitGate・CoalesceQueue・ジッタは次の連携で稼働している:
  - `src/llm_generic_bot/runtime/setup/__init__.py` の `setup_runtime` は `src/llm_generic_bot/runtime/setup/gates.py::build_permit` を呼び出して `PermitGate.permit` の結果を `PermitDecision` へ包み直した `PermitEvaluator` を構築し、同関数内で `Orchestrator` と `JobContext` へ共有している。
  - CoalesceQueue はスケジューラが収集した同一ジョブを閾値に応じてバッチ化し、Permit 判定前のメッセージ束を保持する。`Scheduler.queue.push` で積まれたバッチは `dispatch_ready_batches` を経て `sender.send` で `Orchestrator.enqueue` に載せられ、内部ワーカー `_process` が Permit を評価する。不許可時は `send.denied` を記録してバッチを破棄する。
  - ジッタは `core/scheduler.py` の `Scheduler` で既定有効となり、Permit 判定前のバッチに対して `next_slot` が遅延を決定してからオーケストレータへ渡す。統合テストでは `scheduler.jitter_enabled = False` としてテストの決定性を確保している。
- integration テストは以下で運用経路をカバーしている:
  - `tests/integration/test_main_pipeline.py`: Permit 通過後にチャンネル付き文字列バッチを送出できることと Permit ゲート呼び出しを追跡。
  - `tests/integration/test_permit_bridge.py`: `PermitGate` 経由の送信成否に応じたメトリクスタグ（`retryable` 含む）を直接検証。
  - `tests/runtime/test_setup_runtime_dedupe.py`: `dedupe.enabled=False` 時は `_PassthroughDedupe` シムが選択され、`tests/runtime/test_setup_runtime_dedupe.py::test_setup_runtime_disables_dedupe_when_disabled` で Permit 判定前段の `_PassthroughDedupe.permit` が任意のメッセージに対して常に `True` を返し、重複抑止が完全にバイパスされることを確認する。
  - `tests/integration/runtime_weekly_report/`: 週次サマリジョブの曜日スケジュールおよびテンプレート整形を `weekly_snapshot` / `generate_weekly_summary` の協調呼び出しで検証。
    - `test_scheduler.py`:
      - `test_weekly_report_respects_weekday_schedule`: `Scheduler` が平日スケジュールを順守しつつ設定された「Tue/Thu 09:00」が火曜・木曜の 09:00 実行のみを許可することを 1 ケースで検証する。
      - `test_weekly_report_permit_override_applies_to_dispatch`: Permit 上書き設定が dispatch 送信先へ反映され、指定されたプラットフォーム/チャンネル/ジョブで実行されることを検証。
    - `test_templates.py`:
      - `test_weekly_report_config_template_regression`: テンプレート改変が週次サマリ生成へ確実に反映されることを保証。
      - `test_weekly_report_template_line_context`: テンプレート行整形（行コンテキストの付与）が期待どおりに適用されることを固定。
    - `tests/features/test_report.py`: テンプレート定義どおりにタイトル/行/フッタの整形が行われ、成功率タグや重大度タグがスナップショットから算出されること、および失敗閾値超過時はフェイルオーバー本文へ切り替わることを単体レベルで保証する。
    - `tests/config/test_settings_example_report.py`: `config/settings.example.json` の週次サマリ設定がテンプレートプレースホルダ（`{label}` など）と通知先チャンネルを正しく保持し、実データを流し込んでもテンプレートが破綻しないことを確認して設定リグレッションを防止する。
    - `test_fallbacks.py`:
      - `test_weekly_report_skips_self_success_rate`: 自身の成功率が週次サマリから除外されることを検証し、自己スコア混入を防止。
    - `tests/integration/test_runtime_dm_digest.py`: DM ダイジェストジョブが dispatch キューを汚さないことを確認する専用テスト（パイプライン経由の dispatch を通さず、スケジューラへの push 抑止にフォーカスする）。Permit 通過後に直接送信する経路は `tests/integration/runtime_multicontent/test_dm_digest.py` が多経路統合テストとして担保するため、本テストは責務を分離している。
      - `test_dm_digest_job_returns_none_and_skips_dispatch`: キュー未追加と dispatch スキップを保証し、dispatch キューを汚さないことを固定化する。
      - `tests/integration/test_runtime_dm_digest.py::test_dm_digest_job_denied_by_permit`: Permit 拒否時に DM 送信を抑止しつつ、`dm_digest_permit_denied` ログイベントへ `retryable=False` と `job="dm_digest-denied"`（PermitDecision 由来サフィックス）を記録していることを検証する。
    - `tests/integration/weather_engagement/`: Weather Engagement の履歴参照と抑止/再開制御を代表ケース（`test_cache_control.py`・`test_cooldown_coordination.py`・`test_engagement_calculation.py`）で end-to-end に検証し、履歴キャッシュの同期と Permit 前の投稿判断を保証する。
      - Weather Engagement の履歴連携を `history_provider` 呼び出し・再開スコアで確認。
    - `tests/integration/test_runtime_reload.py`: 設定リロード時の差分検出と監査ログ出力をファイル I/O 越しに確認し、リロードシグナル後にランタイムへ副作用なく設定差分を適用できることを担保する。
      - 設定再読込時の差分ログ出力（差分なしケースはログ抑止）。
  - `tests/integration/runtime_multicontent/test_pipeline.py`: runtime_multicontent パイプライン移行履歴の LEGACY チェックリストであり、後継となる `test_pipeline_weather.py`・`test_pipeline_news.py`・`test_pipeline_omikuji.py`・`test_pipeline_dm_digest.py`・`test_pipeline_weekly_report.py` を追跡しつつ登録・dispatch 条件の移行完了スナップショットを同一段落で記録する。
  - `tests/integration/runtime_multicontent/test_pipeline_weather.py`: Weather ジョブがチャンネル override（`weather-alerts`）付きで登録され、無効設定時はジョブ未登録となり、カスタムジョブ名と override 渡しがビルダー・キュー push・enqueue へ伝播することを複数ケースで検証。
  - `tests/integration/runtime_multicontent/test_pipeline_news.py`: News ジョブがニュース専用チャンネルで登録され、ビルダー呼び出し後に `news` ジョブが同チャンネルでキュー push / オーケストレータ enqueue されることを保証。
  - `tests/integration/runtime_multicontent/test_pipeline_omikuji.py`: おみくじジョブが `user_id="fortune-user"` をビルダーへ渡したうえで登録され、一般チャンネル宛てに `omikuji` ジョブとしてキュー push / enqueue される経路を追跡。
  - `tests/integration/runtime_multicontent/test_pipeline_dm_digest.py`: DM ダイジェストジョブがスケジューラへ登録された後もキュー push や dispatch が発生しないことを保証（`test_dm_digest_job_registers_without_enqueue` でジョブ登録直後も scheduler queue への push や dispatch が発火しないことを検証）。
  - `tests/integration/runtime_multicontent/test_pipeline_weekly_report.py`: 週次レポートジョブが `MetricsService.collect_weekly_snapshot` と `metrics_module.weekly_snapshot` を通じてテンプレート整形されたコンテンツを送出することを後継テストとして保証。
  - `tests/integration/runtime_multicontent/test_dm_digest.py`: DM 専用ジョブが Permit 通過後にキューへ積まず直接送信する経路を担保する（`tests/integration/test_runtime_dm_digest.py` で確認済みの dispatch キュー無汚染・Permit 拒否監査ログと責務分担）。
    - `test_dm_digest_job_sends_without_scheduler_queue`: スケジューラキューの件数が変化しないまま sender が DM を送ることを検証し、Permit 通過時に scheduler queue を経由しない直接送信保証を明示する。
  - `tests/config/test_settings_example_cooldown.py`: `config/settings.example.json` の `cooldown.jobs` が Weather/News/Omikuji/DM Digest の 4 ジョブのみで構成されることを検証し、設定ファイルとランタイム挙動の整合を固定する。`tests/config/test_settings_example_cooldown.py::test_cooldown_jobs_match_expected_set` で設定ファイルのキー集合が想定セットに一致することを直接照合し、外れ値ジョブの混入を防止する。
- `tests/integration/runtime_multicontent/test_providers.py::test_setup_runtime_resolves_string_providers`: 動的に生成した `tests.integration.fake_providers` モジュールへ `news_feed` / `news_summary` / `dm_logs` / `dm_summary` / `dm_sender` を束ねた `SimpleNamespace` を登録し、`monkeypatch.setitem(sys.modules, module_name, provider_module)` で差し込んだ状態で `module:attr` 形式のプロバイダ文字列が `resolve_object` により正しく解決されることを確認する。
- `tests/integration/test_runtime_multicontent_failures.py`: [OPS-10] で追加された異常系結合テスト。Permit 拒否やプロバイダ障害時の再送挙動を再現し、News/おみくじ/DM ダイジェスト経路の例外処理を網羅済み。→ 実装済み
- `tests/integration/test_runtime_news_cooldown.py`: News ジョブがクールダウン継続中はエンキューを抑止し、Permit 呼び出しを行わないことを確認。
- 残課題（OPS-B01〜OPS-B07／UX-B01）の詳細は直後の「### 残課題」節および最新バックログ（`docs/tasks/backlog.md`）を参照。

## Sprint 1: Sender堅牢化 & オーケストレータ（完了）
- [SND-01] Discord/Misskey RetryPolicy（`adapters/discord.py`, `adapters/misskey.py`）は指数バックオフとリトライ上限ログを実装済みで、429/Retry-After と非リトライ判定を `tests/adapters/test_retry_policy.py::test_max_attempts` が固定化している。
- [SND-02] Permit ゲート導入（`core/arbiter.py` など）はチャンネル別クォータ・メトリクスタグの更新を実装済みで、`tests/core/test_quota_gate.py` と `tests/integration/test_permit_bridge.py` が拒否理由タグと Permit 通過メトリクスを検証している。
- [SCH-01] CoalesceQueue（`core/scheduler.py`）は近接メッセージ併合と即時フラッシュを完了しており、`tests/core/test_coalesce_queue.py::test_coalesce_queue_separates_incompatible_batches` ほかテーブル駆動ケースで優先度逆転ガードを保証している。
- [SCH-02] ジッタ適用（`core/scheduler.py`）は送信時刻へランダムオフセットを付与する実装が完了し、`tests/core/test_scheduler_jitter.py::test_scheduler_applies_jitter` / `::test_scheduler_immediate_when_jitter_disabled` / `::test_scheduler_jitter_respects_range` が境界レンジと有効/無効切替を確認している。
- [OPS-01] 構造化ログ/監査（`adapters/*`、オーケストレータ公開エントリ `core/orchestrator/__init__.py` とワーカープロセッサ `core/orchestrator/processor.py`。旧 `core/orchestrator.py`（削除済み）から分割済み）は送信結果と Permit 連携ログを JSON へ記録する実装を完了し、`tests/core/structured_logging/test_success.py` が成功ログと相関 ID を検証し、`tests/core/structured_logging/test_failure.py` が失敗ログとエラー型タグを固定し、`tests/core/structured_logging/test_permit.py` が Permit 拒否ログとメトリクス増分を追跡し、`tests/core/structured_logging/test_duplicate.py` が重複スキップ時のログとメトリクスタグ整合を担保する。
- [OPS-05] CI パイプライン整備（`.github/workflows/ci.yml`）は `ruff check`・`mypy src`・`pytest -q` の並列運用と Slack 通知ガードを導入済みで、ワークフロー YAML の共通セットアップ重複解消まで反映済み。
- [OPS-06] セキュリティスキャン拡充（`.github/workflows/ci.yml`）は週次 CodeQL・`pip-audit` を追加済みで、Slack 通知ガードと連動した異常検知運用へ移行済み。

## Sprint 2: UX & コンテンツ
### 完了済み
- [UX-01] Engagement 反映ロジック（`features/weather.py`、オーケストレータ公開エントリ `core/orchestrator/__init__.py` とワーカープロセッサ `core/orchestrator/processor.py`。旧 `core/orchestrator.py`（削除済み）から移行済み）: リアクション履歴をもとに出力頻度を調整し、`tests/features/test_weather_engagement.py` で閾値・クールダウン・再開シナリオを固定。
- [UX-02] ニュース配信実装（`features/news.py`）: フィード取得・要約・クールダウンを統合し、`tests/features/test_news.py` で正常系とフォールバック・クールダウン抑止を検証。
- [UX-03] おみくじ生成（`features/omikuji.py`）: テンプレートローテーションとユーザー別シードを実装し、`tests/features/test_omikuji.py` でローテーションとフォールバック挙動をカバー。
- [UX-04] DM ダイジェスト（`adapters/discord.py`, `features/*`）: 日次ダイジェストを PermitGate 経由で送信し、`tests/features/test_dm_digest.py` で集計・リトライ・PermitGate 連携を確認。

### 残課題
#### OPS（運用・基盤）
- [OPS-B01] Permit/ジッタ/バッチ閾値の運用チューニングを継続し、閾値変更時も `tests/integration/test_runtime_multicontent_failures.py` がグリーンであることと、追加メトリクス検証を `tests/infra/` に整備する。
- [OPS-B02] Permit 失敗時の再評価フロー整備を進め、再評価タイミングと監査ログをテストで固定したうえで PermitGate のレート制御と重複スキップの両立を確認する。
- [OPS-B03] Permit クォータ多段構成とバッチ再送ガードを設計し、`tests/core/test_quota_gate.py` の拡張と併せて多段クォータ導入を検証する。
- [OPS-B06] `core/orchestrator/__init__.py` のレガシーシム撤去を進め、新パスへの参照統一とテスト拡充後に CI グリーン化を達成する。
- ※ OPS-B04/B05/B07 は 2025-10-18 に完了済み（`tests/infra/metrics/test_reporting_*` 系 CI 緑化・ドキュメント同期済み）。

#### UX（体験・コンテンツ）
- [UX-B01] Engagement 指標の長期トレンド分析と Permit クォータ変動時の通知頻度調整をテストダブルで検証し、`tests/features/test_weather_engagement.py` に新ケースを追加する。

#### DOC（ドキュメント）
- [DOC-B09] 週次サマリ節のテンプレート差分説明を補完し、`tests/integration/runtime_weekly_report/` 配下テストの検証観点を整理済み。→ 完了済み（残課題なし）

## Sprint 3: 運用・可観測性
- [OPS-02] 週次サマリ（公開エントリ `core/orchestrator/__init__.py` とワーカープロセッサ `core/orchestrator/processor.py`。旧 `core/orchestrator.py`（削除済み）から移行済み、`features/report.py`）: 成果・失敗を集計し運用向けに通知。
- [OPS-03] 設定再読込ログ（`src/llm_generic_bot/config/loader.py`, `src/llm_generic_bot/runtime/setup/__init__.py`, `config/*`）: リロード時の差分検出と監査ログ。
- [OPS-04] ランタイムメトリクス（`src/llm_generic_bot/infra/metrics/aggregator.py`, `src/llm_generic_bot/infra/metrics/aggregator_state.py`, `src/llm_generic_bot/infra/metrics/reporting.py`, `src/llm_generic_bot/infra/metrics/service.py`）: `aggregator.py` が送信/Permit 事象の公開ファサードとなり、`aggregator_state.py` がロック付きの履歴保持と週次スナップショット生成を担いつつ、`service.py` のバックエンド構成と `reporting.py` の集約ロジックへ橋渡しする。
- [OPS-07] Weather 複数スケジュール（`src/llm_generic_bot/runtime/jobs/weather.py`, `tests/runtime/test_weather_jobs.py`）: 都市ごとに定義された複数スケジュールが `build_weather_jobs` で 1 件の `ScheduledJob` に複数時刻を集約し、ジョブ登録時に想定通りの時間帯へ割り当てられることを検証。

## Sprint 4: テスト強化 & 異常系整備
- [OPS-08] ジッタ境界と Permit 連携テスト: `tests/core/test_scheduler_jitter.py` の 3 ケース（`test_scheduler_applies_jitter`、`test_scheduler_immediate_when_jitter_disabled`、`test_scheduler_jitter_respects_range`）でジッタ有無の分岐と遅延レンジ境界を固定し、Permit 判定後のジョブ名維持は `test_scheduler_jitter_respects_range` が担保する。→ 実装済み
- [OPS-09] `send_duplicate_skip` のログ/メトリクス整合: 構造化ログ検証を成功/失敗/Permit 拒否/重複スキップ/メトリクスへ分割し、
  - `tests/core/structured_logging/test_success.py` が成功ログと相関 ID・Permit 判定後のメトリクスタグを固定し、
  - `tests/core/structured_logging/test_failure.py` が失敗ログとエラー種別タグ、リトライ可否の記録を保証し、
  - `tests/core/structured_logging/test_permit.py` が Permit 拒否ログ・拒否理由タグ・メトリクス増分を検証し、
  - `tests/core/structured_logging/test_duplicate.py` が重複スキップ時の構造化ログと `send_duplicate_skip` メトリクスタグ整合を担保し、
  - `tests/core/structured_logging/test_metrics.py` が `send.duration` などメトリクス観測値の秒単位タグを固定する。分割後も `tests/core/test_structured_logging.py` はチェックリスト保持用シムとして残し、分担状況のレガシー互換性を追跡する。→ 実装済み
- [OPS-10] News/おみくじ/DM 異常系結合テスト: `tests/integration/test_runtime_multicontent_failures.py` の `test_permit_denied_records_metrics` / `test_cooldown_resume_allows_retry` / `test_summary_provider_retry_and_fallback` / `test_dm_digest_permit_denied_records_metrics` が Permit 拒否メトリクス、クールダウン解除後の再送成功、サマリーリトライとフォールバック記録、DM ダイジェスト拒否時の送信スキップを週次スナップショットまで確認。→ 実装済み

## テストロードマップ
- 現状認識:
  - リトライ: `tests/adapters/test_retry_policy.py` で Discord/Misskey の 429/Retry-After、指数バックオフ、非リトライ判定までカバー済み。残課題だった `_structured_log` の JSON フィールド（`llm_generic_bot.adapters._retry`）スナップショットは `tests/adapters/test_retry_policy.py::test_retry_logging_snapshot` で完了し、リトライ限界到達時の監査属性欠落を防止済み。
  - 併合: `tests/core/test_coalesce_queue.py` で窓内併合、閾値即時フラッシュ、単発バッチを検証済み。残課題だった `CoalesceQueue` の優先度逆転ガードは `tests/core/test_coalesce_queue.py::test_coalesce_queue_separates_incompatible_batches` で完了し、`llm_generic_bot.core.queue` のマルチチャンネル分離・`pop_ready` ソート安定性もテーブル駆動で確認済み。
  - ジッタ: `tests/core/test_scheduler_jitter.py` で `Scheduler` のジッタ有無と `next_slot` 呼び出しを制御できており、同テストでジッタ範囲の最小/最大境界と Permit 連携も固定済み（[OPS-08] 完了）。
  - 構造化ログ: `tests/core/structured_logging/test_success.py` が成功ログと相関 ID、`tests/core/structured_logging/test_failure.py` が失敗ログとエラー種別タグ、`tests/core/structured_logging/test_permit.py` が Permit 拒否ログと拒否理由タグ、`tests/core/structured_logging/test_duplicate.py` が重複スキップ時のログと `send_duplicate_skip` メトリクスタグ、`tests/core/structured_logging/test_metrics.py` が `send.duration` を含む秒単位タグをそれぞれ固定済み（[OPS-09] 完了）。分割前の互換追跡にはチェックリスト保持用シム `tests/core/test_structured_logging.py` を残置し、役割分担の進捗を記録している。
- Sprint 1（完了）: `tests/adapters/test_retry_policy.py::test_retry_logging_snapshot` で JSON 監査フィールドを固定し、`tests/core/test_coalesce_queue.py::test_coalesce_queue_separates_incompatible_batches` などのテーブル駆動ケースで優先度逆転ガードを拡張済み。Permit 拒否理由タグは `tests/core/test_quota_gate.py::test_quota_denial_records_metrics_and_logs` と `tests/integration/test_permit_bridge.py::test_orchestrator_accepts_permit_gate_with_retryable` が `llm_generic_bot.core.arbiter` のタグ整合を保証している。また、`tests/runtime/test_setup_runtime_dedupe.py::test_setup_runtime_disables_dedupe_when_disabled` と `tests/config/test_settings_example_cooldown.py::test_cooldown_jobs_match_expected_set` が設定値に応じたランタイム差し替えと設定ファイル整合を完了済みとして記録する。
- Sprint 2: `tests/features/test_news.py`, `tests/features/test_omikuji.py`, `tests/features/test_dm_digest.py` を追加済み。正常系とフォールバック、PermitGate 連携はカバーしており、ジッタ境界と異常系結合テストは OPS-08/OPS-10 で完遂。
- Sprint 3: ランタイムメトリクスの結合テストは `tests/infra/metrics/test_reporting_freeze_time.py`・`tests/infra/metrics/test_reporting_recording_metrics.py`・`tests/infra/metrics/test_reporting_service.py` へ分割済みで、旧単一ファイル版はレガシーシムとして互換維持用に残存。並行して `tests/core/structured_logging/test_metrics.py` を拡張し、`MetricsRecorder.observe` 呼び出しの単位検証を追加する。

### 参照タスク
- Sprint 1 詳細: [`docs/tasks/sprint1.md`](tasks/sprint1.md)
- Sprint 2 詳細: [`docs/tasks/sprint2.md`](tasks/sprint2.md)
- Sprint 3 詳細: [`docs/tasks/sprint3.md`](tasks/sprint3.md)
- Sprint 4 詳細: [`docs/tasks/sprint4.md`](tasks/sprint4.md)
