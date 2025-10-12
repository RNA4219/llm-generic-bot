import pytest

from llm_generic_bot.adapters.discord import DiscordSender


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)


def test_token_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")

    sender = DiscordSender(token=None)

    assert sender.token == "env-token"
    assert isinstance(sender.token, str)
