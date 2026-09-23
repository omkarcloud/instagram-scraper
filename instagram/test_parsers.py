"""Offline tests for the Instagram refs, SSR helpers, schemas and parsers —
no network.

Every fixture in instagram/fixtures/ is a real upstream payload captured on
2026-09-23 through instagram/fetch.py: GraphQL `data` objects, the Android
app's JSON and the Relay results / og: tags of pages, verbatim except
lists trimmed to a few entries and DASH manifests / tracking tokens
blanked. The assertions pin the field mapping decoded from live data, so
a silent upstream rename shows up here rather than as nulls in a
customer's response.

    python -m pytest instagram/test_parsers.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from instagram import parsers as P, queries, refs, ssr  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


# ---- refs --------------------------------------------------------------------------------

def test_code_and_id_round_trip():
    assert refs.code_to_id("DdEo7DPG8x2") == "3982487950286638198"
    assert refs.id_to_code("3982487950286638198") == "DdEo7DPG8x2"
    assert refs.id_to_code("3982487950286638198_25025320") == "DdEo7DPG8x2"
    assert refs.code_to_id("DdcI4o0Prsz") == "3989102446432402227"


@pytest.mark.parametrize("value", [
    "nike", "@nike", "@Nike", " NIKE ",
    "https://www.instagram.com/nike", "https://www.instagram.com/nike/", "instagram.com/nike/reels/",
    "https://www.instagram.com/nike/p/DdEo7DPG8x2/", "https://instagr.am/nike",
])
def test_user_ref_username_forms(value):
    assert refs.resolve_user(value) == {"id": None, "username": "nike"}


def test_user_ref_id_and_forced_username():
    assert refs.resolve_user("13460080") == {"id": "13460080", "username": None}
    assert refs.resolve_user("@123") == {"id": None, "username": "123"}


@pytest.mark.parametrize("value", ["", "not a user!", "https://threads.com/@nike", "https://www.instagram.com/p/DdEo7DPG8x2/",
                                   "https://www.instagram.com/explore/", "a" * 31])
def test_user_ref_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


@pytest.mark.parametrize("value", [
    "DdEo7DPG8x2", "3982487950286638198", "3982487950286638198_25025320",
    "https://www.instagram.com/p/DdEo7DPG8x2/", "https://www.instagram.com/reel/DdEo7DPG8x2/?igsh=abc",
    "https://www.instagram.com/reels/DdEo7DPG8x2/", "https://www.instagram.com/tv/DdEo7DPG8x2/",
    "https://www.instagram.com/instagram/p/DdEo7DPG8x2/", "instagram.com/instagram/reel/DdEo7DPG8x2",
])
def test_post_ref_forms(value):
    assert refs.resolve_post(value) == {"id": "3982487950286638198", "code": "DdEo7DPG8x2", "share": None}


def test_post_ref_share_link():
    assert refs.resolve_post("https://www.instagram.com/share/reel/_abc123") == {"id": None, "code": None, "share": "/share/reel/_abc123/"}


@pytest.mark.parametrize("value", ["", "https://www.instagram.com/nike/", "https://youtube.com/p/DdEo7DPG8x2/", "a b c"])
def test_post_ref_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_post(value)


def test_tag_location_audio_highlight_refs():
    assert refs.resolve_tag("#Travel") == "travel"
    assert refs.resolve_tag("https://www.instagram.com/explore/tags/travel/") == "travel"
    assert refs.resolve_tag("https://www.instagram.com/popular/travel/?utm_source=explore_tag") == "travel"
    assert refs.resolve_location("212988663") == "212988663"
    assert refs.resolve_location("https://www.instagram.com/explore/locations/212988663/new-york-new-york/") == "212988663"
    assert refs.resolve_audio("https://www.instagram.com/reels/audio/442245453190058/") == "442245453190058"
    assert refs.resolve_highlight("highlight:18029499352961095") == "18029499352961095"
    assert refs.resolve_highlight("https://www.instagram.com/stories/highlights/18029499352961095/") == "18029499352961095"
    for fn, bad in [(refs.resolve_tag, "https://www.instagram.com/nike/"), (refs.resolve_location, "abc"),
                    (refs.resolve_audio, "https://www.instagram.com/p/DdEo7DPG8x2/"), (refs.resolve_highlight, "")]:
        with pytest.raises(ValueError):
            fn(bad)


def test_links():
    assert refs.post_link("DdEo7DPG8x2") == "https://www.instagram.com/p/DdEo7DPG8x2/"
    assert refs.post_link("DdcI4o0Prsz", "clips") == "https://www.instagram.com/reel/DdcI4o0Prsz/"
    assert refs.keyword_link("eiffel tower") == "https://www.instagram.com/popular/eiffel%20tower/"
    assert refs.location_link("212988663", "new-york-new-york").endswith("/212988663/new-york-new-york/")


# ---- queries / schemas -------------------------------------------------------------------

def test_variables_include_every_provider():
    variables = queries.variables_for("PolarisPostRootQuery", shortcode="x")
    assert variables["shortcode"] == "x"
    assert variables["__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider"] is False
    assert variables["__relay_internal__pv__PolarisShortDramaEnabledrelayprovider"] is False
    highlight = queries.variables_for("PolarisStoriesV3HighlightsLoggedOutPageQuery", first=1)
    assert highlight["__relay_internal__pv__PolarisCommunityNoteStoriesLabelEnabledrelayprovider"] is True
    for name, query in queries.QUERIES.items():
        assert query["endpoint"] in ("api", "query"), name
        assert query["doc_id"].isdigit(), name


def test_schemas_one_param_per_input():
    # the marshmallow schemas belong to the hosted service (schema_fields.py);
    # skipped where the package runs standalone
    load_query = pytest.importorskip("schema_fields").load_query
    from instagram import schemas
    data, error = load_query(schemas.UserPageSchema, {"user": "https://www.instagram.com/Nike/", "cursor": "abc"})
    assert error is None and data == {"user": {"id": None, "username": "nike"}, "cursor": "abc"}
    data, error = load_query(schemas.PostSchema, {"post": "https://www.instagram.com/reel/DdcI4o0Prsz/"})
    assert error is None and data["post"]["code"] == "DdcI4o0Prsz"
    _, error = load_query(schemas.PostSchema, {"post": "DdcI4o0Prsz", "url": "x"})
    assert error and "url" in error["errors"]
    _, error = load_query(schemas.UserSchema, {"user": "not a user!"})
    assert error and "user" in error["errors"]
    data, _ = load_query(schemas.LocationPostsSchema, {"location": "212988663", "tab": "Recent"})
    assert data == {"location": "212988663", "tab": "recent"}
    _, error = load_query(schemas.ExploreSectionSchema, {"section": "nope"})
    assert error
    data, _ = load_query(schemas.ExploreSectionSchema, {})
    assert data == {"section": "trending_now", "cursor": None}


# ---- ssr -------------------------------------------------------------------------------------

def test_og_counts():
    html = '<meta property="og:description" content="291M Followers, 269 Following, 1,667 Posts - See Instagram photos and videos from Nike (&#064;nike)">'
    assert ssr.og_counts(html) == {"followers": 291_000_000, "following": 269, "posts": 1667}
    assert ssr.og_counts("") == {"followers": None, "following": None, "posts": None}


# ---- profile ---------------------------------------------------------------------------------

def test_profile_merges_root_page_content_and_og():
    root = load("profile_root_nike.json")["xig_user_by_username"]
    extra = load("profile_page_content_nike.json")["user"]
    og = {"followers": 291_000_000, "following": 269, "posts": 1667}
    profile = P.profile(root, extra, og)
    assert profile["id"] == "13460080" and profile["username"] == "nike" and profile["full_name"] == "Nike"
    assert profile["link"] == "https://www.instagram.com/nike/"
    assert profile["is_verified"] is True and profile["is_private"] is False
    assert profile["biography"] == "Just Do It."
    assert profile["bio_links"] == [{"title": None, "link": "http://empli.fi/nike", "type": "external", "is_pinned": False}]
    assert profile["external_link"] == "http://empli.fi/nike"
    assert profile["account_type"] == "business" and profile["is_business"] is True
    assert profile["follower_count"] > 200_000_000 and profile["following_count"] == root["following_count"]
    assert profile["post_count"] == 1667
    assert profile["threads_username"] == "nike"
    assert profile["has_reels"] is True
    assert profile["highlights"][0]["title"] == "Just Do It"
    assert profile["highlights"][0]["link"].startswith("https://www.instagram.com/stories/highlights/")
    assert profile["has_more_highlights"] is False
    assert "reel_count" not in profile
    assert P.profile(None) is None
    assert P.profile(load("profile_root_missing.json")["xig_user_by_username"]) is None


def test_profile_from_root_alone():
    root = load("profile_root_nike.json")["xig_user_by_username"]
    profile = P.profile(root)
    assert profile["username"] == "nike" and profile["post_count"] is None and profile["category"] is None


# ---- media: mobile dialect ---------------------------------------------------------------------

def test_mobile_feed_reel_has_every_counter():
    items = load("mobile_feed_nike.json")["items"]
    reel = P.media(items[0])
    assert reel["id"] == "3991849403537918302" and reel["code"] == "Ddl5eH-u4le"
    assert reel["link"] == "https://www.instagram.com/reel/Ddl5eH-u4le/"
    assert reel["type"] == "video" and reel["product_type"] == "reel"
    assert reel["caption"].startswith("*Just a normal day")
    assert reel["published_at"] == "2026-09-22T14:00:04Z"
    assert reel["video"]["link"].startswith("https://") and reel["video"]["duration_seconds"] == 30.03
    assert reel["video"]["has_audio"] is True and reel["video"]["width"] == 720
    assert reel["width"] == 1080 and reel["height"] == 1920
    assert reel["stats"]["play_count"] > 1_000_000 and reel["stats"]["like_count"] > 10_000
    assert reel["are_likes_hidden"] is False and reel["is_paid_partnership"] is False
    assert reel["tagged_users"][0]["user"]["username"] == "nikebasketball"
    assert reel["tagged_users"][0]["x"] == pytest.approx(0.0653594807)
    assert reel["coauthors"][0]["username"] == "nikebasketball"
    assert reel["owner"]["id"] == "13460080" and reel["owner"]["username"] == "nike"
    assert reel["carousel"] == [] and reel["carousel_count"] is None


def test_mobile_feed_carousel():
    items = load("mobile_feed_nike.json")["items"]
    post = P.media(items[2])
    assert post["type"] == "carousel" and post["product_type"] == "post"
    assert post["link"] == "https://www.instagram.com/p/DdcI8NLmY21/"
    assert post["carousel_count"] == len(items[2]["carousel_media"]) == len(post["carousel"])
    slide = post["carousel"][0]
    assert slide["id"] and slide["type"] in ("image", "video") and slide["image"].startswith("https://")
    assert post["video"] is None and post["image"].startswith("https://")


def test_mobile_clips_audio_is_original_sound():
    items = load("mobile_clips_nike.json")["items"]
    reels = P.media_list(items)
    assert [r["code"] for r in reels] == ["Ddl5eH-u4le", "DdlXX5sIZSO"]
    audio = reels[0]["audio"]
    assert audio["type"] == "original_sound" and audio["title"] == "Original audio"
    assert audio["artist"] == "nike" and audio["artist_user"]["id"] == "13460080"
    assert audio["link"] == f"https://www.instagram.com/reels/audio/{audio['id']}/"
    assert audio["duration_seconds"] == pytest.approx(30.03, abs=0.01)


def test_mobile_feed_missing_user_is_empty():
    data = load("mobile_feed_missing.json")
    assert P.media_list(data["items"]) == [] and data["num_results"] == 0


# ---- media: XDT dialect ------------------------------------------------------------------------

def test_web_posts_page():
    data = load("web_posts_instagram.json")
    connection = data["xdt_api__v1__feed__user_timeline_graphql_connection"]
    posts = P.media_list(connection["edges"])
    assert [p["code"] for p in posts] == ["Ddjis3vETcP", "DdcI4o0Prsz", "DdbzsI_hDwF"]
    assert posts[0]["type"] == "carousel" and posts[0]["stats"]["like_count"] == 317305
    assert posts[1]["product_type"] == "reel" and posts[1]["video"]["link"].startswith("https://")
    assert posts[1]["audio"]["title"].startswith("When You're Smiling") and posts[1]["audio"]["artist"] == "Louis Prima"
    assert posts[1]["audio"]["id"] == "442245453190058" and posts[1]["audio"]["type"] == "licensed_music"
    assert posts[0]["owner"]["username"] == "instagram"
    cursor, has_more = P.page_info(connection)
    assert cursor == "3973065140916017975_25025320" and has_more is True


def test_post_root_carousel_and_files():
    item = load("post_root_carousel.json")["xdt_api__v1__media__shortcode__web_info"]["items"][0]
    post = P.media(item)
    assert post["id"] == "3982487950286638198" and post["code"] == "DdEo7DPG8x2"
    assert post["type"] == "carousel" and post["product_type"] == "post"
    assert post["published_at"] == "2026-09-09T15:59:40Z"
    assert post["stats"]["like_count"] > 300_000 and post["stats"]["comment_count"] > 7000
    assert post["tagged_users"][0]["user"]["username"] == "maoui2saintdenis"
    assert post["carousel_count"] == 10 and len(post["carousel"]) == 2
    assert post["carousel"][0]["type"] == "video" and post["carousel"][0]["video"]["link"].startswith("https://")
    files = P.media_files(item)
    assert files["code"] == "DdEo7DPG8x2" and files["link"] == post["link"]
    assert files["images"][0]["width"] >= files["images"][-1]["width"]
    assert len(files["carousel"]) == 2 and files["carousel"][0]["videos"][0]["type"] == 101
    assert files["owner"]["username"] == "instagram"
    assert list(files.keys())[:3] == ["id", "code", "link"]


def test_post_root_reel():
    item = load("post_root_reel.json")["xdt_api__v1__media__shortcode__web_info"]["items"][0]
    reel = P.media(item)
    assert reel["link"] == "https://www.instagram.com/reel/DdcI4o0Prsz/" and reel["type"] == "video"
    assert reel["video"]["has_audio"] is True and reel["video"]["width"] == 720
    assert reel["audio"]["title"].startswith("When You're Smiling")
    assert reel["stats"]["play_count"] is None       # the web query hides play counts
    assert reel["tagged_users"][0]["user"]["username"] == "wurzeltheween"
    assert reel["location"] is None


def test_location_tab_post_has_location():
    data = load("location_tab_recent.json")
    posts = P.media_list(data["xdt_location_get_web_info_tab"]["edges"])
    assert posts and posts[0]["location"] == {
        "id": "108424279189115", "name": "New York, New York",
        "link": "https://www.instagram.com/explore/locations/108424279189115/",
        "address": None, "city": None, "latitude": 40.7142, "longitude": -74.0064,
    }


# ---- media: Polaris (logged-out) dialect -------------------------------------------------------

def test_logged_out_post_root_and_comments():
    root = load("post_loggedout_carousel.json")["xig_polaris_media"]
    post = P.media(root["if_not_gated_logged_out"])
    assert post["id"] == "3982487950286638198" and post["type"] == "carousel"
    assert post["owner"]["id"] == "25025320" and post["owner"]["username"] == "instagram"   # pk, not the fb id
    assert post["stats"]["like_count"] > 300_000
    assert post["carousel"][0]["video"]["link"].startswith("https://")
    comments = P.comments(root["comments_connection"]["edges"])
    assert len(comments) == 3 and comments[0]["user"]["username"] and comments[0]["created_at"].endswith("Z")
    assert comments[0]["like_count"] == 0 and comments[0]["parent_comment_id"] is None
    cursor, has_more = P.page_info(root["comments_connection"])
    assert has_more is True and cursor.startswith("{")


def test_logged_out_gated_and_missing():
    gated = load("post_loggedout_gated.json")["xig_polaris_media"]
    assert gated["if_not_gated_logged_out"] is None and gated["gating_ruling"]["gating_type"] == 2
    assert load("post_loggedout_missing.json")["xig_polaris_media"] is None


def test_comments_page():
    data = load("comments_page.json")
    comments = P.comments(data["xig_polaris_media"]["comments_connection"]["edges"])
    assert [c["id"] for c in comments] == ["18424603339146110", "17940230076357965", "18087695675262049"]
    assert comments[1]["text"] == "😍😍😍🙏"


def test_reels_tab_thin_items():
    data = load("reels_tab_nike.json")
    connection = data["xig_user_by_username"]["polaris_clips_connection"]
    reels = P.media_list(connection["edges"], owner={"id": "13460080", "username": "nike"})
    assert len(reels) == 3 and reels[0]["type"] == "video" and reels[0]["product_type"] == "reel"
    assert reels[0]["stats"]["play_count"] > 0 and reels[0]["stats"]["like_count"] > 0
    assert reels[0]["image"].startswith("https://") and reels[0]["link"].startswith("https://www.instagram.com/reel/")
    cursor, has_more = P.page_info(connection)
    assert has_more is True and cursor.startswith("AQHT")


def test_popular_search_page():
    data = load("popular_travel.json")
    posts = P.media_list(data["xig_logged_out_popular_search_media_info"]["edges"], default_product="clips")
    assert [p["code"] for p in posts] == ["DTfS7SMEk8B", "DSI7LxnEbrb", "DW14TyKjKya"]
    assert posts[0]["type"] == "video" and posts[0]["product_type"] == "reel"
    assert posts[0]["link"] == "https://www.instagram.com/reel/DTfS7SMEk8B/"
    assert posts[0]["stats"]["play_count"] > 30_000_000 and posts[0]["video"]["link"].startswith("https://")
    assert posts[0]["owner"]["username"] == "life_samour_style" and posts[0]["owner"]["id"] == "65543671366"
    keywords = P.related_keywords(data["popular_search_related_keywords_connection"])
    assert len(keywords) == 3 and keywords[0]["link"].startswith("https://www.instagram.com/popular/")
    description = P.keyword_description(data["popular_search_keyword_description"])
    assert description["text"].startswith("Edith Cowan") and len(description["sources"]) == 3


def test_ayml_users():
    users = P._users(load("ayml_instagram.json")["xdt_ayml_logged_out"]["users"])
    assert len(users) == 3 and users[0]["id"] == users[0]["id"].strip() and users[0]["username"]
    assert users[0]["link"] == f"https://www.instagram.com/{users[0]['username']}/"


# ---- highlights --------------------------------------------------------------------------------

def test_highlight_items():
    node = load("highlight_items.json")["xdt_api__v1__feed__reels_media__connection"]["edges"][0]["node"]
    highlight = P.highlight(node)
    assert highlight["id"] == "18029499352961095" and highlight["title"] == "what’s new"
    assert highlight["owner"]["username"] == "instagram"
    assert highlight["item_count"] == 2
    image, video = highlight["items"]
    assert image["type"] == "image" and image["video"] is None and image["image"].startswith("https://")
    assert image["published_at"] == "2026-01-26T18:57:40Z" and image["expires_at"] == "2026-01-27T18:57:40Z"
    assert image["link"] == "https://www.instagram.com/stories/highlights/18029499352961095/3818778240853641015/"
    assert image["owner"]["username"] == "instagram"       # filled from the reel's owner
    assert video["type"] == "video" and video["video"]["duration_seconds"] == 20.9


# ---- explore -----------------------------------------------------------------------------------

def test_explore_sections():
    data = load("explore_home.json")
    sections = [P.explore_section(s) for s in data["popular_search_home_sections"]]
    assert [s["section"] for s in sections][:3] == ["trending_now", "entertainment", "celebrities"]
    trending = sections[0]
    assert trending["title"] == "Trending now" and trending["next_cursor"] == "11" and trending["has_more"] is True
    entry = trending["entries"][0]
    assert entry["type"] == "keyword" and entry["rank"] == 1 and entry["link"].startswith("https://www.instagram.com/popular/")
    assert entry["featured_reel"]["link"].startswith("https://www.instagram.com/reel/")
    profiles = sections[2]["entries"][0]
    assert profiles["type"] == "profile" and profiles["user"]["username"] and profiles["follower_count"] > 0
    categories = sections[3]["entries"][0]
    assert categories["type"] == "category" and categories["display_name"] == "Cute animals"
    page = P.explore_section({**load("explore_section_page.json")["fetch__PolarisPopularSearchHomeSection"], "section": "celebrities"})
    assert page["entries"][0]["rank"] == 13 and page["entries"][0]["user"]["username"] == "keyisqueen"


# ---- locations / audio -------------------------------------------------------------------------

def test_location_info_from_page():
    data = load("location_page_relay.json")
    raw = data["PolarisExploreLocationsContainerQuery"]["xdt_location_get_web_info"]["native_location_data"]["location_info"]
    info = P.location_info(raw)
    assert info["id"] == "212988663" and info["name"] == "New York, New York" and info["category"] == "City"
    assert info["link"] == "https://www.instagram.com/explore/locations/212988663/new-york-new-york/"
    assert info["latitude"] == pytest.approx(40.7306, abs=0.001) and info["media_count"] > 80_000_000
    assert info["address"] is None and info["phone"] is None
    assert P.location_info({}) is None
    top = P.media_list(data["PolarisLocationPageTabContentQuery"]["xdt_location_get_web_info_tab"]["edges"])
    assert top and top[0]["code"]


def test_audio_page():
    payload = load("clips_music.json")
    reels = P.media_list(payload["items"], default_product="clips")
    assert len(reels) == 2 and reels[0]["product_type"] == "reel" and reels[0]["stats"]["play_count"] > 0
    meta = {"artist": "Louis Prima", "title": "When You're Smiling (The Whole World Smiles With You)", "reel_count": 901, "cover_image": "https://x/y.jpg"}
    audio = P.audio_page(payload, "442245453190058", reels, meta)
    assert audio["id"] == "442245453190058" and audio["canonical_id"] == "18346538293008909"
    assert audio["type"] == "licensed_music" and audio["artist"] == "Louis Prima"
    assert audio["reel_count"] == 901 and audio["cover_image"] == "https://x/y.jpg" and audio["is_restricted"] is False
    original = P.audio_page(payload, "1", [], {"artist": "nike", "title": "Original audio", "reel_count": None, "cover_image": None})
    assert original["type"] == "original_sound"
    missing = load("clips_music_missing.json")
    assert not missing.get("items") and not missing.get("music_canonical_id")


def test_oembed_shape():
    data = load("oembed.json")
    assert data["media_id"] == "3982487950286638198_25025320" and data["author_name"] == "instagram"


# ---- robustness --------------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [P.media, P.media_files, P.comment, P.user_ref, P.location, P.location_info,
                                P.highlight, P.explore_section, P.explore_entry, P.story_item])
def test_parsers_never_crash_on_garbage(fn):
    for value in (None, {}, [], "x", {"pk": None, "user": "nope", "carousel_media": "x", "image_versions2": 3}):
        fn(value)
