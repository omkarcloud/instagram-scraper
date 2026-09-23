"""Configuration for the Instagram Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    INSTAGRAM_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none — direct). Instagram answered ~140 back-to-back
                      requests from one IP without a block, so you very likely
                      don't need this. Set it only if you start seeing failures at
                      high volume, or to see posts that are region-locked where
                      you run the scraper.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

INSTAGRAM_PROXY = os.environ.get("INSTAGRAM_PROXY") or None

# A blocked request is retried on a fresh session. There is no second proxy
# to fall back to, so these stay off.
INSTAGRAM_FALLBACK_PROXY_COUNTRY = None
INSTAGRAM_DIRECT_COOLDOWN = 900


def instagram_proxy():
    """The proxy every request goes through (None = direct)."""
    return os.environ.get("INSTAGRAM_PROXY") or None


def instagram_fallback_proxy():
    """No fallback exit in the standalone package."""
    return None
