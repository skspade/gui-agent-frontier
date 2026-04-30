"""Phase 18: minimal add-by-name probe for MAI-UI on saucedemo.

Isolates the CP4 failure observed in Phase 17 follow-up (n=3 reruns):
both deterministic-twin runs added Bolt T-Shirt instead of Backpack
when asked for "Sauce Labs Backpack". This task removes the sort
step and the 3rd-cheapest ordinal so that only one variable is left
under test — can the model click the correct Add-to-cart button when
the target item is named explicitly and visible in default order?

Saucedemo default sort is A→Z, which puts Sauce Labs Backpack at
top-left of the 2-col inventory grid (the easiest possible target
for this 6-item layout). If MAI-UI fails this, the wall is at the
add-by-name action level, not the grid-ordinal-reasoning level.

Pass = cart at /cart.html contains exactly Sauce Labs Backpack and
nothing else. Model is asked to put PASS / FAIL as the first word
of its final answer for mechanical scoring; ground truth is the
final screenshot.
"""

TASK = (
    "Open https://www.saucedemo.com and complete the following:\n"
    "1. Login with username 'standard_user' and password 'secret_sauce'.\n"
    "2. On the inventory page (default sort), click the 'Add to cart' "
    "button for the item literally named 'Sauce Labs Backpack'. Do NOT "
    "add any other item.\n"
    "3. Click the cart icon in the top-right to open the cart.\n"
    "4. Verify the cart contains exactly 'Sauce Labs Backpack' and no "
    "other items. Report 'PASS' or 'FAIL' as the very first word of "
    "your final answer, followed by the list of item names you see in "
    "the cart.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why rather than pretending to succeed."
)
START_URL = "https://www.saucedemo.com/"
HEADLESS = False
MAX_STEPS = 25

# Task class (see docs/thesis.md): B — known-site DOM, isolates B's add-by-name precision sub-cliff
TASK_CLASS = "B"
