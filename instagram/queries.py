"""Instagram GraphQL persisted queries: doc_id, endpoint and relay-provider
list per query, as harvested from the www.instagram.com JS bundles on
2026-09-22.

The web app sends `doc_id` (a persisted-query id) instead of query text.
Each query module in the bundles is

    __d("<Name>_instagramRelayOperation", [], (...) { exports = "<doc_id>" })
    __d("<Name>.graphql", [...], ...) whose argumentDefinitions / Request
    section names `__relay_internal__pv__<X>relayprovider` variables

TWO endpoints serve two query families (the trap of this site):

  * "api"    POST /api/graphql — what the logged-out web app calls. Serves
             the `*LoggedOut*` doc_ids. The same doc_ids on /graphql/query
             answer `{"data":{"xig_user_by_username":null}}` — no error,
             just nothing.
  * "query"  POST /graphql/query — the logged-in web app's endpoint. Its
             doc_ids DO answer anonymously, but only when every relay
             provider the query declares is present in `variables`
             (missing one -> `missing_required_variable_value` or
             `data: null` with "execution error"; extra ones are ignored).

Provider values are what a logged-out browser sends: all false except the
highlights label flag. Re-harvest when a query starts failing: download the
bundles any www page references (static.cdninstagram.com/rsrc.php/...js),
grep `_instagramRelayOperation` for ids and each `.graphql` module for its
`__relay_internal__pv__` names.
"""

PROVIDER_VALUES = {
    "PolarisCASB976ProfileEnabled": False,
    "PolarisCannesGuardianExperienceEnabled": False,
    "PolarisCommunityNoteStoriesLabelEnabled": True,
    "PolarisMultiCaptionCarouselEnabled": False,
    "PolarisReelsRecoDebugOverlayEnabled": False,
    "PolarisRepostsConsumptionEnabled": False,
    "PolarisShortDramaEnabled": False,
    "PolarisWebSchoolsEnabled": False,
}

_PROFILE_PROVIDERS = ["PolarisCASB976ProfileEnabled", "PolarisCannesGuardianExperienceEnabled",
                      "PolarisMultiCaptionCarouselEnabled", "PolarisReelsRecoDebugOverlayEnabled",
                      "PolarisRepostsConsumptionEnabled", "PolarisShortDramaEnabled", "PolarisWebSchoolsEnabled"]
_POSTS_PROVIDERS = ["PolarisMultiCaptionCarouselEnabled", "PolarisReelsRecoDebugOverlayEnabled", "PolarisShortDramaEnabled"]

# name -> {doc_id, endpoint, providers}
QUERIES = {
    # ---- /api/graphql (logged-out family) --------------------------------------------
    # profile header by username: pk, fbid, bio, bio links, counts, highlights tray
    "PolarisLoggedOutDesktopWWWProfileRootContentQuery": {
        "doc_id": "27981003384861049", "endpoint": "api", "providers": []},
    # reels tab, 12 per page with like/comment/play counts (no known pagination query)
    "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery": {
        "doc_id": "27838951732404191", "endpoint": "api", "providers": []},
    # one post by numeric media id: media + first 11 comments + 12 owner posts; clean geo-gating
    "PolarisLoggedOutDesktopWWWPostRootContentQuery": {
        "doc_id": "28309390568695038", "endpoint": "api", "providers": []},
    # comments, 24 per page, cursor = the JSON string page_info.end_cursor verbatim
    "PolarisLoggedOutDesktopWWWPostCommentsPaginationQuery": {
        "doc_id": "27659279553772821", "endpoint": "api", "providers": []},
    # "accounts you might like": 44 users for an owner (by pk) / by Facebook id
    "PolarisAYMLFollowChainingListLoggedOutQuery": {
        "doc_id": "26772329349085526", "endpoint": "api", "providers": []},
    "PolarisLoggedOutDesktopWWWAYMLQuery": {
        "doc_id": "26631739266527266", "endpoint": "api", "providers": []},
    # hashtag / keyword page: ranked reels + related keywords (+ description)
    "PolarisLoggedOutPopularSearchPageQuery": {
        "doc_id": "29032174876406682", "endpoint": "api", "providers": []},
    # /explore/: the 8 keyword / profile sections
    "PolarisPopularSearchHomePageQuery": {
        "doc_id": "26965411179802517", "endpoint": "api", "providers": []},
    "PopularSearchHomeSectionPaginationQuery": {
        "doc_id": "27777580388517690", "endpoint": "api", "providers": []},
    # every item of one highlight reel
    "PolarisStoriesV3HighlightsLoggedOutPageQuery": {
        "doc_id": "28479441025019684", "endpoint": "api", "providers": ["PolarisCommunityNoteStoriesLabelEnabled"]},

    # ---- /graphql/query (logged-in family, anonymous with providers) -----------------
    # one post by shortcode: the full 86-key media item
    "PolarisPostRootQuery": {
        "doc_id": "28210188581965596", "endpoint": "query",
        "providers": ["PolarisMultiCaptionCarouselEnabled", "PolarisShortDramaEnabled"]},
    # a user's timeline, 12 full media per page, cursor "<media_pk>_<user_pk>"
    "PolarisProfilePostsQuery": {
        "doc_id": "39740939532171951", "endpoint": "query", "providers": _POSTS_PROVIDERS},
    "PolarisProfilePostsTabContentQuery_connection": {
        "doc_id": "28489798657316487", "endpoint": "query", "providers": _POSTS_PROVIDERS},
    # profile extras by pk: category, external link, bio links, clips count
    "PolarisProfilePageContentQuery": {
        "doc_id": "28036671149327607", "endpoint": "query", "providers": _PROFILE_PROVIDERS},
    # a location's ranked / recent posts
    "PolarisLocationPageTabContentQuery": {
        "doc_id": "28211016731901625", "endpoint": "query", "providers": _PROFILE_PROVIDERS},
}


def variables_for(name, **variables):
    """The query's variables plus every relay-provider boolean it declares."""
    out = dict(variables)
    for provider in QUERIES[name]["providers"]:
        out[f"__relay_internal__pv__{provider}relayprovider"] = PROVIDER_VALUES.get(provider, False)
    return out
