"""R1: long-horizon saucedemo flow on the custom CDP agent (Phase 14).

Same 9-checkpoint task as scripts/smokes/saucedemo_full_checkout.py, ported
to the custom_agent_tasks format. Runs `scripts/custom_agent.py` against
UI-Venus-1.5-8B (Q6_K) to test the harness-fit hypothesis from
docs/plans/2026-04-29-harness-fit-research.md: does the existing coord-first
CDP harness reach more checkpoints than browser-use's index-based contract?

Compare verified score against Phase 13 S1/S3 baselines (8B baseline 1/9,
Holo2 30B 2/9 median).
"""

TASK = (
    "Open https://www.saucedemo.com and complete the following checkout "
    "flow. Treat the steps as a checklist; do them in order and verify "
    "each before moving on.\n"
    "1. Login with username 'standard_user' and password 'secret_sauce'.\n"
    "2. Sort the products by 'Price (low to high)' using the dropdown.\n"
    "3. After sorting, identify the THIRD CHEAPEST item (the third "
    "product from the left/top of the sorted grid) and add it to the "
    "cart.\n"
    "4. Then add the item literally named 'Sauce Labs Backpack' to the "
    "cart as well.\n"
    "5. Open the cart by clicking the cart icon in the top-right.\n"
    "6. In the cart, REMOVE the item that you added in step 3 (the "
    "third-cheapest one), so only Sauce Labs Backpack remains.\n"
    "7. Click 'Checkout', then fill First Name='Test', Last Name='User', "
    "Postal Code='94000'. Click 'Continue'.\n"
    "8. On the overview page, verify the item total matches Sauce Labs "
    "Backpack's price ($29.99). Report the displayed total in your "
    "final answer.\n"
    "9. Click 'Finish' and verify the page shows 'Thank you for your "
    "order!'. Report 'PASS' or 'FAIL' as the very first word of your "
    "final answer.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why rather than pretending to succeed."
)
START_URL = "https://www.saucedemo.com/"
HEADLESS = False
MAX_STEPS = 40

# Task class (see docs/thesis.md): B — known-site DOM long-horizon w/ grounding pinches
TASK_CLASS = "B"
