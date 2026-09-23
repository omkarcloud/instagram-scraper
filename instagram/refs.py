"""Instagram reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  user      nike | @nike | 13460080 (numeric user id) | @123 (an all-digit
            username; the @ forces the username reading)
            | https://www.instagram.com/nike[/reels|/tagged|...]
            | https://www.instagram.com/nike/p/<code>/ (the post's author)
    -> {"id": "13460080", "username": None} or {"id": None, "username": "nike"}

  post      DdEo7DPG8x2 (the shortcode in post links)
            | 3982487950286638198 (numeric media id) | 3982487950286638198_25025320
            | https://www.instagram.com/p/<code>/ | /reel/<code>/ | /reels/<code>/
            | /tv/<code>/ | /<username>/p/<code>/ | /<username>/reel/<code>/
            | https://www.instagram.com/share/reel/_abc123 (a share link — the
              shortcode is only known after following its redirect)
    -> {"id": "3982487950286638198", "code": "DdEo7DPG8x2", "share": None}
       or {"id": None, "code": None, "share": "/share/reel/_abc123"}
    The shortcode IS the media id in base64 (alphabet A-Z a-z 0-9 - _), so
    no lookup is needed: code_to_id / id_to_code (verified on live posts,
    2026-09-22).

  tag       travel | #travel | https://www.instagram.com/explore/tags/travel/
            | https://www.instagram.com/popular/travel/
    -> "travel"

  location  212988663 | https://www.instagram.com/explore/locations/212988663/new-york-new-york/
    -> "212988663"

  audio     442245453190058 | https://www.instagram.com/reels/audio/442245453190058/
    -> "442245453190058"

  highlight 18029499352961095 | highlight:18029499352961095
            | https://www.instagram.com/stories/highlights/18029499352961095/
    -> "18029499352961095"
"""
import re
from urllib.parse import unquote, urlparse

SITE = "https://www.instagram.com"

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}

