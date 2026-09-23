"""Instagram normalizers: the three upstream dialects -> one clean
snake_case shape per entity.

Dialects (the same entity arrives in three spellings):
  XDT      /graphql/query answers (XDTMediaDict / XDTUserDict) and the
           Relay results preloaded into pages: pk as string, user.id == pk.
  POLARIS  /api/graphql logged-out answers (XIGPolaris*Media / XIGComment):
           thin media, `display_uri`, user.id is the FACEBOOK id (17841…)
           while user.pk is the Instagram id — always read pk.
  MOBILE   i.instagram.com app answers: pk as int, the richest media
           (play_count, video_duration, full clips_metadata), `strong_id__`
           / `pk_id` duplicates everywhere.

Output conventions (shared with the other scrapers here): `link` for
canonical instagram.com URLs, `image` / `video` / `profile_picture` for
media URLs, `*_count` for counters, `is_*` / `has_*` / `are_*` for
booleans, ISO-8601 UTC timestamps (the upstream's epoch seconds), numbers
as numbers, null for missing, [] for empty lists. Ids stay STRINGS: media
and user ids are 17-20 digits and overflow a JavaScript number.

Entity shapes:
  user (compact)  {id, username, full_name, link, profile_picture,
                   is_verified, is_private}
  profile         compact user + biography, bio_links, external_link,
                   category, account_type, pronouns, follower_count,
                   following_count, post_count, flags,
                   threads_username, highlights[]
  media           {id, code, link, type, product_type, caption,
                   published_at, is_caption_edited, image, video, width,
                   height, accessibility_caption, stats{...}, flags,
                   location, audio, tagged_users, coauthors, sponsors,
                   carousel[], carousel_count, owner}
                   `type` decodes media_type: 1 image, 2 video, 8 carousel;
                   `product_type` decodes the upstream product: feed ->
                   "post", clips -> "reel", igtv -> "igtv", story ->
                   "story", carousel_container -> "post".
  comment         {id, text, created_at, like_count, reply_count, user,
                   parent_comment_id}
  story item      media + expires_at (highlight reels)

Deliberately dropped as noise:
  tracking    organic_tracking_token, logging_info_token, mezql_token,
              client_cache_key, __typename / __isXIGPolarisMedia,
              __module_operation_* / __module_component_* (Relay boot),
              strong_id__, pk_id, device_timestamp, integrity_review_decision,
              deleted_reason, filter_type, fbid / fbid_v2 (Facebook-side ids
              of the same objects), interop_messaging_user_fbid
  duplicates  the composite `id` ("<media>_<user>"; `pk` kept as id),
              display_uri (= the largest image candidate), video_dash_manifest
              (an XML rendition of video_versions), is_dash_eligible,
              number_of_qualities, video_codec, lynx_url / external_lynx_url
              (click-tracking wrappers; the target url is kept), link_id,
              hd_profile_pic_url_info (= profile_picture), text_translation,
              caption.media_id / user_id / user (= the media's owner),
              image estimated_scans_sizes / scans_profile,
              scrubber_spritesheet_info_candidates, additional_candidates
              (first-frame stills of videos), media_cropping_info,
              profile_grid_thumbnail_fitting_style, carousel_media_ids
  viewer      has_liked, has_viewer_saved, friendship_status,
              can_viewer_reshare, can_viewer_save, can_reply,
              commenting_disabled_for_viewer, saved_collection_ids,
              has_privately_liked, is_seen, reel_media_seen_timestamp — the
              logged-out viewer's own state, always null/false here
  always null logged out / unused by the web app: boosted_status,
              boost_unavailable_*, feed_demotion_control, sharing_friction_info,
              social_context, media_overlay_info, ai_label_info, audience,
              upcoming_event, media_notes, headline, crosspost_metadata,
              longform_*, floating_context_items, group, story_cta, preview,
              thumbnails, inventory_source, explore, wearable_attribution_info,
              media_attributions_data, follow_hashtag_info, affiliate_info,
              clips_attribution_info, gen_ai_detection_method, fundraiser_tag,
              comment_inform_treatment, clips_demotion_control,
              related_ads_pivots_media_info, eligible_insights_entrypoints,
              fan_club_info, mashup_info, basel_template_info_for_ig_app,
              achievements_info, music_consumption_info (mute flags),
              highlight_start_times_in_ms, dash_manifest (audio),
              fast_start_progressive_download_url (= progressive_download_url)
  unreliable  total_clips_count (PolarisProfilePageContentQuery answers 1 for
              accounts with hundreds of reels), all_media_count (always null
              logged out; the post count comes from the page's og:description)
  presentation hidden_likes_string_variant, formatted_media_count (the numeric
              count is kept), popular_search_home_sections[].__token,
              PolarisPopularSearchHome* display_name where it equals the
              keyword, page_url (rebuilt as `link`)
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

from . import refs

# The scalar / image helpers below are the same ones threads/parsers.py uses;
# they are kept inside this package so it runs standalone (no sibling
# scraper packages needed).


def clean(value):
    """Whitespace-trimmed string, or None for empty / non-strings."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def to_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


