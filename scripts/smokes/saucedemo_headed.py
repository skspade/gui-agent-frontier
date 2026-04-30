"""
Saucedemo cart-icon click test (browser-use harness path).

Mirrors scripts/custom_agent_tasks/saucedemo_headed.py — same task,
ported here so the browser-use smoke runner can drive it. Phase 11
observed a 30+ step loop on the nested-anchor cart icon in this path.
"""

TASK = (
    "Open https://www.saucedemo.com/ and log in with username "
    "'standard_user' and password 'secret_sauce'. Once on the inventory "
    "page, add the FIRST item to the cart, then click the cart icon in "
    "the top-right to navigate to the cart page. If you cannot complete "
    "the task, report what blocked you rather than pretending to succeed."
)

MAX_STEPS = 25
HEADLESS = False
MAX_ACTIONS_PER_STEP = 2

# Task class (see docs/thesis.md): A — known-site DOM short-horizon
TASK_CLASS = "A"
