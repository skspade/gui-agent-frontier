"""
Generic harness defensive patches.

Some local VLMs emit text actions with stray surrounding whitespace
(e.g. UI-Venus-1.5-30B-A3B at Q3_K_M typed `"standard_user "` and
`"secret_sauce "` for saucedemo, breaking the exact-match login). The
fix is generic — any model that emits clean text is unaffected — so
it's a defensive harness improvement, not model-specific tuning.

Apply via `import harness_patches` at the top of any smoke runner. The
import has the side effect of installing the patches.

The patch wraps `InputTextAction.model_validate` to strip whitespace
from the `text` field before Pydantic constructs the action. This is
the entry point browser-use uses when parsing action JSON from the
LLM, so the trim happens before the field reaches the input handler.
"""
from browser_use.tools.views import InputTextAction

_orig_model_validate = InputTextAction.model_validate


def _stripping_model_validate(obj, *args, **kwargs):
    if isinstance(obj, dict) and isinstance(obj.get("text"), str):
        obj = {**obj, "text": obj["text"].strip()}
    return _orig_model_validate(obj, *args, **kwargs)


InputTextAction.model_validate = _stripping_model_validate
