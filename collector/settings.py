import os

try:
    from dotenv import load_dotenv
except ImportError:
    # VS Code loads .env through python.envFile. Keeping dotenv optional also
    # allows test discovery before the project's dependencies are installed.
    pass
else:
    load_dotenv()

def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


# Credentials must only exist in PROXY_FILE, mounted at runtime.
PROXY_FILE = os.getenv("PROXY_FILE", "proxies")
PROXY_ENABLED = _bool_env("PROXY_ENABLED", False)
PROXY_ALLOW_DIRECT_FALLBACK = _bool_env(
    "PROXY_ALLOW_DIRECT_FALLBACK",
    False,
)
COLLECTOR_CONCURRENCY = int(os.getenv("COLLECTOR_CONCURRENCY", "4"))
COLLECTOR_LOG_RECORDS = _bool_env("COLLECTOR_LOG_RECORDS", False)
COLLECTOR_LOG_RESULTS = _bool_env("COLLECTOR_LOG_RESULTS", False)
MAX_REQUESTS_PER_MINUTE = int(
    os.getenv(
        "MAX_REQUESTS_PER_MINUTE",
        os.getenv("REQUESTS_PER_MINUTE", "100"),
    )
)
MAX_REQUESTS_PER_MINUTE_PER_PROXY = int(
    os.getenv("MAX_REQUESTS_PER_MINUTE_PER_PROXY", "10")
)
MAX_CONCURRENT_REQUESTS_PER_PROXY = int(
    os.getenv("MAX_CONCURRENT_REQUESTS_PER_PROXY", "1")
)
PROXY_FAILURE_THRESHOLD = int(os.getenv("PROXY_FAILURE_THRESHOLD", "3"))
PROXY_COOLDOWN_SECONDS = int(os.getenv("PROXY_COOLDOWN_SECONDS", "120"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
# Backward-compatible alias used by collectors that override the HTTP rate.
REQUESTS_PER_MINUTE = MAX_REQUESTS_PER_MINUTE
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
METRICS_ENABLED = _bool_env("METRICS_ENABLED", True)
METRICS_BIND_ADDRESS = os.getenv("METRICS_BIND_ADDRESS", "0.0.0.0")
COLLECTOR_METRICS_PORT = int(os.getenv("COLLECTOR_METRICS_PORT", "9102"))
