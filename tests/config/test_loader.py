import json
import os
import time

import pytest

from llm_generic_bot.config.loader import Settings


@pytest.mark.usefixtures("caplog")
def test_settings_preserves_previous_data_when_reload_fails(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    settings = Settings(str(config_path))
    assert settings.data == {"foo": "bar"}

    caplog.clear()
    with caplog.at_level("WARNING"):
        config_path.write_text("{ invalid", encoding="utf-8")
        os.utime(config_path, (time.time() + 1, time.time() + 1))

        assert settings.data == {"foo": "bar"}

    assert any("Failed to reload settings" in message for message in caplog.messages)
