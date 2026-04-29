"""Saucedemo headless: log in, add an item, navigate to cart."""
TASK = (
    "Log in to saucedemo.com using username 'standard_user' and password 'secret_sauce'. "
    "Once on the inventory page, add the first item to the cart, then click the cart icon "
    "in the top right to navigate to the cart page. If you cannot complete the task, "
    "report what blocked you rather than pretending to succeed."
)
START_URL = "https://www.saucedemo.com/"
HEADLESS = True
MAX_STEPS = 25
