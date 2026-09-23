"""User endpoints: resolve, profile, posts, reels, highlights and similar
accounts.

`user` is {"id": ..., "username": ...} from refs.resolve_user (a username,
@username, numeric id or profile link). Every endpoint first looks the
user up with the logged-out profile root query (an ~8 KB answer by
username; a numeric id goes through the app's users/<id>/info first for
the username), which both proves the account exists (a null root is a
404) and supplies the numeric id / Facebook id the other calls need.
Lookups are memoised in-process for LOOKUP_TTL seconds so a paging client
does not pay for it on every page.

Surfaces (probed 2026-09-22):
  posts   the app's feed/user/<username>/username/ — 12 items per page
          with every counter (play_count included) and full audio
          metadata; cursor = next_max_id ("<media_pk>_<user_pk>"). When
          that surface is walled for an exit, the same page comes from the
          web PolarisProfilePostsQuery / _connection (same cursor format,
          same fields minus play_count / duration).
  reels   the app's POST clips/user/ — 12 reels per page, opaque max_id.
          Fallback (first page only: the logged-out reels tab has no
          pagination query): PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery,
          thin items with like / comment / play counts.
  highlights  the tray preloaded with the profile root (first page; its
          pagination query is login-walled).
  similar     PolarisAYMLFollowChainingListLoggedOutQuery, up to 44
          accounts (empty for some large accounts upstream).
"""
import threading
import time

from . import parsers as P
from .fetch import (
    InstagramBadRequest, InstagramBlocked, InstagramExecutionError, InstagramGated, InstagramNotFound,
    InstagramUpstreamError, graphql, mobile, run_parallel,
)
from .ssr import og_counts

LOOKUP_TTL = 600
PAGE_SIZE = 12
INVALID_CURSOR = "invalid cursor: pass the next_cursor value from the previous page unchanged"

_lookup_lock = threading.Lock()
_lookups = {}           # ("id"|"username", value) -> (expires, raw root user)


def _describe(user):
    return f"@{user['username']}" if user.get("username") else f"user id {user.get('id')}"


def _root_by_username(username):
    data = graphql("PolarisLoggedOutDesktopWWWProfileRootContentQuery", username=username)
    raw = data.get("xig_user_by_username")
    return raw if isinstance(raw, dict) and raw.get("pk") else None


def lookup(user):
    """The raw profile root for a resolved ref; InstagramNotFound if the
    account does not exist."""
    key = ("username", user["username"]) if user.get("username") else ("id", str(user.get("id")))
    now = time.time()
    with _lookup_lock:
        hit = _lookups.get(key)
        if hit and hit[0] > now:
            return hit[1]
    if key[0] == "username":
        raw = _root_by_username(key[1])
    else:
        try:
            info = mobile(f"users/{key[1]}/info/")
        except InstagramNotFound:
            raw = None
        else:
            username = P.clean(P._dict(info.get("user")).get("username"))
            raw = _root_by_username(username.lower()) if username else None
    if raw is None:
        raise InstagramNotFound(f"{_describe(user)} not found on Instagram")
    with _lookup_lock:
        if len(_lookups) > 5000:
            _lookups.clear()
        _lookups[key] = (now + LOOKUP_TTL, raw)
        _lookups[("id", str(raw.get("pk")))] = (now + LOOKUP_TTL, raw)
        if raw.get("username"):
            _lookups[("username", str(raw["username"]).lower())] = (now + LOOKUP_TTL, raw)
    return raw


def resolve(user):
    """Username <-> numeric id, with the basic account facts."""
    raw = lookup(user)
    out = P.user_ref(raw)
    out["facebook_id"] = P.to_id(raw.get("id")) if str(raw.get("id")) != str(raw.get("pk")) else None
    out["follower_count"] = P.to_int(raw.get("follower_count"))
    out["following_count"] = P.to_int(raw.get("following_count"))
    return out


def _quiet(fn):
    """Run an enrichment call; its failure must not fail the profile."""
    try:
        return fn()
    except (InstagramUpstreamError, InstagramBadRequest, InstagramNotFound):
        return None


def get_profile(user):
    """The full profile: bio, bio links, category, counts, highlights."""
    raw = lookup(user)
    pk = str(raw.get("pk"))
    username = str(raw.get("username"))

    def extra():
        data = graphql("PolarisProfilePageContentQuery", id=pk, enable_integrity_filters=True)
        return data.get("user")

    def og():
        from .fetch import get_page
        html, _ = get_page(f"/{username}/", label=f"@{username}")
        return og_counts(html)

    extra_raw, counts = run_parallel([lambda: _quiet(extra), lambda: _quiet(og)])
    parsed = P.profile(raw, extra_raw, counts)
    if parsed is None:
        raise InstagramNotFound(f"{_describe(user)} not found on Instagram")
    return parsed


# ---- posts ---------------------------------------------------------------------------------

