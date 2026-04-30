"""Phase 18: real e-commerce smoke — search-and-add-to-bag on IKEA.

The realistic shopping-cart-builder use case: hand the agent a product
name and have it search, navigate to PDP, and add to bag. No sort-then-
pick-Nth ordinal reasoning (which Phase 17 follow-up showed MAI-UI can't
do); just text-grounding through search.

Target: BLAHAJ (the shark plush) — single SKU, no size/color variants,
canonical IKEA search target. Picking a no-variant item isolates "search-
and-add" from "configure-then-add".

Pass = cart contains BLAHAJ. Cookie banner / overlay handling is in-
scope (real e-commerce sites have these); the model has to dismiss
whatever IKEA renders.
"""

TASK = (
    "Open https://www.ikea.com/us/en/ and complete the following:\n"
    "1. If any cookie consent banner or country/store overlay appears, "
    "dismiss it (accept or close, whichever is fastest).\n"
    "2. Click the search bar at the top of the page and type 'BLAHAJ', "
    "then press Enter to search.\n"
    "3. From the search results, click the BLAHAJ shark plush product "
    "card to open its product detail page.\n"
    "4. On the product detail page, click the 'Add to bag' button.\n"
    "5. Click the bag/cart icon in the top-right of the page to open "
    "the bag.\n"
    "6. Verify the bag contains BLAHAJ. Report 'PASS' or 'FAIL' as the "
    "very first word of your final answer, followed by the list of "
    "item names you see in the bag.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why rather than pretending to succeed."
)
START_URL = "https://www.ikea.com/us/en/"
HEADLESS = False
MAX_STEPS = 60

# Task class (see docs/thesis.md): D — novel real-world e-commerce (search-and-add, single SKU)
TASK_CLASS = "D"
