from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()

options.add_argument("--user-data-dir=/home/seluser/chrome-profile")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

# Hide automation flags
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Remote(
    command_executor="http://localhost:4444",
    options=options
)

# Patch navigator.webdriver to undefined via JS
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

driver.get("https://accounts.google.com")