"""The 19 Instagram endpoints. Every path is served with and without the
`/instagram` prefix, so code generated against the hosted API on RapidAPI
(paths like /users/profile) runs unchanged against this server."""
import json

from bottle import request, response, route

from instagram import refs
from instagram.discovery import (EXPLORE_SECTIONS, audio_details, audio_reels, explore_section,
                                 explore_trending, hashtag_posts, highlight_items, location_details,
                                 location_posts, search_keyword)
from instagram.fetch import InstagramBadRequest, InstagramNotFound
from instagram.posts import get_comments, get_details, get_media
from instagram.posts import resolve as resolve_post
from instagram.users import (get_highlights, get_posts, get_profile, get_reels, get_similar)
from instagram.users import resolve as resolve_user


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def q(name):
    """One query param as unicode (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    value = request.query.getunicode(name)
    return " ".join(value.split()) if value else None


class Invalid(Exception):
    """A bad or missing query param -> 400."""


def required(name, resolver=None):
    """The param, resolved (a username / link -> the reference the scraper
    takes). Missing or malformed -> Invalid."""
    value = q(name)
    if not value:
        raise Invalid(f"Missing required parameter: {name}")
    if resolver is None:
        return value
    try:
        return resolver(value)
    except ValueError as e:
        raise Invalid(f"{name}: {e}")


def choice(name, allowed, default):
    value = (q(name) or default).lower()
    if value not in allowed:
        raise Invalid(f"{name}: must be one of {', '.join(allowed)}")
    return value


def call(label, fn):
    """Shared error mapping: bad params -> 400, missing entity -> 404,
    transport/blocks -> 500."""
    try:
        return json_response(fn())
    except Invalid as e:
        return json_response({"error": str(e)}, 400)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except InstagramBadRequest as e:       # upstream rejected the request (e.g. a stale cursor)
        return json_response({"error": f"instagram rejected the request: {e}"}, 400)
    except InstagramNotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"instagram {label} failed: {e}"}, 500)


def mount(path, fn):
    """Serve fn (a zero-arg callable reading the query) at /path and /instagram/path."""
    def handler():
        return call(path.strip("/"), fn)
    handler.__name__ = "instagram_" + path.strip("/").replace("/", "_")
    route(path, method="GET")(handler)
    route("/instagram" + path, method="GET")(handler)


def user():
    return required("user", refs.resolve_user)


def post():
    return required("post", refs.resolve_post)


ENDPOINTS = [
    ("/users/profile", lambda: get_profile(user())),
    ("/users/posts", lambda: get_posts(user(), cursor=q("cursor"))),
    ("/users/reels", lambda: get_reels(user(), cursor=q("cursor"))),
    ("/posts/details", lambda: get_details(post())),
    ("/posts/comments", lambda: get_comments(post(), cursor=q("cursor"))),
    ("/posts/media", lambda: get_media(post())),
    ("/users/highlights", lambda: get_highlights(user())),
    ("/highlights/items", lambda: highlight_items(required("highlight", refs.resolve_highlight))),
    ("/users/similar", lambda: get_similar(user())),
    ("/hashtags/posts", lambda: hashtag_posts(required("tag", refs.resolve_tag), cursor=q("cursor"))),
    ("/search/keywords", lambda: search_keyword(required("query"), cursor=q("cursor"))),
    ("/locations/details", lambda: location_details(required("location", refs.resolve_location))),
    ("/locations/posts", lambda: location_posts(required("location", refs.resolve_location),
                                                tab=choice("tab", ["ranked", "recent"], "ranked"))),
    ("/audio/details", lambda: audio_details(required("audio", refs.resolve_audio))),
    ("/audio/reels", lambda: audio_reels(required("audio", refs.resolve_audio), cursor=q("cursor"))),
    ("/explore/trending", lambda: explore_trending()),
    ("/explore/section", lambda: explore_section(choice("section", EXPLORE_SECTIONS, "trending_now"),
                                                 cursor=q("cursor"))),
    ("/users/resolve", lambda: resolve_user(user())),
    ("/posts/resolve", lambda: resolve_post(post())),
]

for _path, _fn in ENDPOINTS:
    mount(_path, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _ in ENDPOINTS]})
