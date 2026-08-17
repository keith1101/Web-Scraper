import json
import requests

BASE_URL = "https://abi.com.vn"
OUTPUT_FILE = "posts_public.json"
PER_PAGE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def get_all_public_posts():
    all_posts = []
    page = 1

    while True:
        print(f"Fetching page {page}...")

        response = requests.get(
            f"{BASE_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": PER_PAGE,
                "page": page,
                "status": "publish",
            },
            timeout=30,
        )

        print("Status:", response.status_code)

        if response.status_code != 200:
            print(response.text[:500])
            break

        posts = response.json()

        if not posts:
            break

        all_posts.extend(posts)

        total_pages = int(
            response.headers.get("X-WP-TotalPages", 1)
        )

        total_posts = int(
            response.headers.get("X-WP-Total", len(all_posts))
        )

        print(
            f"  Downloaded {len(posts)} posts "
            f"| Page {page}/{total_pages} "
            f"| Total: {total_posts}"
        )

        if page >= total_pages:
            break

        page += 1

    return all_posts


def main():
    posts = get_all_public_posts()

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            posts,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"\nCompleted: {len(posts)} posts")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()