import json
import re
from pathlib import Path
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

POSTS_FILE = Path("posts_public.json")
MEDIA_FILE = Path("media_public.json")

MEDIA_DIRECTORY = Path("media")
OUTPUT_DIRECTORY = Path("normalized")

POSTS_OUTPUT = OUTPUT_DIRECTORY / "posts.json"
MEDIA_OUTPUT = OUTPUT_DIRECTORY / "media.json"
MAPPING_OUTPUT = OUTPUT_DIRECTORY / "post_media_mapping.json"


# ============================================================
# HELPERS
# ============================================================

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def get_rendered(obj, field):
    """
    WordPress fields frequently look like:

    {
        "title": {
            "rendered": "..."
        }
    }
    """

    value = obj.get(field, {})

    if isinstance(value, dict):
        return value.get("rendered", "")

    return value or ""


def extract_wp_image_ids(html):
    """
    Example:

    class="wp-image-5878"

    -> 5878
    """

    if not html:
        return []

    ids = re.findall(
        r"\bwp-image-(\d+)\b",
        html,
        flags=re.IGNORECASE
    )

    # remove duplicates while preserving order
    return list(
        dict.fromkeys(
            int(media_id)
            for media_id in ids
        )
    )


# ============================================================
# NORMALIZE POSTS
# ============================================================

def normalize_post(post):
    return {
        "id": post.get("id"),

        "type": post.get("type"),
        "status": post.get("status"),

        "slug": post.get("slug"),
        "source_url": post.get("link"),

        "published_at": post.get("date"),
        "published_at_gmt": post.get("date_gmt"),

        "modified_at": post.get("modified"),
        "modified_at_gmt": post.get("modified_gmt"),

        "title": get_rendered(
            post,
            "title"
        ),

        "content_html": get_rendered(
            post,
            "content"
        ),

        "excerpt_html": get_rendered(
            post,
            "excerpt"
        ),

        "author_id": post.get("author"),

        "featured_media_id": (
            post.get("featured_media")
            or None
        ),

        "category_ids": (
            post.get("categories")
            or []
        ),

        "tag_ids": (
            post.get("tags")
            or []
        ),

        "comment_status": post.get(
            "comment_status"
        ),
    }


# ============================================================
# NORMALIZE MEDIA
# ============================================================

def normalize_media(item):
    details = item.get(
        "media_details",
        {}
    )

    relative_path = details.get(
        "file"
    )

    local_path = None
    file_exists = False

    if relative_path:
        local_file = (
            MEDIA_DIRECTORY /
            relative_path
        )

        local_path = str(
            local_file.as_posix()
        )

        file_exists = (
            local_file.is_file()
        )

    filesize = item.get("filesize")

    if filesize is None:
        filesize = details.get(
            "filesize"
        )

    return {
        "id": item.get("id"),

        "type": item.get("type"),
        "status": item.get("status"),

        "slug": item.get("slug"),

        "uploaded_at": item.get("date"),
        "uploaded_at_gmt": item.get(
            "date_gmt"
        ),

        "modified_at": item.get(
            "modified"
        ),

        "title": get_rendered(
            item,
            "title"
        ),

        "caption_html": get_rendered(
            item,
            "caption"
        ),

        "description_html": get_rendered(
            item,
            "description"
        ),

        "alt_text": item.get(
            "alt_text",
            ""
        ),

        "author_id": item.get(
            "author"
        ),

        # WordPress attachment parent
        "parent_post_id": (
            item.get("post")
            or None
        ),

        "media_type": item.get(
            "media_type"
        ),

        "mime_type": item.get(
            "mime_type"
        ),

        "filename": (
            item.get("filename")
            or (
                Path(relative_path).name
                if relative_path
                else None
            )
        ),

        "relative_path": relative_path,

        "local_path": local_path,

        "source_url": item.get(
            "source_url"
        ),

        "width": details.get(
            "width"
        ),

        "height": details.get(
            "height"
        ),

        "filesize": filesize,

        # useful for validation
        "file_exists": file_exists,
    }


# ============================================================
# POST <-> MEDIA MAPPING
# ============================================================

def add_relation(
    relation_map,
    post_id,
    media_id,
    relation
):
    if not post_id or not media_id:
        return

    key = (
        int(post_id),
        int(media_id)
    )

    relation_map[key].add(
        relation
    )


