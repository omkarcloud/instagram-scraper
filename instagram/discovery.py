"""Discovery endpoints: hashtag / keyword pages, locations, audio pages,
highlights and the explore home.

What logged-out Instagram serves (probed 2026-09-22):
  * hashtag / keyword: the /popular/<keyword>/ page's query
    (PolarisLoggedOutPopularSearchPageQuery) — ranked reels 12 per page
    with a cursor, related keywords and an AI-written description with its
    sources. There is no "recent" tab and no hashtag media count logged
    out; an unknown keyword returns no posts (no 404). Typed search
    (users / places) is a login wall.
  * locations: the /explore/locations/<id>/ page preloads the location
    record (name, category, address, coordinates, media count — the query
    itself is login-walled when called directly) and its first ranked
    posts; PolarisLocationPageTabContentQuery pages ranked / recent posts
    with a cursor. Location search is a login wall (ids come from posts).
  * audio: the audio page's own POST /api/v1/clips/music/ — 12 reels per
    page with an opaque max_id. Logged out neither that call's summary
    block nor the reels' clips_metadata name the track, so the artist /
    title / reel count come from the audio page's og: tags.
  * highlights: PolarisStoriesV3HighlightsLoggedOutPageQuery returns every
    item of one highlight reel at once (44 seen); live stories are a wall.
  * explore: PolarisPopularSearchHomePageQuery, the 8 keyword / profile
    sections of /explore/, each paging with its own cursor.
"""
import re

from . import parsers as P
from . import refs
from .fetch import (
    InstagramBadRequest, InstagramExecutionError, InstagramNotFound, InstagramUpstreamError, graphql, www_api,
)
from .ssr import load, og_meta

PAGE_SIZE = 12
RELATED_KEYWORDS = 10
INVALID_CURSOR = "invalid cursor: pass the next_cursor value from the previous page unchanged"

EXPLORE_SECTIONS = ["trending_now", "entertainment", "celebrities", "browse_categories", "get_inspired",
                    "learn_something_new", "shop_the_trends", "trending_month"]


# ---- hashtag / keyword -----------------------------------------------------------------------

