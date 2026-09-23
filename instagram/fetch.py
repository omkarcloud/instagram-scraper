"""Instagram transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no cookie harvest (validated 2026-09-22 from direct
Indian egress and through residential US/GB exits: identical answers, ~140 mixed
calls on one exit and 30 back-to-back GraphQL calls in 34 s without a 429
or a checkpoint). www.instagram.com runs no bot challenge; its walls are
login walls, and everything this package serves is on the logged-out side
of them.

Four upstream surfaces, all from one anonymous session:

  * GRAPHQL  POST /api/graphql        (the logged-out web app's endpoint)
             POST /graphql/query      (the logged-in web app's endpoint)
    Persisted doc_ids (queries.py). TRAP: each doc_id only answers on ITS
    endpoint — a logged-out doc_id sent to /graphql/query returns
    `{"data":{"xig_user_by_username":null}}` with status ok; a logged-in
    doc_id on /graphql/query needs every relay-provider boolean it declares
    (queries.variables_for) or fails with missing_required_variable_value /
    "execution error". Both need an `lsd` token (x-fb-lsd + form field) and
    a csrftoken cookie echoed in x-csrftoken. Neither value is validated
    server-side: a random pair works, so a session needs NO bootstrap page.
    Login-gated queries answer 401 "Please wait a few minutes before you
    try again" (a gate, not a rate limit — it is immediate and cold on a
    fresh exit; do not build cooldowns on it) or 400 "Unauthorized logged
    out query".

  * MOBILE   https://i.instagram.com/api/v1/... with the Android app's
    User-Agent and app id, unsigned. Serves a user's timeline by USERNAME
    (feed/user/<username>/username/, 12 items, max_id paging — the numeric
    id form is flaky and rejects max_id with "useragent mismatch") and reels
    (POST clips/user/), with the counters the web queries hide (play_count,
    video_duration) and the full audio metadata. Gated paths answer 403
    login_required.

  * WWW API  POST /api/v1/clips/music/ (the audio page's own call): form
    audio_cluster_id + max_id + lsd, header x-ig-d: www, answer prefixed
    with `for (;;);`.

  * PAGES    GET /explore/locations/<id>/ etc.: server-rendered pages that
    embed Relay results in `<script type="application/json" data-sjs>`
    (ssr.py), used where the matching query is itself gated
    (PolarisExploreLocationsContainerQuery answers 401 when called).

FALLBACK: a thread whose direct egress is refused (401/403/429 on a surface
that normally answers, or HTML where JSON was expected) moves to a
residential exit (config.INSTAGRAM_FALLBACK_PROXY_COUNTRY) for
INSTAGRAM_DIRECT_COOLDOWN seconds. If residential exits start being
challenged too, the next step is the patchright pattern (g2 pool): warm a
Chrome on https://www.instagram.com/ and run the same POSTs through the
in-page fetch. Not built: dead code while plain HTTP works.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  InstagramUpstreamError   transport failure / 5xx                  — retryable
  InstagramExecutionError  GraphQL "execution error" with no data    — retryable
  InstagramGated           a login wall on a surface (403/401/redirect
                           to /accounts/login/) — callers fall back to
                           another surface; otherwise 502
  InstagramBlocked         403 / 429 / HTML instead of JSON          — retryable on a new exit
  InstagramBadRequest      upstream 400                              — never retried
  InstagramNotFound        unknown user / post / tag / location      — never retried
"""
import json
import os
import secrets
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
try:  # the shared failure taxonomy of the scrapers service (route_glue maps it to HTTP)
    from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
except ImportError:  # standalone package: the same four bases, locally
    class UpstreamError(Exception):
        """Transport failure or 5xx — retryable."""

    class Blocked(UpstreamError):
        """Anti-bot challenge / 403 / 429 — retryable after a fresh exit."""

    class BadRequest(Exception):
        """Upstream rejected the params — never retried."""

    class NotFound(Exception):
        """Entity / page does not exist — never retried."""

