import os
import json
import requests
import dotenv

dotenv.load_dotenv()

BASE_URL = "https://abi.com.vn"

USERNAME = os.getenv("WP_USERNAME")
APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

print("USERNAME:", USERNAME)
print("APP_PASSWORD:", APP_PASSWORD)

url = f"{BASE_URL}/wp-json/wp/v2/posts"

response = requests.get(
    url,
    params={
        "per_page": 5,
        "context": "edit"
    },
    auth=(USERNAME, APP_PASSWORD),
    timeout=30
)

print("Status:", response.status_code)

response.raise_for_status()

posts = response.json()

print("Số bài lấy được:", len(posts))

for post in posts:
    print(
        post["id"],
        "|",
        post["status"],
        "|",
        post["title"].get("rendered")
    )

with open("test_posts.json", "w", encoding="utf-8") as f:
    json.dump(
        posts,
        f,
        ensure_ascii=False,
        indent=2
    )

print("Đã lưu: test_posts.json")