def to_bool(value):
    """True/False for real booleans (and 0/1), None when absent."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def to_id(value):
    """An upstream numeric id as a string (they exceed 2**53)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def iso_utc(epoch):
    """Epoch seconds -> 2026-09-17T14:27:44Z."""
    seconds = to_int(epoch)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def unwrap_link(url):
    """https://l.instagram.com/?u=<target>&e=... -> <target> (the
    click-tracking redirect around outbound links); anything else unchanged."""
    text = clean(url)
    if not text:
        return None
    parsed = urlparse(text)
    host = parsed.hostname or ""
    if host.startswith("l.instagram.") or host.startswith("l.threads."):
        target = (parse_qs(parsed.query).get("u") or [None])[0]
        return clean(target) or text
    return text


def image_sizes(candidates):
    """[{link, width, height}] largest first, duplicates (same size) dropped."""
    out, seen = [], set()
    rows = [c for c in _list(candidates) if isinstance(c, dict) and clean(c.get("url"))]
    rows.sort(key=lambda c: (to_int(c.get("width")) or 0) * (to_int(c.get("height")) or 0), reverse=True)
    for c in rows:
        size = (to_int(c.get("width")), to_int(c.get("height")))
        if size in seen:
            continue
        seen.add(size)
        out.append({"link": clean(c.get("url")), "width": size[0], "height": size[1]})
    return out


def best_image(candidates):
    sizes = image_sizes(candidates)
    return sizes[0]["link"] if sizes else None

MEDIA_TYPES = {1: "image", 2: "video", 8: "carousel"}
PRODUCT_TYPES = {"feed": "post", "clips": "reel", "igtv": "igtv", "story": "story", "carousel_container": "post",
                 "carousel_item": "carousel_item", "ad": "ad", "guide": "guide"}
ACCOUNT_TYPES = {1: "personal", 2: "business", 3: "creator"}
AUDIO_TYPES = {"licensed_music": "licensed_music", "original_sounds": "original_sound", "original_sound": "original_sound"}


# ---- scalars ---------------------------------------------------------------------------

def to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def seconds(ms):
    """Milliseconds -> seconds (float), None when absent."""
    value = to_float(ms)
    return round(value / 1000.0, 3) if value is not None else None


def _ig_id(raw):
    """A user's Instagram id: pk in every dialect (the Polaris dialect's
    `id` is the Facebook id of the same account)."""
    raw = _dict(raw)
    return to_id(raw.get("pk")) or to_id(raw.get("pk_id")) or to_id(raw.get("id"))


# ---- images / video ----------------------------------------------------------------------

def video_versions(versions):
    """[{link, width, height, type}] largest first. `type` is Instagram's
    rendition code (101 highest quality, 102, 103); the Polaris dialect
    carries no dimensions."""
    rows = []
    for v in _list(versions):
        if not isinstance(v, dict) or not clean(v.get("url")):
            continue
        rows.append({"link": clean(v.get("url")), "width": to_int(v.get("width")), "height": to_int(v.get("height")),
                     "type": to_int(v.get("type"))})
    rows.sort(key=lambda r: ((r["width"] or 0) * (r["height"] or 0), -(r["type"] or 999)), reverse=True)
    return rows


def _candidates(raw):
    return _dict(raw.get("image_versions2")).get("candidates")


def _image(raw):
    return best_image(_candidates(raw)) or clean(raw.get("display_uri")) or clean(raw.get("display_url"))