from .queries import QUERIES, variables_for

SITE = "https://www.instagram.com"
MOBILE_SITE = "https://i.instagram.com"
GRAPHQL_URLS = {"api": SITE + "/api/graphql", "query": SITE + "/graphql/query"}
IMPERSONATE = "chrome"

# Constants of the instagram.com web app / Android app (same for every visitor).
WEB_APP_ID = "936619743392459"
WEB_ASBD_ID = "129477"
MOBILE_APP_ID = "567067343352427"
MOBILE_USER_AGENT = ("Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; "
                     "o1s; exynos2100; en_US; 458229258)")

GRAPHQL_TIMEOUT = 30
MOBILE_TIMEOUT = 30
PAGE_TIMEOUT = 45          # explore pages are 1-2 MB
FANOUT_WORKERS = 4

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
}

_GATE_MARKERS = ("please wait a few minutes", "login_required", "unauthorized logged out", "checkpoint_required")


class InstagramUpstreamError(UpstreamError):
    """Transport failure, 5xx or a GraphQL execution error — retryable."""


class InstagramExecutionError(InstagramUpstreamError):
    """GraphQL answered `data: null` with "execution error" — a transient
    backend failure, a stale doc_id / provider list, or (on paged queries)
    a cursor the server cannot decode."""


class InstagramFieldException(InstagramUpstreamError):
    """`data: null` with "A server error field_exception occured" — what
    /graphql/query answers for a shortcode that does not exist (or is
    geo-gated for this exit). Never retried; callers re-ask the logged-out
    endpoint, which distinguishes missing from gated."""


class InstagramGated(InstagramUpstreamError):
    """A login wall on this surface (401 "Please wait", 403 login_required,
    a redirect to /accounts/login/). Callers fall back to another surface."""


class InstagramBlocked(InstagramUpstreamError, Blocked):
    """403 / 429, or HTML where JSON was expected — retryable on a new exit."""


class InstagramBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class InstagramNotFound(NotFound):
    """The user / post / tag / location does not exist — never retried."""


# ---- sessions --------------------------------------------------------------------
# One curl session per worker thread (a curl handle must not be shared across
# threads), each with its own random csrftoken/lsd pair. The mobile calls use
# a second, cookie-less session on the same thread so the web cookies never
# reach i.instagram.com.
_local = threading.local()
_TOKEN_CHARS = string.ascii_letters + string.digits


def _token(n):
    return "".join(secrets.choice(_TOKEN_CHARS) for _ in range(n))


def _proxy_for_thread():
    via_proxy = getattr(_local, "proxy_until", 0) > time.time()
    return via_proxy, (config.instagram_proxy() or (config.instagram_fallback_proxy() if via_proxy else None))


def _new_session(proxy):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess


def _session():
    sess = getattr(_local, "session", None)
    via_proxy, proxy = _proxy_for_thread()
    if sess is not None and getattr(sess, "_ig_proxied", False) != via_proxy:
        _drop_session()
        sess = None
    if sess is None:
        sess = _new_session(proxy)
        sess._ig_proxied = via_proxy
        sess._ig_csrf = _token(32)
        sess._ig_lsd = "AV" + _token(9)
        sess.cookies.set("csrftoken", sess._ig_csrf, domain=".instagram.com")
        _local.session = sess
    return sess


def _mobile_session():
    sess = getattr(_local, "mobile_session", None)
    via_proxy, proxy = _proxy_for_thread()
    if sess is not None and getattr(sess, "_ig_proxied", False) != via_proxy:
        _drop_session()
        sess = None
    if sess is None:
        sess = _new_session(proxy)
        sess._ig_proxied = via_proxy
        _local.mobile_session = sess
    return sess


