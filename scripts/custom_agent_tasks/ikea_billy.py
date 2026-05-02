"""Phase 18: IKEA search-and-add for BILLY bookcase.

Sibling of ikea_search_add.py with a different product. BILLY has been
IKEA's flagship bookcase for ~45 years and is always in stock — picking
it removes the "product not in search results" failure that hit the
BLAHAJ run on both MAI-UI-8B and UI-Venus-30B-A3B.

BILLY has multiple variants (size, color, with/without doors). The
search may return either the category page or a specific PDP. The
agent should pick a plausible BILLY result and proceed; the cart-builder
use case doesn't care about the exact variant, just that *a* BILLY
bookcase ends up in the bag.

Pass = bag contains a BILLY-named item. Final-screenshot ground truth.
"""

TASK = (
    "Open https://www.ikea.com/us/en/ and complete the following:\n"
    "1. If any cookie consent banner or country/store overlay appears, "
    "dismiss it (accept or close, whichever is fastest).\n"
    "2. Click the search bar at the top of the page and type 'BILLY "
    "bookcase', then press Enter to search.\n"
    "3. From the search results, click on a BILLY bookcase product card "
    "to open its product detail page. Verify the page title or product "
    "name actually says 'BILLY' before proceeding.\n"
    "4. On the product detail page, click the 'Add to bag' button. If "
    "the button is below the visible area, scroll down to bring it into "
    "view first.\n"
    "5. Click the bag/cart icon in the top-right of the page to open "
    "the bag.\n"
    "6. Verify the bag contains a BILLY-named item. Report 'PASS' or "
    "'FAIL' as the very first word of your final answer, followed by "
    "the list of item names you see in the bag.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why rather than pretending to succeed."
)
START_URL = "https://www.ikea.com/us/en/"
HEADLESS = False
MAX_STEPS = 60

# Task class (see docs/thesis.md): D — novel real-world e-commerce (overlay handling, variant-tolerant)
TASK_CLASS = "D"

# Cart-state final check: agent must leave ≥1 item in the bag at run end.
# Without this, models that confabulate "I added a BILLY to the cart" after
# the cart reverts to empty would score pass on outcome=done alone. The
# runner reads cart-state via verify_cart_state() after the agent declares
# done; if cart_count < MIN_FINAL_CART_COUNT, outcome is downgraded to
# stuck_premature_done.
MIN_FINAL_CART_COUNT = 1