def _video(raw):
    versions = video_versions(raw.get("video_versions"))
    if not versions:
        return None
    best = versions[0]
    return {
        "link": best["link"],
        "width": best["width"] or to_int(raw.get("original_width")),
        "height": best["height"] or to_int(raw.get("original_height")),
        "duration_seconds": _duration(raw.get("video_duration")),
        "has_audio": to_bool(raw.get("has_audio")),
    }


def _duration(value):
    value = to_float(value)
    return round(value, 3) if value is not None else None


# ---- users ---------------------------------------------------------------------------------

def user_ref(raw):
    """Compact user: an owner, a tag, a suggestion."""
    raw = _dict(raw)
    username = clean(raw.get("username"))
    user_id = _ig_id(raw)
    if not username and not user_id:
        return None
    picture = clean(_dict(raw.get("hd_profile_pic_url_info")).get("url")) or clean(raw.get("profile_pic_url")) \
        or clean(_dict(raw.get("profile_picture_for_dimensions")).get("uri")) or clean(raw.get("profile_image_uri"))
    return {
        "id": user_id,
        "username": username,
        "full_name": clean(raw.get("full_name")),
        "link": refs.user_link(username),
        "profile_picture": picture,
        "is_verified": to_bool(raw.get("is_verified")),
        "is_private": to_bool(raw.get("is_private")),
    }


def bio_links(raw_links):
    out = []
    for link in _list(raw_links):
        if not isinstance(link, dict):
            continue
        target = unwrap_link(link.get("url")) or unwrap_link(link.get("lynx_url"))
        if not target:
            continue
        out.append({
            "title": clean(link.get("title")),
            "link": target,
            "type": clean(link.get("link_type")),
            "is_pinned": to_bool(link.get("is_pinned")) or False,
        })
    return out


def highlight_ref(node):
    """One entry of the profile's highlights tray."""
    node = _dict(node)
    raw_id = clean(node.get("id"))
    if not raw_id:
        return None
    highlight_id = raw_id.split(":", 1)[1] if raw_id.startswith("highlight:") else raw_id
    cover = clean(node.get("cover_media_cropped_thumbnail_url")) \
        or clean(_dict(_dict(node.get("cover_media")).get("cropped_image_version")).get("url"))
    return {
        "id": highlight_id,
        "title": clean(node.get("title")),
        "link": refs.highlight_link(highlight_id),
        "cover_image": cover,
    }


def profile(root, extra=None, og=None):
    """The full profile: `root` is xig_user_by_username (logged-out profile
    root), `extra` the /graphql/query PolarisProfilePageContentQuery user
    (category, external link, hd picture, clips count), `og` the counts
    read from the profile page (post_count)."""
    root = _dict(root)
    extra = _dict(extra)
    og = _dict(og)
    base = user_ref({**extra, **root, "hd_profile_pic_url_info": extra.get("hd_profile_pic_url_info")})
    if base is None:
        return None
    tray = _dict(root.get("lox_highlights_connection"))
    highlights = [h for h in (highlight_ref(_dict(e).get("node")) for e in _list(tray.get("edges"))) if h]
    badge = clean(root.get("text_post_app_badge_label")) or clean(extra.get("text_post_app_badge_label"))
    shows_badge = to_bool(root.get("show_text_post_app_badge")) or to_bool(extra.get("show_text_post_app_badge"))
    base.update({
        "biography": clean(root.get("biography")) if root.get("biography") is not None else clean(extra.get("biography")),
        "bio_links": bio_links(root.get("bio_links") or extra.get("bio_links")),
        "external_link": unwrap_link(extra.get("external_url")),
        "category": clean(extra.get("category")),
        "account_type": ACCOUNT_TYPES.get(to_int(extra.get("account_type"))),
        "pronouns": [p for p in (clean(x) for x in _list(root.get("pronouns"))) if p],
        "follower_count": to_int(root.get("follower_count")) if root.get("follower_count") is not None else to_int(extra.get("follower_count")),
        "following_count": to_int(root.get("following_count")) if root.get("following_count") is not None else to_int(extra.get("following_count")),
        "post_count": to_int(og.get("posts")) if og.get("posts") is not None else to_int(root.get("all_media_count")),
        "is_business": (to_int(extra.get("account_type")) == 2) if extra.get("account_type") is not None else None,
        "is_memorialized": to_bool(root.get("is_memorialized")) if root.get("is_memorialized") is not None else to_bool(extra.get("is_memorialized")),
        "has_reels": to_bool(root.get("has_any_clips")),
        "threads_username": badge if shows_badge else None,
        "account_badges": [b for b in (clean(x) for x in _list(root.get("account_badges"))) if b],
        "highlights": highlights,
        "has_more_highlights": to_bool(_dict(tray.get("page_info")).get("has_next_page")) or False,
    })
    return base


