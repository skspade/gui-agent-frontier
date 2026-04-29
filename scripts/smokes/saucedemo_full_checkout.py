"""
Long-horizon saucedemo flow for the 5-stack MoE bake-off.

Nine checkpoints, three discriminators baked in early so a stack that
fails on one still yields a graded score:
  - step 3-4: ordinal visual reasoning (sort by price + pick the third
    cheapest).
  - step 4: text grounding (add by literal name "Sauce Labs Backpack").
  - step 6: nested-anchor cart manipulation (the Phase 11 failure mode
    that broke the merged 8B in headed Chromium).

Pass = "Thank you for your order!" page reached with the correct final
cart contents (Sauce Labs Backpack only). Partial-pass = highest
checkpoint number reached. The model is asked to put PASS / FAIL as the
very first word of its final answer to make grading mechanical.

Use with `MAX_TOKENS=8192` env (matches Phase 12 decision for non-Venus
models with longer thinking blocks).

See docs/plans/2026-04-29-moe-stack-comparison-design.md.
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

MAX_STEPS = 40
HEADLESS = False
MAX_ACTIONS_PER_STEP = 2
