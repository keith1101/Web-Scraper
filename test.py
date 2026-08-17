import json
import csv

with open(
    "normalized/post_media_mapping.json",
    encoding="utf-8"
) as f:
    mappings = json.load(f)

unknown = [
    item
    for item in mappings
    if not item["media_exists"]
]

print("Unknown media:", len(unknown))

with open(
    "unknown_media.csv",
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "post_id",
            "media_id",
            "relations"
        ]
    )

    writer.writeheader()

    for item in unknown:
        writer.writerow({
            "post_id": item["post_id"],
            "media_id": item["media_id"],
            "relations": ",".join(
                item["relations"]
            )
        })