# ---- media ---------------------------------------------------------------------------------

def location(raw):
    raw = _dict(raw)
    location_id = to_id(raw.get("pk") or raw.get("id") or raw.get("location_id"))
    name = clean(raw.get("name"))
    if not location_id and not name:
        return None
    return {
        "id": location_id,
        "name": name,
        "link": refs.location_link(location_id, clean(raw.get("slug"))),
        "address": clean(raw.get("address")) or clean(raw.get("location_address")),
        "city": clean(raw.get("city")) or clean(raw.get("location_city")),
        "latitude": to_float(raw.get("lat")),
        "longitude": to_float(raw.get("lng")),
    }


def audio(clips_metadata, music_metadata=None):
    """The track a reel (or a feed post with music) uses, from
    clips_metadata (reels) or music_metadata (feed posts)."""
    meta = _dict(clips_metadata)
    music = _dict(meta.get("music_info")) or _dict(_dict(music_metadata).get("music_info"))
    asset = _dict(music.get("music_asset_info"))
    original = _dict(meta.get("original_sound_info")) or _dict(_dict(music_metadata).get("original_sound_info"))
    if asset:
        audio_id = to_id(asset.get("audio_cluster_id")) or to_id(asset.get("id"))
        return {
            "id": audio_id,
            "link": refs.audio_link(audio_id),
            "type": "licensed_music",
            "title": clean(asset.get("title")),
            "artist": clean(asset.get("display_artist")),
            "artist_user": None,
            "cover_image": clean(asset.get("cover_artwork_uri")) or clean(asset.get("cover_artwork_thumbnail_uri")),
            "duration_seconds": seconds(asset.get("duration_in_ms")),
            "is_explicit": to_bool(asset.get("is_explicit")),
            "preview_link": clean(asset.get("web_30s_preview_download_url")),
            "download_link": clean(asset.get("progressive_download_url")),
        }
    if original:
        audio_id = to_id(original.get("audio_asset_id")) or to_id(original.get("audio_id"))
        artist = user_ref(original.get("ig_artist"))
        return {
            "id": audio_id,
            "link": refs.audio_link(audio_id),
            "type": "original_sound",
            "title": clean(original.get("original_audio_title")),
            "artist": (artist or {}).get("username"),
            "artist_user": artist,
            "cover_image": None,
            "duration_seconds": seconds(original.get("duration_in_ms")),
            "is_explicit": to_bool(original.get("is_explicit")),
            "preview_link": None,
            "download_link": clean(original.get("progressive_download_url")),
        }
    return None


def tagged_users(raw):
    out = []
    for tag in _list(_dict(raw).get("in")):
        tag = _dict(tag)
        user = user_ref(tag.get("user"))
        if not user:
            continue
        position = _list(tag.get("position"))
        out.append({
            "user": user,
            "x": to_float(position[0]) if len(position) > 0 else None,
            "y": to_float(position[1]) if len(position) > 1 else None,
        })
    return out


def _users(rows):
    return [u for u in (user_ref(r) for r in _list(rows)) if u]


def _play_count(raw):
    for key in ("play_count", "ig_play_count", "fb_play_count"):
        value = to_int(raw.get(key))
        if value is not None:
            return value
    return None


def _product_type(raw, default=None):
    product = clean(raw.get("product_type")) or default
    if product:
        return PRODUCT_TYPES.get(product, product)
    return None


_TYPENAME_TYPES = {"Video": "video", "Image": "image", "Carousel": "carousel"}


def _media_type(raw):
    """1/2/8 -> image/video/carousel; the Polaris dialect carries no
    media_type on list items, only a __typename (XIGPolarisVideoMedia…)."""
    kind = MEDIA_TYPES.get(to_int(raw.get("media_type")))
    if kind:
        return kind
    typename = clean(raw.get("__typename")) or ""
    for marker, value in _TYPENAME_TYPES.items():
        if marker in typename:
            return value
    return None


