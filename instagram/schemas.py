"""Marshmallow request schemas for every /instagram/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Instagram resolvers and the per-route schemas. Every schema's
load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair), auto-detected by refs.py:
  user       a username, @username, numeric user id or instagram.com profile link
  post       a shortcode, numeric media id or instagram.com post / reel / share link
  tag        a hashtag (with or without #) or an /explore/tags/ link
  location   a numeric location id or an /explore/locations/ link
  audio      a numeric audio id or a /reels/audio/ link
  highlight  a numeric highlight id, "highlight:<id>" or a /stories/highlights/ link
"""
from marshmallow import validate

from schema_fields import BaseSchema, ChoiceField, QueryField, RefField, StrippedString
from instagram import refs
from instagram.discovery import EXPLORE_SECTIONS


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class PostRefField(RefField):
    resolver = staticmethod(refs.resolve_post)


class TagRefField(RefField):
    resolver = staticmethod(refs.resolve_tag)


class LocationRefField(RefField):
    resolver = staticmethod(refs.resolve_location)


class AudioRefField(RefField):
    resolver = staticmethod(refs.resolve_audio)


class HighlightRefField(RefField):
    resolver = staticmethod(refs.resolve_highlight)


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=2000))
        super().__init__(**kwargs)


class EmptySchema(BaseSchema):
    pass


# ---- users -----------------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserRefField(metadata={"description": "username, @username, numeric user id or instagram.com profile link"})


class UserPageSchema(UserSchema):
    cursor = CursorField()


# ---- posts -----------------------------------------------------------------------------

class PostSchema(BaseSchema):
    post = PostRefField(metadata={"description": "shortcode, numeric media id or instagram.com post / reel / share link"})


class PostPageSchema(PostSchema):
    cursor = CursorField()


# ---- discovery -------------------------------------------------------------------------

class TagSchema(BaseSchema):
    tag = TagRefField(metadata={"description": "hashtag (with or without #) or an instagram.com/explore/tags/ link"})
    cursor = CursorField()


class KeywordSchema(BaseSchema):
    query = QueryField(max_length=150)
    cursor = CursorField()


class LocationSchema(BaseSchema):
    location = LocationRefField(metadata={"description": "numeric location id or an instagram.com/explore/locations/ link"})


class LocationPostsSchema(LocationSchema):
    tab = ChoiceField(["ranked", "recent"], load_default="ranked")


class AudioSchema(BaseSchema):
    audio = AudioRefField(metadata={"description": "numeric audio id or an instagram.com/reels/audio/ link"})


class AudioPageSchema(AudioSchema):
    cursor = CursorField()


class HighlightSchema(BaseSchema):
    highlight = HighlightRefField(metadata={"description": "numeric highlight id, highlight:<id> or a /stories/highlights/ link"})


class ExploreSectionSchema(BaseSchema):
    section = ChoiceField(EXPLORE_SECTIONS, load_default="trending_now")
    cursor = CursorField()