def build_mapping(posts, media):
    """
    Mapping sources:

    1. post.featured_media
    2. wp-image-{id} in content.rendered
    3. media.post
    """

    relations = defaultdict(set)

    media_ids = {
        item.get("id")
        for item in media
        if item.get("id") is not None
    }

    post_ids = {
        post.get("id")
        for post in posts
        if post.get("id") is not None
    }

    # --------------------------------------------------------
    # Relations coming from Posts
    # --------------------------------------------------------

    for post in posts:
        post_id = post.get("id")

        # Featured image
        featured_media = post.get(
            "featured_media"
        )

        if featured_media:
            add_relation(
                relations,
                post_id,
                featured_media,
                "featured"
            )

        # Images embedded inside post content
        html = get_rendered(
            post,
            "content"
        )

        content_media_ids = (
            extract_wp_image_ids(
                html
            )
        )

        for media_id in content_media_ids:
            add_relation(
                relations,
                post_id,
                media_id,
                "content"
            )

    # --------------------------------------------------------
    # Relations coming from Media
    # --------------------------------------------------------

    for item in media:
        media_id = item.get("id")
        parent_post_id = item.get(
            "post"
        )

        if parent_post_id:
            add_relation(
                relations,
                parent_post_id,
                media_id,
                "attached"
            )

    # --------------------------------------------------------
    # Produce normalized mapping
    # --------------------------------------------------------

    output = []

    for (
        post_id,
        media_id
    ), relation_types in sorted(
        relations.items()
    ):

        output.append({
            "post_id": post_id,
            "media_id": media_id,

            "relations": sorted(
                relation_types
            ),

            "post_exists": (
                post_id in post_ids
            ),

            "media_exists": (
                media_id in media_ids
            ),
        })

    return output


# ============================================================
# VALIDATION / SUMMARY
# ============================================================

def print_summary(
    raw_posts,
    raw_media,
    normalized_media,
    mappings
):
    missing_media_records = [
        item
        for item in normalized_media
        if not item["file_exists"]
    ]

    invalid_mapping = [
        row
        for row in mappings
        if not row["media_exists"]
    ]

    featured_count = sum(
        1
        for row in mappings
        if "featured" in row["relations"]
    )

    content_count = sum(
        1
        for row in mappings
        if "content" in row["relations"]
    )

    attached_count = sum(
        1
        for row in mappings
        if "attached" in row["relations"]
    )

    print()
    print("=" * 60)
    print("NORMALIZATION SUMMARY")
    print("=" * 60)

    print(
        "Posts:",
        len(raw_posts)
    )

    print(
        "Media:",
        len(raw_media)
    )

    print(
        "Mappings:",
        len(mappings)
    )

    print()
    print(
        "Featured relations:",
        featured_count
    )

    print(
        "Content relations:",
        content_count
    )

    print(
        "Attached relations:",
        attached_count
    )

    print()
    print(
        "Local media missing:",
        len(missing_media_records)
    )

    print(
        "Mapping references unknown media:",
        len(invalid_mapping)
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("Loading source files...")

    posts = load_json(
        POSTS_FILE
    )

    media = load_json(
        MEDIA_FILE
    )

    print(
        f"Loaded {len(posts)} posts"
    )

    print(
        f"Loaded {len(media)} media records"
    )

    # --------------------------------------------------------
    # Normalize
    # --------------------------------------------------------

    normalized_posts = [
        normalize_post(post)
        for post in posts
    ]

    normalized_media = [
        normalize_media(item)
        for item in media
    ]

    # --------------------------------------------------------
    # Mapping
    # --------------------------------------------------------

    mapping = build_mapping(
        posts,
        media
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_json(
        POSTS_OUTPUT,
        normalized_posts
    )

    save_json(
        MEDIA_OUTPUT,
        normalized_media
    )

    save_json(
        MAPPING_OUTPUT,
        mapping
    )

    print_summary(
        posts,
        media,
        normalized_media,
        mapping
    )

    print()
    print("Saved:")
    print(
        f"  {POSTS_OUTPUT}"
    )
    print(
        f"  {MEDIA_OUTPUT}"
    )
    print(
        f"  {MAPPING_OUTPUT}"
    )


if __name__ == "__main__":
    main()