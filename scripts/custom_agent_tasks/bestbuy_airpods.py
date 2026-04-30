"""Phase 18: Best Buy search-and-add — generalization probe for the
"search → PDP → add → verify" flow proven on IKEA BILLY.

Sibling of ikea_billy.py with a different retailer. Best Buy's country-
selector overlay (US / Canada) on first visit is a close analogue of
IKEA's country/store overlay, so the dismiss-overlay step exercises the
same pattern. Past that, the search bar / PDP / Add-to-Cart / cart-icon
layout is canonical e-commerce.

"AirPods" is intentionally generic (Pro, 4, Max all match) — the cart-
builder use case doesn't care which AirPods variant ends up in the cart,
just that *an* AirPods item does. Mirrors BILLY's tolerance for variant
ambiguity (size, color, doors).

Pass = cart contains an AirPods-named item. Final-screenshot ground
truth.
"""

TASK = (
    "Open https://www.bestbuy.com/ and complete the following:\n"
    "1. If any country selector ('United States' / 'Canada'), cookie "
    "consent banner, location prompt, or promotional overlay appears, "
    "dismiss it (pick United States, accept, or close — whichever is "
    "fastest).\n"
    "2. Click the search bar at the top of the page and type 'AirPods', "
    "then press Enter to search.\n"
    "3. From the search results, click on an AirPods product card "
    "(any AirPods model — Pro, 4, Max — is fine) to open its product "
    "detail page. Verify the page title or product name actually "
    "contains 'AirPods' before proceeding.\n"
    "4. On the product detail page, click the 'Add to Cart' button. "
    "If a protection-plan / Geek Squad upsell modal appears after "
    "adding, dismiss it (close, skip, or 'No thanks'). If the button "
    "is below the visible area, scroll down to bring it into view "
    "first.\n"
    "5. Click the cart icon in the top-right of the page to open the "
    "cart.\n"
    "6. Verify the cart contains an AirPods-named item. Report 'PASS' "
    "or 'FAIL' as the very first word of your final answer, followed "
    "by the list of item names you see in the cart.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why rather than pretending to succeed."
)
START_URL = "https://www.bestbuy.com/"
HEADLESS = False
MAX_STEPS = 60
