from importlib import import_module


def test_processor_module_is_directly_importable() -> None:
    module = import_module("llm_generic_bot.core.orchestrator.processor")
    assert hasattr(module, "process")


def test_public_orchestrator_exports_forward_to_runtime_module() -> None:
    orchestrator_module = import_module("llm_generic_bot.core.orchestrator")
    orchestrator_cls = getattr(orchestrator_module, "Orchestrator")
    assert orchestrator_cls.__module__ == "llm_generic_bot.core.orchestrator.runtime"
