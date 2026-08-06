import os

# Leave empty to disable proxying. Never commit new proxy credentials here.
PROXY_URL = os.getenv("PROXY_URL", "")
REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "30"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
F1_SETUP_LAPS_URL = os.getenv(
    "F1_SETUP_LAPS_URL", "https://www.f1laps.com/f1-26/setups/"
)
EA_SETUP_URL = os.getenv("EA_SETUP_URL", "")