def media_item(raw):
    """One carousel slide."""
    raw = _dict(raw)
    return {
        "id": to_id(raw.get("pk")),
        "type": _media_type(raw),
        "image": _image(raw),
        "video": _video(raw),
        "width": to_int(raw.get("original_width")),
        "height": to_int(raw.get("original_height")),
        "accessibility_caption": clean(raw.get("accessibility_caption")),
        "tagged_users": tagged_users(raw.get("usertags")),
    }


def media(raw, *, owner=None, default_product=None):
    """One post / reel / story item in any dialect. `default_product` is
    the upstream product_type to assume when the dialect omits it (the
    keyword / audio pages only list reels)."""
    raw = _dict(raw)
    media_id = to_id(raw.get("pk"))
    code = clean(raw.get("code"))
    if not media_id and not code:
        return None
    if media_id and not code:
        try:
            code = refs.id_to_code(media_id)
        except (TypeError, ValueError):
            code = None
    caption = _dict(raw.get("caption"))
    product = clean(raw.get("product_type")) or default_product
    pinned_for = _list(raw.get("timeline_pinned_user_ids")) or _list(raw.get("clips_tab_pinned_user_ids"))
    author = user_ref(raw.get("user")) or owner
    if author is None and raw.get("owner_id"):
        author = user_ref({"pk": raw.get("owner_id")})
    carousel = [media_item(item) for item in _list(raw.get("carousel_media"))]
    carousel = [c for c in carousel if c.get("id")]
    location_raw = raw.get("location") or (_list(raw.get("locations")) or [None])[0]
    return {
        "id": media_id,
        "code": code,
        "link": refs.post_link(code, product),
        "type": _media_type(raw),
        "product_type": _product_type(raw, default_product),
        "caption": clean(caption.get("text")),
        "published_at": iso_utc(raw.get("taken_at")),
        "is_caption_edited": to_bool(raw.get("caption_is_edited")),
        "image": _image(raw),
        "video": _video(raw),
        "width": to_int(raw.get("original_width")),
        "height": to_int(raw.get("original_height")),
        "accessibility_caption": clean(raw.get("accessibility_caption")),
        "title": clean(raw.get("title")),
        "stats": {
            "like_count": to_int(raw.get("like_count")),
            "comment_count": to_int(raw.get("comment_count")),
            "play_count": _play_count(raw),
            "view_count": to_int(raw.get("view_count")),
            "repost_count": to_int(raw.get("media_repost_count")),
        },
        "are_likes_hidden": to_bool(raw.get("like_and_view_counts_disabled")),
        "are_comments_disabled": to_bool(raw.get("comments_disabled")),
        "is_paid_partnership": to_bool(raw.get("is_paid_partnership")),
        "is_pinned": bool(pinned_for),
        "location": location(location_raw),
        "audio": audio(raw.get("clips_metadata"), raw.get("music_metadata")),
        "tagged_users": tagged_users(raw.get("usertags")),
        "coauthors": _users(raw.get("coauthor_producers")),
        "sponsors": _users(raw.get("sponsor_tags")),
        "carousel": carousel,
        "carousel_count": to_int(raw.get("carousel_media_count")) or (len(carousel) or None),
        "owner": author,
    }


def media_list(rows, *, owner=None, default_product=None):
    """Media from a list of raw items / edges / {media: ...} wrappers."""
    out = []
    for row in _list(rows):
        row = _dict(row)
        node = row.get("node") if "node" in row else row
        node = _dict(node)
        if "media" in node and isinstance(node.get("media"), dict):
            node = node["media"]
        parsed = media(node, owner=owner, default_product=default_product)
        if parsed:
            out.append(parsed)
    return out