def _popular(keyword, cursor):
    try:
        data = graphql("PolarisLoggedOutPopularSearchPageQuery", retry_execution_errors=not cursor,
                       keyword=keyword, media_count=PAGE_SIZE, related_keywords_count=RELATED_KEYWORDS,
                       include_reel_experience_fields=True, include_description=not cursor,
                       include_trending_pills=False, debug=None, after=cursor)
    except InstagramExecutionError:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    connection = P._dict(data.get("xig_logged_out_popular_search_media_info"))
    posts = P.media_list(connection.get("edges"), default_product="clips")
    next_cursor, has_more = P.page_info(connection)
    return {
        "description": P.keyword_description(data.get("popular_search_keyword_description")),
        "post_count": len(posts),
        "posts": posts,
        "related_keywords": P.related_keywords(data.get("popular_search_related_keywords_connection")),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def hashtag_posts(tag, cursor=None):
    """Top reels for a hashtag (the /explore/tags/<tag>/ page), 12 per page."""
    out = {"tag": tag, "link": refs.tag_link(tag)}
    out.update(_popular(tag, cursor))
    return out


def search_keyword(query, cursor=None):
    """Top reels for a free-text keyword (the /popular/<keyword>/ page) with
    related keywords, 12 per page."""
    out = {"query": query, "link": refs.keyword_link(query)}
    out.update(_popular(query, cursor))
    return out


# ---- locations ---------------------------------------------------------------------------------

def location_details(location):
    """A location's record (name, category, address, coordinates, media
    count) with the first ranked posts the page preloads."""
    data, _ = load(f"/explore/locations/{location}/", label=f"location {location}",
                   required="PolarisExploreLocationsContainerQuery")
    root = P._dict(P._dict(P._dict(data.get("PolarisExploreLocationsContainerQuery")).get("xdt_location_get_web_info"))
                   .get("native_location_data"))
    info = P.location_info(root.get("location_info"))
    if info is None:
        raise InstagramNotFound(f"location {location} not found")
    tab = P._dict(P._dict(data.get("PolarisLocationPageTabContentQuery")).get("xdt_location_get_web_info_tab"))
    top = P.media_list(tab.get("edges"))
    info["top_post_count"] = len(top)
    info["top_posts"] = top
    return info


def location_posts(location, tab="ranked"):
    """Posts tagged with a location: `tab` ranked (top) or recent. ONE page
    (12-27 posts): the tab's pagination query
    (PolarisLocationPageTabContentQuery_connection) is a login wall, and
    the first query answers an empty page for any cursor logged out. An
    unknown location answers an empty page too."""
    data = graphql("PolarisLocationPageTabContentQuery", location_id=location, tab=tab,
                   page_size_override=PAGE_SIZE, first=None, after=None)
    connection = P._dict(data.get("xdt_location_get_web_info_tab"))
    posts = P.media_list(connection.get("edges"))
    _, has_more = P.page_info(connection)
    return {
        "location_id": location,
        "link": refs.location_link(location),
        "tab": tab,
        "post_count": len(posts),
        "posts": posts,
        "has_more": has_more,
    }


# ---- audio -------------------------------------------------------------------------------------

def _audio_page(audio_id, cursor):
    form = {"audio_cluster_id": audio_id, "max_id": cursor or "", "original_sound_audio_asset_id": audio_id}
    try:
        payload = www_api("clips/music/", form=form, referer=refs.audio_link(audio_id))
    except InstagramBadRequest:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    items = P._list(payload.get("items"))
    if not items and not P.clean(payload.get("music_canonical_id")):
        raise InstagramNotFound(f"audio {audio_id} not found")
    reels = P.media_list(items, default_product="clips")
    paging = P._dict(payload.get("paging_info"))
    has_more = bool(P.to_bool(paging.get("more_available")))
    next_cursor = P.clean(paging.get("max_id")) if has_more else None
    return payload, reels, next_cursor, has_more


_OG_TITLE_RE = re.compile(r"^(.*?)\s+\|\s+(.*?)\s+on Instagram$", re.S)
_OG_REELS_RE = re.compile(r"([\d,.]+)\s*([KMB])?\s+reels?\b", re.I)
_SCALE = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _audio_page_meta(audio_id):
    """The audio page's og: tags: "Louis Prima | When You're Smiling on
    Instagram", "856 reels - Listen to …", the cover image. The page
    itself is client-rendered (no Relay data) and the reels the
    /clips/music/ call lists carry no track metadata logged out, so this
    is the only anonymous source of the track's name and reel count."""
    from .fetch import get_page
    html, _ = get_page(f"/reels/audio/{audio_id}/", label=f"audio {audio_id}")
    meta = og_meta(html)
    title = P.clean(meta.get("og:title")) or ""
    match = _OG_TITLE_RE.match(title)
    artist, track = (P.clean(match.group(1)), P.clean(match.group(2))) if match else (None, None)
    count = None
    found = _OG_REELS_RE.search(meta.get("og:description") or "")
    if found:
        try:
            value = float(found.group(1).replace(",", ""))
            count = int(round(value * _SCALE.get((found.group(2) or "").upper(), 1)))
        except ValueError:
            count = None
    return {"artist": artist, "title": track, "reel_count": count, "cover_image": P.clean(meta.get("og:image"))}


def audio_details(audio):
    """The track behind an audio page (title, artist, cover, reel count)
    and its first 12 reels."""
    from .fetch import run_parallel

    def page():
        try:
            return _audio_page_meta(audio)
        except (InstagramUpstreamError, InstagramNotFound, InstagramBadRequest):
            return {}

    (payload, reels, next_cursor, has_more), meta = run_parallel([lambda: _audio_page(audio, None), page])
    out = P.audio_page(payload, audio, reels, meta)
    out.update({"reel_count_returned": len(reels), "reels": reels, "next_cursor": next_cursor, "has_more": has_more})
    return out


def audio_reels(audio, cursor=None):
    """Reels using an audio track, 12 per page, cursor paged."""
    payload, reels, next_cursor, has_more = _audio_page(audio, cursor)
    return {
        "audio_id": audio,
        "link": refs.audio_link(audio),
        "reel_count": len(reels),
        "reels": reels,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ---- highlights --------------------------------------------------------------------------------

def highlight_items(highlight):
    """Every story item of one highlight reel (photos and videos with
    their media URLs, timestamps and tagged users)."""
    reel_id = f"highlight:{highlight}"
    data = graphql("PolarisStoriesV3HighlightsLoggedOutPageQuery", reel_ids=[reel_id], initial_reel_id=reel_id,
                   first=1, apply_new_highlights_filter=False)
    edges = P._list(P._dict(data.get("xdt_api__v1__feed__reels_media__connection")).get("edges"))
    node = P._dict(P._dict(edges[0]).get("node")) if edges else {}
    parsed = P.highlight(node) if node else None
    if parsed is None:
        raise InstagramNotFound(f"highlight {highlight} not found")
    return parsed


# ---- explore -----------------------------------------------------------------------------------

def explore_trending():
    """The /explore/ home logged out: trending keywords, pop-culture
    moments, profiles to look out for, browse categories and more."""
    data = graphql("PolarisPopularSearchHomePageQuery", count=PAGE_SIZE)
    sections = [P.explore_section(s) for s in P._list(data.get("popular_search_home_sections")) if isinstance(s, dict)]
    return {"section_count": len(sections), "sections": sections}


def explore_section(section, cursor=None):
    """More entries of one explore section (section ids from /explore/trending)."""
    section_id = f"PolarisPopularSearchHomeSection:{section}"
    try:
        data = graphql("PopularSearchHomeSectionPaginationQuery", retry_execution_errors=not cursor,
                       id=section_id, count=PAGE_SIZE, cursor=cursor)
    except InstagramExecutionError:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    raw = data.get("fetch__PolarisPopularSearchHomeSection")
    if not isinstance(raw, dict):
        raise InstagramNotFound(f"explore section {section} not found")
    parsed = P.explore_section({**raw, "section": section, "id": section_id})
    return parsed
