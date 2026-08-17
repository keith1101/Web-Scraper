import json
import csv
import re
from urllib.parse import urlparse


POSTS_FILE = "posts_public.json"
MEDIA_FILE = "media_public.json"
OUTPUT_FILE = "post_media_mapping.csv"


# ==========================================
# Load JSON
# ==========================================

with open(POSTS_FILE, "r", encoding="utf-8") as f:
    posts = json.load(f)

with open(MEDIA_FILE, "r", encoding="utf-8") as f:
    media = json.load(f)


# ==========================================
# Build indexes
# ==========================================

# Map media ID -> media object
media_by_id = {
    item["id"]: item
    for item in media
}

# Map source_url -> media object
media_by_url = {
    item.get("source_url"): item
    for item in media
    if item.get("source_url")
}


# ==========================================
# Extract URLs from HTML
# ==========================================

def extract_media_urls(html):
    if not html:
        return []

    # lấy src="..."
    urls = re.findall(
        r'''(?:src|href)=["']([^"']+)["']''',
        html,
        flags=re.IGNORECASE
    )

    # Chỉ quan tâm wp-content/uploads
    urls = [
        url
        for url in urls
        if "/wp-content/uploads/" in url
    ]

    return list(dict.fromkeys(urls))


# ==========================================
# Find media by URL
# ==========================================

def find_media_by_url(url):
    # Match chính xác trước
    if url in media_by_url:
        return media_by_url[url]

    # WordPress content đôi khi dùng thumbnail:
    #
    # image-300x200.jpg
    #
    # nhưng source_url là:
    #
    # image.jpg

    parsed = urlparse(url)
    path = parsed.path

    # remove -300x200 trước extension
    normalized_path = re.sub(
        r"-\d+x\d+(?=\.[^.]+$)",
        "",
        path
    )

    for source_url, item in media_by_url.items():
        source_path = urlparse(source_url).path

        if source_path == normalized_path:
            return item

    return None


# ==========================================
# Create mapping
# ==========================================

rows = []

for post in posts:
    post_id = post.get("id")

    title = (
        post.get("title", {})
        .get("rendered", "")
    )

    # --------------------------------------
    # Featured image
    # --------------------------------------

    featured_id = post.get("featured_media")

    if featured_id:
        media_item = media_by_id.get(featured_id)

        rows.append({
            "post_id": post_id,
            "post_title": title,
            "relation": "featured",
            "media_id": featured_id,

            "media_url": (
                media_item.get("source_url", "")
                if media_item
                else ""
            ),

            "media_file": (
                media_item
                .get("media_details", {})
                .get("file", "")
                if media_item
                else ""
            ),

            "found_in_media_json":
                bool(media_item),
        })

    # --------------------------------------
    # Content images/files
    # --------------------------------------

    html = (
        post.get("content", {})
        .get("rendered", "")
    )

    urls = extract_media_urls(html)

    for url in urls:
        media_item = find_media_by_url(url)

        rows.append({
            "post_id": post_id,
            "post_title": title,
            "relation": "content",

            "media_id": (
                media_item.get("id", "")
                if media_item
                else ""
            ),

            "media_url": url,

            "media_file": (
                media_item
                .get("media_details", {})
                .get("file", "")
                if media_item
                else ""
            ),

            "found_in_media_json":
                bool(media_item),
        })


# ==========================================
# Export CSV
# ==========================================

with open(
    OUTPUT_FILE,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    fieldnames = [
        "post_id",
        "post_title",
        "relation",
        "media_id",
        "media_url",
        "media_file",
        "found_in_media_json",
    ]

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(rows)


print(f"Posts: {len(posts)}")
print(f"Media: {len(media)}")
print(f"Mappings: {len(rows)}")
print(f"Saved: {OUTPUT_FILE}")