_HOST_RE = re.compile(r"(^|\.)(instagram\.com|instagr\.am)$")
_USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")
_NUMERIC_RE = re.compile(r"^\d{1,20}$")
_MEDIA_ID_RE = re.compile(r"^(\d{10,20})(?:_\d+)?$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
_TAG_RE = re.compile(r"^[^\s#/?&]{1,150}$")
_BARE_LINK_RE = re.compile(r"^(?:www\.)?(?:instagram\.com|instagr\.am)(?:[/?#]|$)", re.I)

# first path segments that are pages, never usernames
_RESERVED = {
    "p", "reel", "reels", "tv", "explore", "stories", "accounts", "share", "popular", "directory",
    "about", "legal", "developer", "api", "graphql", "static", "web", "s", "locations", "tags",
    "audio", "challenge", "emails", "session", "oauth", "embed", "lite", "press", "privacy",
}
_POST_PATHS = {"p", "reel", "reels", "tv"}


def code_to_id(code):
    """Post shortcode -> numeric media id (as a string; ids exceed 2**53)."""
    value = 0
    for ch in code:
        value = value * 64 + _INDEX[ch]
    return str(value)


def id_to_code(media_id):
    """Numeric media id -> shortcode."""
    value = int(str(media_id).split("_")[0])
    out = ""
    while value > 0:
        value, rem = divmod(value, 64)
        out = _ALPHABET[rem] + out
    return out


def _as_url(text):
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return "https:" + text
    return "https://" + text


def _looks_like_link(text):
    # a bare host must end at a path boundary: "instagram.community" would be
    # a valid username, not a link
    low = text.lower()
    return low.startswith(("http://", "https://", "//")) or bool(_BARE_LINK_RE.match(text))


def _parse_link(text, kind):
    parsed = urlparse(_as_url(text))
    if not _HOST_RE.search((parsed.hostname or "").lower()):
        raise ValueError(f"{kind} link must be an instagram.com link")
    return parsed, [unquote(p) for p in parsed.path.split("/") if p]


def resolve_user(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("user must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "user")
        if not parts or parts[0].lower() in _RESERVED:
            raise ValueError(f"no username in link {text!r}")
        text = parts[0]
        if text.startswith("@"):
            text = text[1:]
        name = text.lower()
        if not _USERNAME_RE.match(name):
            raise ValueError(f"no username in link {value!r}")
        return {"id": None, "username": name}
    if text.startswith("@"):
        name = text[1:].lower()
        if not _USERNAME_RE.match(name):
            raise ValueError(f"invalid Instagram username {text!r}")
        return {"id": None, "username": name}
    if _NUMERIC_RE.match(text):
        return {"id": text, "username": None}
    name = text.lower()
    if not _USERNAME_RE.match(name):
        raise ValueError(f"user must be an Instagram username, a numeric user id or an instagram.com profile link, got {text!r}")
    return {"id": None, "username": name}


def _post_from_code(code):
    return {"id": code_to_id(code), "code": code, "share": None}


def resolve_post(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("post must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "post")
        for i, part in enumerate(parts):
            low = part.lower()
            if low == "share" and i + 2 < len(parts):
                # /share/reel/_xxx or /share/p/_xxx — only the redirect knows the code
                return {"id": None, "code": None, "share": "/share/" + "/".join(parts[i + 1:i + 3]) + "/"}
            if low in _POST_PATHS and i + 1 < len(parts) and _CODE_RE.match(parts[i + 1]) and not parts[i + 1].isdigit():
                return _post_from_code(parts[i + 1])
        raise ValueError(f"no post code in link {text!r}")
    match = _MEDIA_ID_RE.match(text)
    if match:
        return {"id": match.group(1), "code": id_to_code(match.group(1)), "share": None}
    if _CODE_RE.match(text):
        return _post_from_code(text)
    raise ValueError(f"post must be an Instagram post code, a numeric media id or an instagram.com post link, got {text!r}")


def resolve_tag(value):
    text = str(value or "").strip()
    if _looks_like_link(text):
        _, parts = _parse_link(text, "tag")
        if len(parts) >= 3 and parts[0].lower() == "explore" and parts[1].lower() == "tags":
            text = parts[2]
        elif len(parts) >= 2 and parts[0].lower() == "popular":
            text = parts[1]
        else:
            raise ValueError(f"no hashtag in link {value!r}")
    text = text.lstrip("#").strip().lower()
    if not text:
        raise ValueError("tag must not be empty")
    if not _TAG_RE.match(text):
        raise ValueError(f"invalid hashtag {value!r}")
    return text


def _resolve_numeric(value, kind, link_parts):
    """A bare numeric id, or an instagram.com link whose path starts with
    `link_parts` followed by the id."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{kind} must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, kind)
        n = len(link_parts)
        if len(parts) > n and [p.lower() for p in parts[:n]] == list(link_parts) and _NUMERIC_RE.match(parts[n]):
            return parts[n]
        raise ValueError(f"no {kind} id in link {text!r}")
    if _NUMERIC_RE.match(text):
        return text
    raise ValueError(f"{kind} must be a numeric id or an instagram.com {kind} link, got {text!r}")


def resolve_location(value):
    return _resolve_numeric(value, "location", ("explore", "locations"))


def resolve_audio(value):
    return _resolve_numeric(value, "audio", ("reels", "audio"))


def resolve_highlight(value):
    text = str(value or "").strip()
    if text.lower().startswith("highlight:"):
        text = text[len("highlight:"):]
    return _resolve_numeric(text, "highlight", ("stories", "highlights"))


# ---- links ---------------------------------------------------------------------------------

def user_link(username):
    return f"{SITE}/{username}/" if username else None


def post_link(code, product_type=None):
    if not code:
        return None
    if product_type in ("clips", "reel"):
        return f"{SITE}/reel/{code}/"
    return f"{SITE}/p/{code}/"


def tag_link(name):
    return f"{SITE}/explore/tags/{name}/" if name else None


def location_link(location_id, slug=None):
    if not location_id:
        return None
    return f"{SITE}/explore/locations/{location_id}/{slug}/" if slug else f"{SITE}/explore/locations/{location_id}/"


def audio_link(audio_id):
    return f"{SITE}/reels/audio/{audio_id}/" if audio_id else None


def highlight_link(highlight_id):
    return f"{SITE}/stories/highlights/{highlight_id}/" if highlight_id else None


def keyword_link(keyword):
    from urllib.parse import quote
    return f"{SITE}/popular/{quote(keyword, safe='')}/" if keyword else None
