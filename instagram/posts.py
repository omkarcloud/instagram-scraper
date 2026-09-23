"""Post endpoints: details, media files, comments and id resolution.

`post` is {"id", "code", "share"} from refs.resolve_post (a shortcode,
numeric media id or instagram.com post link — the shortcode decodes to the
id locally; a /share/ link only knows its code after one redirect).

Details come from PolarisPostRootQuery (/graphql/query, the full 86-key
media item: counts, every image size and video rendition, location,
tagged users, audio). A shortcode that does not exist — or a post
geo-gated for this exit — makes that query answer `field_exception`, so
the logged-out PolarisLoggedOutDesktopWWWPostRootContentQuery (/api/graphql,
by media id) is asked next: it returns null for a missing post and a
`gating_ruling` ("Not available in your region") for a gated one, with the
thinner logged-out media when it is available after all.

Comments page with PolarisLoggedOutDesktopWWWPostCommentsPaginationQuery
(24 asked per page, ~4-15 returned after upstream filtering; the cursor is
the JSON string the server hands back, passed verbatim). Logged out, some
posts stop paging early (one reel with 13K comments ended at 31 on
2026-09-23, another ran past 140). Replies to a comment and the likers list
are login walls upstream and are not served.
"""
from urllib.parse import urlparse

from . import parsers as P
from . import refs
from .fetch import (
    InstagramBadRequest, InstagramExecutionError, InstagramFieldException, InstagramNotFound, get_redirect, graphql,
    www_json,
)

COMMENTS_PAGE_SIZE = 24
INVALID_CURSOR = "invalid cursor: pass the next_cursor value from the previous page unchanged"


def _resolved(post):
    """A share link -> the post it redirects to."""
    if not post.get("share"):
        return post
    location = get_redirect(post["share"], label="share link")
    if not location:
        raise InstagramNotFound("share link does not point at a post")
    try:
        target = refs.resolve_post(location if location.startswith("http") else refs.SITE + location)
    except ValueError:
        raise InstagramNotFound("share link does not point at a post")
    if target.get("share"):
        raise InstagramNotFound("share link does not point at a post")
    return target


def _logged_out(media_id, code):
    data = graphql("PolarisLoggedOutDesktopWWWPostRootContentQuery", media_id=media_id)
    root = data.get("xig_polaris_media")
    if not isinstance(root, dict):
        raise InstagramNotFound(f"post {code} not found")
    gate = P._dict(root.get("gating_ruling"))
    inner = root.get("if_not_gated_logged_out")
    if isinstance(inner, dict) and inner.get("pk"):
        return inner
    if gate:
        title = P.clean(gate.get("title")) or "not available"
        raise InstagramNotFound(f"post {code} is not available from this region ({title})")
    raise InstagramNotFound(f"post {code} not found")


def _full(post):
    """The raw media item (XDT dialect, or the logged-out one when only that
    surface serves it)."""
    post = _resolved(post)
    code, media_id = post["code"], post["id"]
    try:
        data = graphql("PolarisPostRootQuery", shortcode=code)
    except InstagramFieldException:
        return _logged_out(media_id, code)
    items = P._list(P._dict(data.get("xdt_api__v1__media__shortcode__web_info")).get("items"))
    item = items[0] if items and isinstance(items[0], dict) else None
    if not item or not item.get("pk"):
        return _logged_out(media_id, code)
    return item


def get_details(post):
    """One post / reel with everything: caption, counts, media, location,
    tagged users, coauthors, audio, carousel slides."""
    return P.media(_full(post))


def get_media(post):
    """Every image size and video rendition of the post's media (each
    carousel slide separately), for downloading."""
    return P.media_files(_full(post))


def get_comments(post, cursor=None):
    """The post's comments as the site shows them logged out, page by page
    (~12 per page; some posts stop paging early)."""
    post = _resolved(post)
    code, media_id = post["code"], post["id"]
    try:
        data = graphql("PolarisLoggedOutDesktopWWWPostCommentsPaginationQuery", retry_execution_errors=not cursor,
                       media_id=media_id, first=COMMENTS_PAGE_SIZE, after=cursor)
    except InstagramExecutionError:
        if cursor:
            raise InstagramBadRequest(INVALID_CURSOR)
        raise
    root = data.get("xig_polaris_media")
    if not isinstance(root, dict):
        raise InstagramNotFound(f"post {code} not found")
    connection = P._dict(root.get("comments_connection"))
    comments = P.comments(connection.get("edges"))
    next_cursor, has_more = P.page_info(connection)
    return {
        "post_id": media_id,
        "code": code,
        "link": refs.post_link(code),
        "comment_count": len(comments),
        "comments": comments,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def resolve(post):
    """Shortcode <-> numeric media id, with the canonical link and the
    author (from the public oEmbed endpoint — one small call, no GraphQL)."""
    post = _resolved(post)
    code, media_id = post["code"], post["id"]
    data = www_json("api/v1/oembed/", params={"url": refs.post_link(code)}, label=f"post {code}")
    if not isinstance(data, dict) or not data.get("media_id"):
        raise InstagramNotFound(f"post {code} not found")
    author_url = P.clean(data.get("author_url"))
    username = None
    if author_url:
        parts = [p for p in urlparse(author_url).path.split("/") if p]
        username = parts[0].lower() if parts else None
    return {
        "id": media_id,
        "code": code,
        "link": refs.post_link(code),
        "caption": P.clean(data.get("title")),
        "thumbnail": P.clean(data.get("thumbnail_url")),
        "author": {
            "id": P.to_id(data.get("author_id")),
            "username": username or P.clean(data.get("author_name")),
            "link": refs.user_link(username or P.clean(data.get("author_name"))),
        },
    }
