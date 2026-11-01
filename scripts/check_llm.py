"""Check the LLM setup from the terminal:  python -m scripts.check_llm"""
from doctor_leads.config import load_config
from doctor_leads.llm import LLMClient, LLMError


def main() -> None:
    cfg = load_config()
    print(f"Provider: {cfg.llm_provider}\nModel:    {cfg.llm_model}\nKey:      {cfg.llm_key_masked}")
    llm = LLMClient(cfg, max_retries=1)
    try:
        models = llm.list_models()
    except LLMError as e:
        print(f"\nFAILED to list models: {e}")
        return
    print(f"\nModels available to your key ({len(models)}):")
    for m in models:
        print(("  * " if m == cfg.llm_model else "    ") + m)
    if cfg.llm_model not in models:
        print(f"\n'{cfg.llm_model}' isn't available. Set LLM_MODEL=<one of the above> in .env")
        return
    try:
        print("\nTest call:", llm.complete_json('Reply with JSON {"ok": true}.', "ping"))
        print("All good.")
    except LLMError as e:
        print(f"\nTest call FAILED: {e}")


if __name__ == "__main__":
    main()