def media_files(raw):
    """Every image size and video rendition of a media (each carousel slide
    separately), for downloading."""
    raw = _dict(raw)
    def files(item):
        return {
            "id": to_id(item.get("pk")),
            "type": _media_type(item),
            "width": to_int(item.get("original_width")),
            "height": to_int(item.get("original_height")),
            "images": image_sizes(_candidates(item)) or ([{"link": clean(item.get("display_uri")), "width": None, "height": None}]
                                                          if clean(item.get("display_uri")) else []),
            "videos": video_versions(item.get("video_versions")),
            "has_audio": to_bool(item.get("has_audio")),
            "duration_seconds": _duration(item.get("video_duration")),
        }
    parsed = media(raw) or {}
    out = files(raw)
    out.update({
        "code": parsed.get("code"),
        "link": parsed.get("link"),
        "product_type": parsed.get("product_type"),
        "owner": parsed.get("owner"),
        "carousel": [files(item) for item in _list(raw.get("carousel_media")) if isinstance(item, dict)],
    })
    ordered = ["id", "code", "link", "type", "product_type", "width", "height", "images", "videos", "has_audio",
               "duration_seconds", "carousel", "owner"]
    return {k: out.get(k) for k in ordered}


def page_info(connection):
    """(next_cursor, has_more) from a Relay connection."""
    info = _dict(_dict(connection).get("page_info"))
    has_more = to_bool(info.get("has_next_page"))
    cursor = info.get("end_cursor")
    cursor = clean(cursor) if isinstance(cursor, str) else None
    if not has_more:
        cursor = None
    return cursor, bool(has_more)


# ---- comments ------------------------------------------------------------------------------

def comment(raw):
    raw = _dict(raw)
    comment_id = to_id(raw.get("pk"))
    text = clean(raw.get("text"))
    if not comment_id and text is None:
        return None
    return {
        "id": comment_id,
        "text": text,
        "created_at": iso_utc(raw.get("created_at") or raw.get("created_at_utc")),
        "like_count": to_int(raw.get("comment_like_count")),
        "reply_count": to_int(raw.get("child_comment_count")),
        "user": user_ref(raw.get("user")),
        "parent_comment_id": to_id(raw.get("parent_comment_id")),
        "is_by_owner": to_bool(raw.get("is_created_by_media_owner")),
    }


def comments(rows):
    out = []
    for row in _list(rows):
        row = _dict(row)
        node = row.get("node") if "node" in row else row
        parsed = comment(node)
        if parsed:
            out.append(parsed)
    return out


# ---- stories / highlights ------------------------------------------------------------------

def story_item(raw, *, highlight_id=None):
    parsed = media(raw)
    if parsed is None:
        return None
    raw = _dict(raw)
    keep = ["id", "type", "published_at", "image", "video", "width", "height", "accessibility_caption", "owner"]
    out = {k: parsed.get(k) for k in keep}
    out["expires_at"] = iso_utc(raw.get("expiring_at"))
    out["link"] = f"{refs.SITE}/stories/highlights/{highlight_id}/{out['id']}/" if highlight_id and out.get("id") else None
    out["tagged_users"] = parsed.get("tagged_users") or []
    out["audio"] = parsed.get("audio")
    ordered = ["id", "link", "type", "published_at", "expires_at", "image", "video", "width", "height",
               "accessibility_caption", "audio", "tagged_users", "owner"]
    return {k: out.get(k) for k in ordered}


def highlight(node):
    """One highlight reel with all its items."""
    node = _dict(node)
    ref = highlight_ref(node)
    if ref is None:
        return None
    owner = user_ref(node.get("user"))
    items = [i for i in (story_item(raw, highlight_id=ref["id"]) for raw in _list(node.get("items"))) if i]
    for item in items:
        if owner and not (item.get("owner") or {}).get("username"):
            item["owner"] = owner
    ref.update({
        "owner": owner,
        "updated_at": iso_utc(node.get("latest_reel_media")),
        "item_count": len(items),
        "items": items,
    })
    return ref


# ---- discovery -------------------------------------------------------------------------------

def keyword_description(raw):
    raw = _dict(raw)
    text = clean(raw.get("plain_text"))
    if not text:
        return None
    return {"text": text, "sources": [s for s in (clean(x) for x in _list(raw.get("source_uris"))) if s]}


def related_keywords(connection):
    out = []
    for edge in _list(_dict(connection).get("edges")):
        text = clean(_dict(_dict(edge).get("node")).get("query_text"))
        if text:
            out.append({"keyword": text, "link": refs.keyword_link(text)})
    return out


