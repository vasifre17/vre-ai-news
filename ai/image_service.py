import requests
from config import settings


def get_image_for_article(query: str) -> str:
    if settings.pexels_api_key:
        headers = {"Authorization": settings.pexels_api_key}
        resp = requests.get("https://api.pexels.com/v1/search", params={"query": query, "per_page": 1}, headers=headers, timeout=15)
        if resp.ok and resp.json().get("photos"):
            return resp.json()["photos"][0]["src"]["large"]
    return "https://images.unsplash.com/photo-1504711434969-e33886168f5c"
