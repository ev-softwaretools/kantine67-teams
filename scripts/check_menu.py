"""Check kantine67.at for a new Wochenmenü image and post it to a Teams channel.

Flow: fetch page -> find menu image -> compare hash with state/last.json ->
crop header/footer -> commit image -> post Adaptive Card to the Teams
Workflows webhook -> commit new state.

Env:
  TEAMS_WEBHOOK_URL  Teams Workflows webhook (GitHub secret)
  GITHUB_REPOSITORY  owner/repo (set by GitHub Actions)
  DRY_RUN=1          only download/crop and print the card, no git, no post
"""

import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image

PAGE_URL = "https://kantine67.at/"
MENU_LINK = "https://kantine67.at/#menue"
UA = "Mozilla/5.0 (compatible; kantine-menu-bot/1.0)"
ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "last.json"
MENU_DIR = ROOT / "menus"

# Crop for the current poster layout (1055x1491): drop the "WOCHENMENÜ" header
# and the "Weitere Snacks ... Buongiorno" footer. Fractions of the image height.
CROP_TOP = 0.262
CROP_BOTTOM = 0.922
EXPECTED_ASPECT = 1055 / 1491

DRY_RUN = os.environ.get("DRY_RUN") == "1"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def find_menu_image_url(page: str) -> str | None:
    m = re.search(r'https://[^"\s]+/storage/v1/object/sign/menus/[^"\s]+', page)
    return html.unescape(m.group(0)) if m else None


def crop(img_bytes: bytes) -> bytes:
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    if abs(w / h - EXPECTED_ASPECT) < 0.02:
        im = im.crop((0, int(h * CROP_TOP), w, int(h * CROP_BOTTOM)))
    else:
        print(f"Unexpected layout {w}x{h}, posting uncropped image")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def week_title(file_name: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", file_name)
    if not m:
        return "Wochenmenü"
    mon = dt.date.fromisoformat(m.group(1))
    fri = mon + dt.timedelta(days=4)
    if mon.month == fri.month:
        return f"Wochenmenü {mon.day}.–{fri.day}.{fri.month}.{fri.year}"
    return f"Wochenmenü {mon.day}.{mon.month}.–{fri.day}.{fri.month}.{fri.year}"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_and_push(paths: list[Path], message: str) -> str:
    git("add", *[str(p.relative_to(ROOT)) for p in paths])
    git("commit", "-m", message)
    git("push")
    return git("rev-parse", "HEAD")


def post_to_teams(title: str, image_url: str) -> None:
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "msteams": {"width": "Full"},
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"🍽️ Kantine67 – {title}",
                            "weight": "Bolder",
                            "size": "Medium",
                            "wrap": True,
                        },
                        {
                            "type": "Image",
                            "url": image_url,
                            "altText": title,
                            "size": "Stretch",
                            "selectAction": {"type": "Action.OpenUrl", "url": image_url},
                        },
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "kantine67.at", "url": MENU_LINK}
                    ],
                },
            }
        ],
    }
    if DRY_RUN:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    req = urllib.request.Request(
        os.environ["TEAMS_WEBHOOK_URL"],
        data=json.dumps(card).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"Teams webhook answered HTTP {r.status}")


def main() -> int:
    page = http_get(PAGE_URL).decode("utf-8", errors="replace")
    url = find_menu_image_url(page)
    if not url:
        print("No menu image found on the page, nothing to do")
        return 0

    raw = http_get(url)
    digest = hashlib.sha256(raw).hexdigest()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    if state.get("sha256") == digest:
        print("Menu unchanged")
        return 0

    source_name = url.split("?")[0].rsplit("/", 1)[-1]
    week = source_name[:10]
    title = week_title(source_name)
    if state.get("week") == week:
        title += " (aktualisiert)"

    MENU_DIR.mkdir(exist_ok=True)
    img_path = MENU_DIR / f"{week}-{digest[:8]}.jpg"
    img_path.write_bytes(crop(raw))
    print(f"New menu: {source_name} -> {img_path.name}")

    if DRY_RUN:
        post_to_teams(title, img_path.as_uri())
        return 0

    sha = commit_and_push([img_path], f"Add menu {img_path.name}")
    repo = os.environ["GITHUB_REPOSITORY"]
    image_url = f"https://raw.githubusercontent.com/{repo}/{sha}/menus/{img_path.name}"
    post_to_teams(title, image_url)

    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {"sha256": digest, "week": week, "source": source_name, "image": img_path.name},
            indent=2,
        )
        + "\n"
    )
    commit_and_push([STATE_FILE], f"Posted {img_path.name} to Teams")
    return 0


if __name__ == "__main__":
    sys.exit(main())
