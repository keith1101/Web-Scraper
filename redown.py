import csv
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

INPUT_FILE = "post_media_mapping.csv"
OUTPUT_DIR = Path("media_unmapped")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
}


def is_false(value):
    return str(value).strip().lower() in {
        "false",
        "0",
        "no",
        ""
    }


def get_filename(url):
    path = unquote(urlparse(url).path)

    filename = Path(path).name

    return filename or "unknown_file"


def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:
        rows = list(csv.DictReader(f))

    failed_rows = [
        row
        for row in rows
        if is_false(
            row.get("found_in_media_json")
        )
        and row.get("media_url")
    ]

    print(
        "Unmapped media:",
        len(failed_rows)
    )

    # tránh download cùng URL nhiều lần
    urls = list(dict.fromkeys(
        row["media_url"]
        for row in failed_rows
    ))

    for index, url in enumerate(
        urls,
        start=1
    ):
        filename = get_filename(url)

        destination = (
            OUTPUT_DIR /
            filename
        )

        print(
            f"[{index}/{len(urls)}] "
            f"{url}"
        )

        if destination.exists():
            print("  -> EXISTS")
            continue

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                stream=True,
                timeout=60
            )

            print(
                "  Status:",
                response.status_code
            )

            response.raise_for_status()

            with destination.open("wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        f.write(chunk)

            print(
                "  -> SAVED:",
                destination
            )

        except Exception as error:
            print(
                "  -> ERROR:",
                error
            )


if __name__ == "__main__":
    main()