def explore_entry(node):
    node = _dict(node)
    kind = clean(node.get("__typename")) or ""
    rank = to_int(node.get("rank"))
    if "Profile" in kind:
        user = user_ref(node.get("user"))
        if not user:
            return None
        return {"rank": rank, "type": "profile", "user": user, "follower_count": to_int(_dict(node.get("user")).get("follower_count"))}
    keyword = _dict(node.get("keyword"))
    text = clean(keyword.get("keyword_text")) or clean(node.get("display_name"))
    if not text:
        return None
    reel = _dict(keyword.get("featured_reel_media"))
    featured = None
    if reel.get("code"):
        versions = video_versions(reel.get("video_versions"))
        featured = {"code": clean(reel.get("code")), "link": refs.post_link(reel.get("code"), "clips"),
                    "video": versions[0]["link"] if versions else None}
    return {
        "rank": rank,
        "type": "category" if "Category" in kind else "keyword",
        "keyword": text,
        "display_name": clean(node.get("display_name")),
        "link": refs.keyword_link(text),
        "media_count": to_int(keyword.get("media_count")),
        "thumbnail": clean(keyword.get("thumbnail_url")),
        "featured_reel": featured,
    }


def explore_section(raw):
    raw = _dict(raw)
    connection = _dict(raw.get("entries_connection"))
    entries = [e for e in (explore_entry(_dict(edge).get("node")) for edge in _list(connection.get("edges"))) if e]
    cursor, has_more = page_info(connection)
    return {
        "id": clean(raw.get("id")),
        "section": (clean(raw.get("section")) or "").lower() or None,
        "title": clean(raw.get("display_title")),
        "entry_count": len(entries),
        "entries": entries,
        "next_cursor": cursor,
        "has_more": has_more,
    }


def location_info(raw):
    """xdt_location_get_web_info.native_location_data.location_info."""
    raw = _dict(raw)
    location_id = to_id(raw.get("location_id") or raw.get("pk"))
    name = clean(raw.get("name"))
    if not location_id or not name:
        return None
    hours = _dict(raw.get("hours"))
    business = _dict(_dict(raw.get("ig_business")).get("profile"))
    return {
        "id": location_id,
        "name": name,
        "link": refs.location_link(location_id, clean(raw.get("slug"))),
        "category": clean(raw.get("category")),
        "address": clean(raw.get("location_address")),
        "city": clean(raw.get("location_city")),
        "zip": clean(raw.get("location_zip")),
        "phone": clean(raw.get("phone")),
        "website": unwrap_link(raw.get("website")),
        "latitude": to_float(raw.get("lat")),
        "longitude": to_float(raw.get("lng")),
        "media_count": to_int(raw.get("media_count")),
        "price_range": to_int(raw.get("price_range")),
        "hours_status": clean(hours.get("status")),
        "business": user_ref(business),
    }


def audio_page(payload, audio_id, items, meta=None):
    """The audio page: `payload` is the /clips/music/ answer (canonical id,
    counts, restriction flag), `meta` the artist / title / reel count /
    cover read from the page's og: tags, `items` its parsed reels (used
    only for the track when a reel's own metadata names this audio)."""
    payload = _dict(payload)
    meta = _dict(meta)
    track = None
    for item in _list(items):
        candidate = _dict((item or {}).get("audio"))
        if candidate.get("id") == audio_id:
            track = candidate
            break
    track = track or {}
    counts = _dict(payload.get("media_count"))
    reel_count = to_int(counts.get("clips_count")) or None
    return {
        "id": audio_id,
        "link": refs.audio_link(audio_id),
        "canonical_id": to_id(payload.get("music_canonical_id")),
        "type": track.get("type") or ("original_sound" if (meta.get("title") or "").lower() == "original audio" else
                                      ("licensed_music" if meta.get("title") else None)),
        "title": track.get("title") or meta.get("title"),
        "artist": track.get("artist") or meta.get("artist"),
        "artist_user": track.get("artist_user"),
        "cover_image": track.get("cover_image") or meta.get("cover_image"),
        "duration_seconds": track.get("duration_seconds"),
        "is_explicit": track.get("is_explicit"),
        "preview_link": track.get("preview_link"),
        "download_link": track.get("download_link"),
        "reel_count": reel_count if reel_count is not None else meta.get("reel_count"),
        "photo_count": to_int(counts.get("photos_count")),
        "is_restricted": to_bool(payload.get("is_music_page_restricted")),
    }


def keyword_quote(keyword):
    return quote(keyword, safe="")
