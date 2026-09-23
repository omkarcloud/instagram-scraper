"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from instagram import refs
from instagram.posts import get_details
from instagram.users import get_posts, get_profile

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a username, @username, numeric id or any instagram.com profile link
    save("profile_taylorswift.json", get_profile(refs.resolve_user("taylorswift")))

    # 12 posts per page; pass next_cursor back as cursor= for the next page
    save("posts_taylorswift.json", get_posts(refs.resolve_user("taylorswift")))

    # a shortcode, numeric media id or any post / reel link
    save("post_DdcI4o0Prsz.json", get_details(refs.resolve_post("https://www.instagram.com/reel/DdcI4o0Prsz/")))