def _drop_session():
    for attr in ("session", "mobile_session"):
        sess = getattr(_local, attr, None)
        setattr(_local, attr, None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass


def _escalate():
    """Direct egress (or the current exit) was refused: run this thread
    through a fresh residential exit for a while (no fallback configured =
    just rebuild the sessions with new tokens)."""
    if config.instagram_fallback_proxy() is not None:
        _local.proxy_until = time.time() + config.INSTAGRAM_DIRECT_COOLDOWN
    _drop_session()


def dump_debug(name, text):
    """Write a raw response to $INSTAGRAM_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("INSTAGRAM_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


def _retrying(fn, no_retry=()):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except no_retry:
            raise
        except InstagramBlocked as e:
            last = e
            _escalate()
        except InstagramUpstreamError as e:
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _is_gate(text):
    low = (text or "")[:2000].lower()
    return any(marker in low for marker in _GATE_MARKERS)


def _parse_json(text, label):
    body = text or ""
    if body.startswith("for (;;);"):
        body = body[9:]
    if not body.lstrip().startswith("{"):
        dump_debug(f"nonjson_{label}", text)
        raise InstagramBlocked(f"{label} returned a non-JSON body")
    try:
        return json.loads(body)
    except ValueError:
        dump_debug(f"badjson_{label}", text)
        raise InstagramUpstreamError(f"could not parse JSON from {label}")


# ---- GraphQL -------------------------------------------------------------------------

def _is_execution_error(errors):
    return any("execution error" in str((e or {}).get("message", "")) for e in errors or [])


def _error_text(errors):
    return "; ".join(str((e or {}).get("message", "")) for e in errors or [] if isinstance(e, dict))[:300]


def graphql(name, retry_execution_errors=True, **variables):
    """Run one persisted query -> its `data` object.

    A missing entity comes back as data with a null root (callers turn that
    into InstagramNotFound). `data: null` with errors is either a transient
    backend failure or a stale doc_id / provider list — retried, then
    surfaced as an upstream error naming the query so a re-harvest is
    obvious from the logs. Paged calls pass retry_execution_errors=False:
    an undecodable cursor fails the same way every time, so retrying only
    delays the 400."""
    query = QUERIES[name]
    url = GRAPHQL_URLS[query["endpoint"]]
    body = {
        "av": "0",
        "__d": "www",
        "__user": "0",
        "__a": "1",
        "__comet_req": "7",
        "lsd": None,
        "jazoest": "2100",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": name,
        "variables": json.dumps(variables_for(name, **variables), separators=(",", ":")),
        "server_timestamps": "true",
        "doc_id": query["doc_id"],
    }

    def once():
        sess = _session()
        body["lsd"] = sess._ig_lsd
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": SITE,
            "referer": SITE + "/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-asbd-id": WEB_ASBD_ID,
            "x-csrftoken": sess._ig_csrf,
            "x-fb-friendly-name": name,
            "x-fb-lsd": sess._ig_lsd,
            "x-ig-app-id": WEB_APP_ID,
        }
        try:
            resp = sess.post(url, data=body, headers=headers, timeout=GRAPHQL_TIMEOUT)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status in (401, 403, 429):
            dump_debug(f"blocked_{name}", text)
            if _is_gate(text):
                raise InstagramGated(f"{name} is login-gated (HTTP {status})")
            raise InstagramBlocked(f"HTTP {status} on {name}")
        if status >= 500:
            raise InstagramUpstreamError(f"HTTP {status} on {name}")
        payload = _parse_json(text, name)
        if status == 400:
            if _is_gate(text):
                raise InstagramGated(f"{name} is login-gated")
            raise InstagramBadRequest(f"instagram rejected {name}: {_error_text(payload.get('errors')) or 'HTTP 400'}")
        if status != 200:
            raise InstagramUpstreamError(f"HTTP {status} on {name}")
        data = payload.get("data")
        if data is None:
            dump_debug(f"error_{name}", text)
            errors = payload.get("errors")
            if _is_execution_error(errors):
                raise InstagramExecutionError(f"{name} failed upstream (execution error)")
            if "field_exception" in _error_text(errors):
                raise InstagramFieldException(f"{name} answered field_exception")
            if _is_gate(_error_text(errors)):
                raise InstagramGated(f"{name} is login-gated")
            raise InstagramUpstreamError(f"{name} returned no data: {_error_text(errors) or 'empty'}")
        return data

    no_retry = (InstagramGated, InstagramFieldException) + (() if retry_execution_errors else (InstagramExecutionError,))
    return _retrying(once, no_retry=no_retry)


# ---- mobile app API --------------------------------------------------------------------

def mobile(path, *, params=None, data=None):
    """GET (or POST with `data`) https://i.instagram.com/api/v1/<path> as
    the Android app, unsigned -> the JSON object. Login walls (403
    login_required) raise InstagramGated so callers can fall back to a web
    query; a 401 "Please wait" on a path that normally answers is treated
    as a block and moves the thread to a fresh exit."""
    url = f"{MOBILE_SITE}/api/v1/{path.lstrip('/')}"
    label = path.strip("/").split("?")[0]

    def once():
        sess = _mobile_session()
        headers = {
            "user-agent": MOBILE_USER_AGENT,
            "accept": "*/*",
            "accept-language": "en-US",
            "x-ig-app-id": MOBILE_APP_ID,
        }
        try:
            if data is not None:
                resp = sess.post(url, data=data, params=params, headers=headers, timeout=MOBILE_TIMEOUT)
            else:
                resp = sess.get(url, params=params, headers=headers, timeout=MOBILE_TIMEOUT)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status == 404:
            raise InstagramNotFound(f"{label} not found")
        if status in (401, 403, 429):
            dump_debug(f"mobile_blocked_{label.replace('/', '_')}", text)
            if status == 403 and "login_required" in text[:500]:
                raise InstagramGated(f"{label} is login-gated")
            raise InstagramBlocked(f"HTTP {status} on {label}")
        if status >= 500:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        payload = _parse_json(text, label)
        if status == 400:
            message = str(payload.get("message") or "")
            if "not found" in message.lower() or "invalid" in message.lower():
                raise InstagramNotFound(f"{label}: {message}")
            raise InstagramBadRequest(f"instagram rejected {label}: {message or 'HTTP 400'}")
        if status != 200:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        if payload.get("status") == "fail":
            message = str(payload.get("message") or "")
            if "login" in message.lower():
                raise InstagramGated(f"{label} is login-gated")
            raise InstagramUpstreamError(f"{label} failed: {message or 'status fail'}")
        return payload

    return _retrying(once, no_retry=(InstagramGated, InstagramNotFound))


# ---- www /api/v1 (the web app's non-GraphQL calls) --------------------------------------

def www_api(path, *, form, referer):
    """POST https://www.instagram.com/api/v1/<path> the way the web app does
    (form + lsd, x-ig-d: www) -> the JSON payload (the `for (;;);` guard
    stripped, `payload` unwrapped)."""
    url = f"{SITE}/api/v1/{path.lstrip('/')}"
    label = path.strip("/")

    def once():
        sess = _session()
        body = dict(form)
        body.update({"__d": "www", "__user": "0", "__a": "1", "__comet_req": "7", "lsd": sess._ig_lsd, "jazoest": "2100"})
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": SITE,
            "referer": referer,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-asbd-id": "359341",
            "x-csrftoken": sess._ig_csrf,
            "x-fb-lsd": sess._ig_lsd,
            "x-ig-d": "www",
        }
        try:
            resp = sess.post(url, data=body, headers=headers, timeout=GRAPHQL_TIMEOUT)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status == 404:
            raise InstagramNotFound(f"{label} not found")
        if status in (401, 403, 429):
            dump_debug(f"blocked_{label.replace('/', '_')}", text)
            if _is_gate(text):
                raise InstagramGated(f"{label} is login-gated (HTTP {status})")
            raise InstagramBlocked(f"HTTP {status} on {label}")
        if status >= 500:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        payload = _parse_json(text, label)
        if status == 400:
            raise InstagramBadRequest(f"instagram rejected {label}: {payload.get('message') or 'HTTP 400'}")
        if status != 200:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        inner = payload.get("payload")
        return inner if isinstance(inner, dict) else payload

    return _retrying(once, no_retry=(InstagramGated, InstagramNotFound))


def www_json(path, *, params, label):
    """GET https://www.instagram.com/<path> (a plain JSON endpoint such as
    oembed) -> the JSON object; a 404 is InstagramNotFound."""
    url = f"{SITE}/{path.lstrip('/')}"

    def once():
        sess = _session()
        headers = {"accept": "*/*", "accept-language": "en-US,en;q=0.9", "referer": SITE + "/"}
        try:
            resp = sess.get(url, params=params, headers=headers, timeout=GRAPHQL_TIMEOUT)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status == 404:
            raise InstagramNotFound(f"{label} not found")
        if status in (401, 403, 429):
            dump_debug(f"blocked_{label.replace(' ', '_')}", text)
            if _is_gate(text):
                raise InstagramGated(f"{label} is login-gated (HTTP {status})")
            raise InstagramBlocked(f"HTTP {status} on {label}")
        if status >= 500:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        payload = _parse_json(text, label)
        if status == 400:
            raise InstagramBadRequest(f"instagram rejected {label}")
        if status != 200:
            raise InstagramUpstreamError(f"HTTP {status} on {label}")
        return payload

    return _retrying(once, no_retry=(InstagramGated, InstagramNotFound))


# ---- pages ------------------------------------------------------------------------------

def get_page(path, *, label):
    """GET one www.instagram.com page -> (html, final_url). A 404 is
    InstagramNotFound; a redirect to /accounts/login/ is a login wall
    (InstagramGated)."""
    url = SITE + path

    def once():
        sess = _session()
        try:
            resp = sess.get(url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        final = str(resp.url or url)
        if status == 404:
            raise InstagramNotFound(f"{label} not found")
        if status in (401, 403, 429):
            dump_debug("blocked_page", resp.text)
            raise InstagramBlocked(f"HTTP {status} on {path}")
        if status >= 500 or status != 200:
            raise InstagramUpstreamError(f"HTTP {status} on {path}")
        if urlparse(final).path.startswith("/accounts/login"):
            raise InstagramGated(f"{label} is behind a login wall")
        html = resp.text or ""
        if "<html" not in html[:3000].lower():
            dump_debug("nonhtml", html)
            raise InstagramBlocked(f"{path} returned a non-HTML body")
        return html, final

    return _retrying(once, no_retry=(InstagramGated, InstagramNotFound))


def get_redirect(path, *, label):
    """The Location a www.instagram.com path redirects to (share links),
    or None when it does not redirect."""
    url = SITE + path

    def once():
        sess = _session()
        try:
            resp = sess.get(url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=False)
        except Exception as e:
            raise InstagramUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        if status == 404:
            raise InstagramNotFound(f"{label} not found")
        if status in (401, 403, 429):
            raise InstagramBlocked(f"HTTP {status} on {path}")
        if status >= 500:
            raise InstagramUpstreamError(f"HTTP {status} on {path}")
        if status in (301, 302, 303, 307, 308):
            return resp.headers.get("location") or None
        return None

    return _retrying(once, no_retry=(InstagramNotFound,))


# ---- fan-out -------------------------------------------------------------------------

def run_parallel(fns):
    """Run zero-arg callables in parallel; results align with `fns`.
    Exceptions propagate from the first failing call."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


if __name__ == "__main__":
    # Smoke test: python -m instagram.fetch [username]
    who = sys.argv[1] if len(sys.argv) > 1 else "instagram"
    data = graphql("PolarisLoggedOutDesktopWWWProfileRootContentQuery", username=who)
    user = data.get("xig_user_by_username") or {}
    print("user:", user.get("username"), user.get("pk"), user.get("follower_count"))
