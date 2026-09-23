"""Cache TTL per /instagram/* endpoint (cache.py, keyed on the validated
params — `user=nike`, `user=@Nike` and a pasted profile link all validate
to the same key).

Instagram is a live social feed: like / comment / play counts move by the
minute on popular posts and keyword pages turn over constantly, so the
tiers stay short. Profiles (bio, follower count), location records and
the id resolvers change slowly. Cursor pages are cached per cursor — a
repeated page request is served from the cache, a new cursor is a new key.
"""
from datetime import timedelta

RESOLVE_CACHE = timedelta(hours=24)          # username <-> id, code <-> id
PROFILE_CACHE = timedelta(minutes=30)
USER_MEDIA_CACHE = timedelta(minutes=10)     # posts / reels pages
HIGHLIGHTS_CACHE = timedelta(hours=1)        # tray and highlight items
SIMILAR_CACHE = timedelta(hours=6)
POST_CACHE = timedelta(minutes=10)           # details, media files
COMMENTS_CACHE = timedelta(minutes=5)
KEYWORD_CACHE = timedelta(minutes=15)        # hashtag / keyword pages
LOCATION_CACHE = timedelta(hours=6)          # the location record
LOCATION_POSTS_CACHE = timedelta(minutes=15)
AUDIO_CACHE = timedelta(minutes=30)
EXPLORE_CACHE = timedelta(minutes=30)
