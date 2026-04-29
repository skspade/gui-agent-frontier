"""Saucedemo headed: same task as saucedemo_headless, run in headed mode.

Disambiguates the Phase 11 cart-icon failure: if this run reaches
/cart.html, the headless run's failure was the --headless=new vs nested
anchor interaction. If it fails the same way, it's the model's coord
precision.
"""
TASK = (
    "Log in to saucedemo.com using username 'standard_user' and password 'secret_sauce'. "
    "Once on the inventory page, add the first item to the cart, then click the cart icon "
    "in the top right to navigate to the cart page. If you cannot complete the task, "
    "report what blocked you rather than pretending to succeed."
)
START_URL = "https://www.saucedemo.com/"
HEADLESS = False
MAX_STEPS = 25