def _web_posts(raw_user, cursor):
    username = str(raw_user.get("username"))
    fbid = str(raw_user.get("id") or raw_user.get("pk"))
    try:
        if cursor:
            data = graphql("PolarisProfilePostsTabContentQuery_connection", retry_execution_errors=False,
                           first=PAGE_SIZE, after=cursor, id=fbid, include_multi_captions=False,
                           data={"count": PAGE_SIZE, "include_reel_media_seen_timestamp": True,
                                 "include_relationship_info": True, "latest_besties_reel_media": True,
                                 "latest_reel_media": True}, username=username)
        else:
            data = graphql("PolarisProfilePostsQuery", username=username,
                           data={"count": PAGE_SIZE, "include_reel_media_seen_timestamp": True,
                                 "include_relationship_info": True, "latest_besties_reel_media": True,
                                 "latest_reel_media": True})
    except InstagramExecutionError:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    connection = P._dict(data.get("xdt_api__v1__feed__user_timeline_graphql_connection"))
    posts = P.media_list(connection.get("edges"), owner=P.user_ref(raw_user))
    next_cursor, has_more = P.page_info(connection)
    return posts, next_cursor, has_more


def _app_posts(raw_user, cursor):
    username = str(raw_user.get("username"))
    params = {"count": PAGE_SIZE}
    if cursor:
        params["max_id"] = cursor
    try:
        data = mobile(f"feed/user/{username}/username/", params=params)
    except InstagramBadRequest:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    posts = P.media_list(data.get("items"), owner=P.user_ref(raw_user))
    has_more = bool(P.to_bool(data.get("more_available")))
    next_cursor = P.clean(data.get("next_max_id")) if has_more else None
    return posts, next_cursor, has_more


def get_posts(user, cursor=None):
    """The user's timeline (posts, reels shared to the grid, carousels),
    newest first, 12 per page."""
    raw_user = lookup(user)
    try:
        posts, next_cursor, has_more = _app_posts(raw_user, cursor)
    except (InstagramGated, InstagramBlocked):
        posts, next_cursor, has_more = _web_posts(raw_user, cursor)
    if P.to_bool(raw_user.get("is_private")) and not posts:
        has_more = False
    return {
        "user": P.user_ref(raw_user),
        "is_private": P.to_bool(raw_user.get("is_private")),
        "post_count": len(posts),
        "posts": posts,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ---- reels ---------------------------------------------------------------------------------

def _web_reels(raw_user):
    data = graphql("PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery", first=PAGE_SIZE,
                   username=str(raw_user.get("username")))
    root = P._dict(data.get("xig_user_by_username"))
    connection = P._dict(root.get("polaris_clips_connection"))
    reels = P.media_list(connection.get("edges"), owner=P.user_ref(raw_user))
    for reel in reels:
        reel["product_type"] = reel["product_type"] or "reel"
        reel["link"] = reel["link"] or None
    _, has_more = P.page_info(connection)
    return reels, None, has_more


def get_reels(user, cursor=None):
    """The user's reels (the Reels tab), newest first, 12 per page."""
    raw_user = lookup(user)
    pk = str(raw_user.get("pk"))
    form = {"target_user_id": pk, "page_size": str(PAGE_SIZE), "include_feed_video": "true"}
    if cursor:
        form["max_id"] = cursor
    try:
        data = mobile("clips/user/", data=form)
    except InstagramBadRequest:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    except (InstagramGated, InstagramBlocked):
        if cursor:
            raise
        reels, next_cursor, has_more = _web_reels(raw_user)
    else:
        reels = P.media_list(data.get("items"), owner=P.user_ref(raw_user))
        paging = P._dict(data.get("paging_info"))
        has_more = bool(P.to_bool(paging.get("more_available")))
        next_cursor = P.clean(paging.get("max_id")) if has_more else None
    return {
        "user": P.user_ref(raw_user),
        "is_private": P.to_bool(raw_user.get("is_private")),
        "reel_count": len(reels),
        "reels": reels,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ---- highlights / similar ------------------------------------------------------------------

def get_highlights(user):
    """The profile's highlights tray (id, title, cover). Items of one
    highlight: /instagram/highlights/items."""
    raw_user = lookup(user)
    tray = P._dict(raw_user.get("lox_highlights_connection"))
    highlights = [h for h in (P.highlight_ref(P._dict(e).get("node")) for e in P._list(tray.get("edges"))) if h]
    _, has_more = P.page_info(tray)
    return {
        "user": P.user_ref(raw_user),
        "highlight_count": len(highlights),
        "highlights": highlights,
        "has_more": has_more,
    }


def get_similar(user):
    """Accounts Instagram suggests next to this one ("accounts you might
    like"), up to 44."""
    raw_user = lookup(user)
    pk = str(raw_user.get("pk"))
    data = graphql("PolarisAYMLFollowChainingListLoggedOutQuery", owner_id=pk)
    users = P._users(P._dict(data.get("xdt_ayml_logged_out")).get("users"))
    if not users:
        fbid = str(raw_user.get("id") or pk)
        data = _quiet(lambda: graphql("PolarisLoggedOutDesktopWWWAYMLQuery", id=fbid)) or {}
        root = data.get("ayml_logged_out") or P._dict(data.get("xdt_ayml_logged_out")).get("users")
        users = P._users(root if isinstance(root, list) else P._dict(root).get("users"))
    return {
        "user": P.user_ref(raw_user),
        "similar_count": len(users),
        "similar_users": users,
    }
