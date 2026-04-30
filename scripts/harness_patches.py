"""
Generic harness defensive patches.

Some local VLMs emit text actions with stray surrounding whitespace
(e.g. UI-Venus-1.5-30B-A3B at Q3_K_M typed `"standard_user "` and
`"secret_sauce "` for saucedemo, breaking the exact-match login). The
fix is generic — any model that emits clean text is unaffected — so
it's a defensive harness improvement, not model-specific tuning.

Apply via `import harness_patches` at the top of any smoke runner. The
import has the side effect of installing the patches.

Hook point: `Registry.execute_action` is the entry where browser-use
constructs `InputTextAction(**params)` — patching the dict before
construction is the only spot that catches all paths (the param_model's
`model_validate` classmethod is bypassed by direct **kwargs construction
in registry/service.py:349).
"""
from browser_use.tools.registry.service import Registry

_orig_execute_action = Registry.execute_action


async def _stripping_execute_action(self, action_name, params, **kwargs):
    if (
        action_name == "input"
        and isinstance(params, dict)
        and isinstance(params.get("text"), str)
    ):
        params = {**params, "text": params["text"].strip()}
    return await _orig_execute_action(self, action_name, params, **kwargs)


Registry.execute_action = _stripping_execute_action
