"""Custom CDP agent package.

The harness registry is here (rather than in scripts/custom_agent.py) so
both the run loop and probe scripts can import it without colliding on the
`scripts.custom_agent` name (which resolves to this package, not the
sibling `custom_agent.py` script).
"""

# Maps llama-server model alias -> harness path. Edit when adding a new
# model family. See docs/findings.md (per-model contracts) for what each
# harness expects.
MODEL_HARNESS_REGISTRY = {
    "ui-venus-1.5-8b": "uivenus",
    "ui-venus-1.5-30b-a3b": "uivenus",
    "holo3-35b-a3b": "holo3",
    # Holo1.5-7B emits absolute pixels in the smart_resize'd image — the
    # canonical surfer-h-cli contract. Verified by model_probe on
    # 2026-04-30: 1/1 inside-box on saucedemo username.
    "holo1.5-7b": "holo1_5",
    # Holo2-30B-A3B emits 0-1000 normalized coords like Holo3 / UI-Venus,
    # NOT the surfer-h-cli absolute-pixel contract its sibling Holo1.5
    # follows. Verified by model_probe on 2026-04-30: holo1_5 path missed
    # by 144px; holo3 path lands inside the username field.
    "holo2-30b-a3b": "holo3",
    "mai-ui-8b": "toolcall",
    "bu-30b-a3b-preview": "toolcall",
}


def harness_for(model: str, override: str | None = None) -> str:
    """Resolve a model alias to a harness name. `override` (HARNESS env)
    wins; unknown models fall back to 'uivenus'."""
    if override:
        return override
    return MODEL_HARNESS_REGISTRY.get(model, "uivenus")
