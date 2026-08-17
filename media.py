import json
from pathlib import Path

import requests

BASE_URL = "https://abi.com.vn"

OUTPUT_JSON = "media_public.json"
MEDIA_DIR = Path("media")

PER_PAGE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def get_all_media():
    all_media = []
    page = 1

    while True:
        print(f"Fetching media page {page}...")

        response = requests.get(
            f"{BASE_URL}/wp-json/wp/v2/media",
            headers=HEADERS,
            params={
                "per_page": PER_PAGE,
                "page": page,
            },
            timeout=30,
        )

        print("Status:", response.status_code)

        if response.status_code != 200:
            print(response.text[:500])
            break

        items = response.json()

        if not items:
            break

        all_media.extend(items)

        total_pages = int(
            response.headers.get("X-WP-TotalPages", 1)
        )

        total_media = int(
            response.headers.get("X-WP-Total", len(all_media))
        )

        print(
            f"  Downloaded metadata: {len(items)} "
            f"| Page {page}/{total_pages} "
            f"| Total: {total_media}"
        )

        if page >= total_pages:
            break

        page += 1

    return all_media


def download_media(items):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(items, start=1):
        source_url = item.get("source_url")

        if not source_url:
            continue

        # WordPress thường cung cấp:
        # 2026/08/image.jpg
        relative_path = (
            item.get("media_details", {})
            .get("file")
        )

        if relative_path:
            destination = MEDIA_DIR / relative_path
        else:
            destination = MEDIA_DIR / source_url.split("/")[-1]

        destination.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if destination.exists():
            print(
                f"[{index}/{len(items)}] SKIP: "
                f"{destination}"
            )
            continue

        print(
            f"[{index}/{len(items)}] Downloading: "
            f"{source_url}"
        )

        try:
            response = requests.get(
                source_url,
                headers=HEADERS,
                stream=True,
                timeout=60,
            )

            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        f.write(chunk)

        except Exception as e:
            print(f"ERROR: {source_url}")
            print(e)


def main():
    media = get_all_media()

    # Save metadata
    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            media,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(f"Media records: {len(media)}")
    print(f"Metadata saved: {OUTPUT_JSON}")

    # Download original files
    download_media(media)

    print()
    print("Completed")


if __name__ == "__main__":
    main()