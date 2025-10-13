import math

import llm_generic_bot.core.cooldown as cooldown
from llm_generic_bot.core.cooldown import CooldownGate


def test_multiplier_resets_after_window(monkeypatch):
    gate = CooldownGate(
        window_sec=10,
        mult_min=0.5,
        mult_max=10.0,
        k_rate=1.0,
        k_time=0.0,
        k_eng=0.0,
    )
    current = 100.0

    def fake_time() -> float:
        return current

    monkeypatch.setattr(cooldown.time, "time", fake_time)

    gate.note_post("platform", "channel", "job")
    boosted = gate.multiplier("platform", "channel", "job")
    assert boosted > 1.0

    current += gate.window * 2.5
    recovered = gate.multiplier("platform", "channel", "job")
    assert math.isclose(recovered, 1.0, rel_tol=1e-6)
