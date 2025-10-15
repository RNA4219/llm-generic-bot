# タスク記録

- 2025-10-15: README の週次サマリ参照先を `runtime/setup/__init__.py` へ更新し、構成ツリーへ `core/orchestrator/processor.py` と `infra/metrics/aggregator*.py` を追記。
- 2025-10-14: Backlog OPS-B02 / UX-B01 の対象領域に `core/orchestrator/processor.py` を追記し、他タスクの参照揺れを防止。
- 2025-10-14: Sprint3 ドキュメントの OPS-02/OPS-04 を `core/orchestrator/processor.py` へ更新し、Permit 判定/送信記録/メトリクス通知の責務を追記。
- 2025-10-14: runtime/setup プロファイル有効判定を `is_enabled` へ統一し、`pytest tests/runtime/test_setup_runtime_profiles.py -q` グリーンを確認予定。
# TASKS

- 2025-10-13: docs/tasks/sprint1.md の SND-02 / OPS-01 を `core/orchestrator/processor.py` 参照へ更新済み。
- 2025-10-15: runtime/setup/runtime_helpers.py の送信プロファイル判定を `is_enabled` へ統一し、`pytest tests/runtime/test_setup_sender.py -q` → `mypy` → `ruff` の順で緑化確認。
