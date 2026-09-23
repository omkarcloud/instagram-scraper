# 📸 Instagram Scraper

Instagram Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Instagram data for free.

## ✨ What Can I Get?

- 👤 **Profiles of 3B+ monthly users** — bio, links, followers, post count, category & highlights
- 🎬 **Every post & reel** — captions, likes, comments, play counts, audio, tagged users & HD media
- 💬 **Comments, stories & look-alikes** — comment pages, every highlight story, 50 similar accounts
- 🔥 **Hashtags, places, songs & trends** — top reels per hashtag, locations, audio pages & what's trending now

## 🎥 Example: A Full Instagram Profile

```json
{
  "id": "11830955",
  "username": "taylorswift",
  "full_name": "Taylor Swift",
  "link": "https://www.instagram.com/taylorswift/",
  "profile_picture": "https://scontent.cdninstagram.com/v/t51.82787-19/818902239_18699523633054956_5239385355012066680_n.jpg?_nc_cat=1&ccb=7-5&_nc_sid=bf7eb4&efg=eyJ2ZW5jb2RlX3RhZyI6InByb2ZpbGVfcGljLnd3dy4xMDgwLkMzIn0%3D&_nc_ohc=LjiOo-1I3FoQ7kNvwH8yxWN&_nc_oc=AdqsdA37nXgNuLPe0Lk_gMakAiebU0lKGdgDL8HCJT8yuS4RUQLlKvmbmPYBtw5JiQc&_nc_zt=24&_nc_ht=scontent.cdninstagram.com&_nc_gid=UzJZz7q-jWuOJVdxG5fVHA&_nc_ss=7fa8c&oh=00_AQI1TEFv5iCKSwY0a7JywYW8UnHvwyyWbhRYOELzvhuY_Q&oe=6AB978C4",
  "is_verified": true,
  "is_private": false,
  "biography": "And, baby, that's sh0w business f0r y0u. ❤️‍🔥",
  "bio_links": [
    { "title": null, "link": "http://store.taylorswift.com", "type": "external", "is_pinned": false }
  ],
  "external_link": "http://store.taylorswift.com",
  "account_type": "creator",
  "follower_count": 272831029,
  "following_count": 0,
  "post_count": 709,
  "has_reels": true,
  "threads_username": "taylorswift",
  "highlights": [
    {
      "id": "18520347457009686",
      "title": "❤️‍🔥",
      "link": "https://www.instagram.com/stories/highlights/18520347457009686/"
    },
    {
      "id": "17991384335533906",
      "title": "🤍",
      "link": "https://www.instagram.com/stories/highlights/17991384335533906/"
    }
  ],
  "has_more_highlights": true
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Instagram Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/instagram-scraper
cd instagram-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/users/profile?user=taylorswift"
```

```json
{
  "id": "11830955",
  "username": "taylorswift",
  "full_name": "Taylor Swift",
  "link": "https://www.instagram.com/taylorswift/",
  "is_verified": true,
  "biography": "And, baby, that's sh0w business f0r y0u. ❤️‍🔥",
  "external_link": "http://store.taylorswift.com",
  "account_type": "creator",
  "follower_count": 272830984,
  "following_count": 0,
  "post_count": 709,
  "threads_username": "taylorswift",
  "highlights": [
    { "id": "18520347457009686", "title": "❤️‍🔥" },
    { "id": "17991384335533906", "title": "🤍" }
  ]
}
```

All 19 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

19 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| User Profile | `/users/profile` | Bio, links, followers, post count, category and highlights |
| User Posts | `/users/posts` | A user's posts with likes, comments, captions and media, 12 per page |
| User Reels | `/users/reels` | A user's reels with play counts, video links and audio, 12 per page |
| Post Details | `/posts/details` | Everything about one post or reel in a single call |
| Post Comments | `/posts/comments` | Comments with text, likes and commenter, 24 per page |
| Post Media | `/posts/media` | Every image size and video rendition, ready to download |
| User Highlights | `/users/highlights` | Story highlights with titles and covers |
| Highlight Stories | `/highlights/items` | Every story in a highlight with media links |
| Similar Users | `/users/similar` | Up to 50 accounts Instagram suggests next to a user |
| Hashtag Posts | `/hashtags/posts` | Top reels for any hashtag, plus related keywords |
| Search Keywords | `/search/keywords` | Top reels for any keyword, plus a topic summary |
| Location Details | `/locations/details` | Name, address, coordinates, post count and top posts |
| Location Posts | `/locations/posts` | Top or most recent posts tagged at a place |
| Audio Details | `/audio/details` | A song's title, artist, cover and reel count |
| Audio Reels | `/audio/reels` | Reels that use a song, 12 per page |
| Trending | `/explore/trending` | What's trending now: keywords, moments and rising profiles |
| Trending Section | `/explore/section` | More entries from any trending section |
| Resolve User | `/users/resolve` | Username to numeric user ID, and back |
| Resolve Post | `/posts/resolve` | Post shortcode or link to media ID, and back |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-instagram-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-instagram-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-instagram-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/users/profile",
    params={"user": "taylorswift"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Instagram Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Instagram%20Scraper%20API.)

[![Ask Us by Email about Instagram Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Instagram%20Scraper%20API&body=I%20need%20help%20using%20the%20Instagram%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV shows, ratings, cast & box office
- [**Threads Scraper**](https://github.com/omkarcloud/threads-scraper) — Threads posts, profiles, replies & search
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/instagram-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/instagram-scraper)
