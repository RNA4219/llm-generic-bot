from importlib import import_module


def test_processor_module_is_directly_importable() -> None:
    module = import_module("llm_generic_bot.core.orchestrator.processor")
    assert hasattr(module, "process")
