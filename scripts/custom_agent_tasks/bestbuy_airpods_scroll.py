"""Phase 22: Best Buy AirPods with explicit scroll-to-bottom hint.

Phase 21 Qwen-72B run on bestbuy_airpods reached the AirPods Pro 3 PDP
but then 56-step-oscillated y=0↔600 looking for Add-to-Cart, never
committing. Two competing hypotheses:
  (a) the model can't *find* the Add-to-Cart button — it's far below the
      fold, and the scroll heuristic doesn't reach it;
  (b) the iframe overlay / modal traffic on the PDP physically blocks
      the click even when the button is in view.

This variant adds an explicit "scroll to the bottom of the page" hint
before searching for Add-to-Cart, to disambiguate (a) vs (b). If the
model still fails after scrolling to bottom, that's evidence for (b)
(the overlay-wall hypothesis from Phase 19a Priority 2).

Also forbids the search-results sidebar bypass: if Best Buy ever
shows an inline "Add to cart" on a search-results card we don't want
the agent to take that shortcut — we're testing the PDP path.
"""

TASK = (
    "Open https://www.bestbuy.com/ and complete the following:\n"
    "1. If any country selector ('United States' / 'Canada'), cookie "
    "consent banner, location prompt, or promotional overlay appears, "
    "dismiss it (pick United States, accept, or close — whichever is "
    "fastest).\n"
    "2. Click the search bar at the top of the page and type 'AirPods', "
    "then press Enter to search.\n"
    "3. From the search RESULTS PAGE, click on an AirPods product card "
    "(any AirPods model — Pro, 4, Max — is fine) to OPEN ITS PRODUCT "
    "DETAIL PAGE. Do not use any 'Add to cart' button that appears on "
    "the search results page itself; you must navigate to the product "
    "detail page first. Verify the page title or product name actually "
    "contains 'AirPods' before proceeding.\n"
    "4. On the product detail page, SCROLL ALL THE WAY TO THE BOTTOM "
    "of the page first using scroll_down. The 'Add to Cart' button on "
    "Best Buy PDPs is consistently far below the fold; do not waste "
    "actions searching the top of the page. After scrolling to the "
    "bottom, scroll back up gradually and click the first 'Add to "
    "Cart' button you see for the AirPods item.\n"
    "5. If a protection-plan / Geek Squad upsell modal appears after "
    "adding, dismiss it (close, skip, or 'No thanks').\n"
    "6. Click the cart icon in the top-right of the page to open the "
    "cart.\n"
    "7. Verify the cart contains an AirPods-named item. Report 'PASS' "
    "or 'FAIL' as the very first word of your final answer, followed "
    "by the list of item names you see in the cart.\n"
    "If you cannot complete a step, report which step blocked you and "
    "why (specifically: did Add-to-Cart never appear, or did clicking "
    "it have no effect?) rather than pretending to succeed."
)
START_URL = "https://www.bestbuy.com/"
HEADLESS = False
MAX_STEPS = 60
