import json
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup


def extract_media(html: str) -> Dict[str, List[str]]:
    """
    Extracts high-resolution images and videos from Amazon product page HTML.
    """
    images: List[str] = []
    videos: List[str] = []

    if not html:
        return {"images": images, "videos": videos}

    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract from colorImages inline JS JSON
    json_matches = re.findall(r"parseJSON\(\s*['\"](\[.*?\])['\"]\s*\)", html)
    for raw in json_matches:
        try:
            unescaped = raw.replace(r"\'", "'").replace(r'\"', '"')
            items = json.loads(unescaped)
            for item in items:
                if isinstance(item, dict):
                    # Check for video
                    if item.get("type") == "video" or "videoUrl" in item:
                        v_url = item.get("videoUrl") or item.get("url")
                        if v_url and v_url not in videos:
                            videos.append(v_url)
                    # Check for images
                    img_url = item.get("hiRes") or item.get("large")
                    if img_url and img_url not in images:
                        images.append(img_url)
                    # Check main dict
                    if isinstance(item.get("main"), dict):
                        for m_url in item["main"].keys():
                            if m_url not in images:
                                images.append(m_url)
        except Exception:
            pass

    # 2. Extract from landingImage tag
    landing_img = soup.find("img", id="landingImage")
    if landing_img:
        # Check dynamic image JSON attribute
        dyn = landing_img.get("data-a-dynamic-image")
        if dyn:
            try:
                dyn_dict = json.loads(dyn)
                for u in dyn_dict.keys():
                    if u not in images:
                        images.append(u)
            except Exception:
                pass

        # Check data-old-hires
        old_hires = landing_img.get("data-old-hires")
        if old_hires and old_hires not in images:
            images.append(old_hires)

        # Check src
        src = landing_img.get("src")
        if src and not src.startswith("data:") and src not in images:
            images.append(src)

    # 3. Extract thumbnail images in image block
    alt_images = soup.select("#altImages ul li img, #imageBlock img")
    for img in alt_images:
        src = img.get("src")
        if src and "play-button" not in src and not src.startswith("data:"):
            # If thumbnail format like ._SX38_SY50_CR... convert to large URL if possible
            large_url = re.sub(r"\._[A-Z0-9_,]+_\.", ".", src)
            if large_url not in images:
                images.append(large_url)

    # 4. Extract videos from video elements or video script blocks
    video_tags = soup.select("video source, video[src]")
    for v in video_tags:
        v_src = v.get("src")
        if v_src and v_src not in videos:
            videos.append(v_src)

    # Search script tags for mp4 video links
    mp4_matches = re.findall(r'https?://[^\s"\']+\.mp4', html)
    for v in mp4_matches:
        if v not in videos:
            videos.append(v)

    return {
        "images": images,
        "videos": videos,
    }
