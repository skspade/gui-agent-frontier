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
    "mai-ui-8b": "toolcall",
    "bu-30b-a3b-preview": "toolcall",
    "qwen2.5-vl-72b-instruct": "qwenvl",
}


def harness_for(model: str, override: str | None = None) -> str:
    """Resolve a model alias to a harness name. `override` (HARNESS env)
    wins; unknown models fall back to 'uivenus'."""
    if override:
        return override
    return MODEL_HARNESS_REGISTRY.get(model, "uivenus")
