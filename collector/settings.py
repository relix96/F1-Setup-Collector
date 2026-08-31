import os

try:
    from dotenv import load_dotenv
except ImportError:
    # VS Code loads .env through python.envFile. Keeping dotenv optional also
    # allows test discovery before the project's dependencies are installed.
    pass
else:
    load_dotenv()

# Leave empty to disable proxying. Never commit new proxy credentials here.
PROXY_URL = os.getenv("PROXY_URL", "")
REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "30"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
F1_SETUP_LAPS_URL = os.getenv(
    "F1_SETUP_LAPS_URL", "https://www.f1laps.com/f1-26/setups/"
)
EA_SETUP_URL = os.getenv("EA_SETUP_URL", "")
MONGODB_SANDBOX_URI = os.getenv(
    "MONGODB_SANDBOX_URI", "mongodb://localhost:27017"
)
MONGODB_PRODUCTION_URI = os.getenv("MONGODB_PRODUCTION_URI", "")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "collector")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "F1")
TEST_MONGODB_ENV = os.getenv("TEST_MONGODB_ENV", "sandbox")
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_SETUP_STREAM = os.getenv("REDIS_SETUP_STREAM", "setup-imports")
