#!/usr/bin/env python3
"""
Mall of Toys restock monitor.

Polls Shopify's per-product JSON endpoint (/products/<handle>.js) for each
watched product and sends a push notification the moment a variant flips from
unavailable -> available.

Runs in a loop inside one GitHub Actions job so we get ~60s granularity,
because GitHub's cron scheduler itself is only accurate to ~5-20 minutes.

Stdlib only. No pip install, no cold-start delay.
"""

import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- config

STORE = "https://malloftoys.com"

# Just the product handle -- the bit after /products/ in the URL.
# Add or remove lines here; nothing else needs to change.
HANDLES = [
    "cx-13-bahamut-blitz-bk1-50i",
    "ux-20-starter-glory-valkyrie-lf",
    "beyblade-x-cx-17-random-booster-10",
    "full-set-beyblade-x-cx-17-random-booster-vol-10",
    "cx-10-wolf-hunt-f0-60db",
]

# How long this job runs before exiting, and how often it polls.
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", 3300))   # 55 min
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", 60))   # 1 min

STATE_FILE = pathlib.Path("state.json")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# ---------------------------------------------------------------- helpers


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_product(handle):
    """Return Shopify's product dict, or None on any failure."""
    url = f"{STORE}/products/{handle}.js"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log(f"  ! {handle}: HTTP {e.code}")
    except Exception as e:  # timeouts, DNS, malformed JSON, etc.
        log(f"  ! {handle}: {type(e).__name__}: {e}")
    return None


def stock_of(product):
    """
    (in_stock, [names of available variants])

    A Shopify product is buyable if ANY variant is available. We report which
    ones so a partial restock (e.g. one colourway) is still actionable.
    """
    variants = product.get("variants") or []
    live = [v for v in variants if v.get("available")]
    names = [v.get("title") or product.get("title", "") for v in live]
    return (bool(live) or bool(product.get("available")), names)


def price_of(product):
    """Shopify reports price in cents."""
    cents = product.get("price")
    return f"${cents / 100:,.2f}" if isinstance(cents, int) else "?"


# ---------------------------------------------------------------- notifications


def _post(url, data, headers=None):
    req = urllib.request.Request(
        url, data=data, headers=headers or {}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:
        log(f"  ! notify failed ({url.split('/')[2]}): {e}")
        return False


def notify(title, body, url):
    """Fire every notification channel that has been configured via secrets."""
    sent = False

    # --- ntfy.sh: free, no account. Just pick an obscure topic name.
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        ok = _post(
            f"{server}/{topic}",
            body.encode("utf-8"),
            {
                "Title": title,
                "Priority": "urgent",
                "Tags": "rotating_light",
                "Click": url,
                "Actions": f"view, Buy now, {url}",
            },
        )
        sent = sent or ok

    # --- Pushover
    p_user, p_token = os.environ.get("PUSHOVER_USER"), os.environ.get("PUSHOVER_TOKEN")
    if p_user and p_token:
        ok = _post(
            "https://api.pushover.net/1/messages.json",
            urllib.parse.urlencode(
                {
                    "token": p_token,
                    "user": p_user,
                    "title": title,
                    "message": body,
                    "url": url,
                    "url_title": "Open product page",
                    "priority": 1,
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        sent = sent or ok

    # --- Discord webhook (optional)
    hook = os.environ.get("DISCORD_WEBHOOK")
    if hook:
        ok = _post(
            hook,
            json.dumps({"content": f"**{title}**\n{body}\n{url}"}).encode(),
            {"Content-Type": "application/json"},
        )
        sent = sent or ok

    if not sent:
        log("  ! NO notification channel configured or all failed")
    return sent


# ---------------------------------------------------------------- state


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- main


def main():
    state = load_state()          # handle -> True/False from previous runs
    dirty = False
    deadline = time.time() + RUN_SECONDS
    log(f"watching {len(HANDLES)} products, polling every {POLL_SECONDS}s")

    while True:
        for handle in HANDLES:
            product = fetch_product(handle)
            if product is None:
                continue  # transient error: don't touch state, just retry next tick

            in_stock, variants = stock_of(product)
            was_in_stock = state.get(handle, False)
            title = product.get("title", handle)

            if in_stock and not was_in_stock:
                url = f"{STORE}/products/{handle}"
                detail = ", ".join(v for v in variants if v) or "in stock"
                log(f"  *** RESTOCK: {title}")
                notify(
                    "RESTOCK: " + title,
                    f"{price_of(product)} - {detail}",
                    url,
                )
            elif was_in_stock and not in_stock:
                log(f"  --- sold out again: {title}")

            if in_stock != was_in_stock:
                state[handle] = in_stock
                dirty = True

            time.sleep(random.uniform(0.3, 1.0))  # be a polite neighbour

        if dirty:
            save_state(state)
            dirty = False

        if time.time() >= deadline:
            break
        time.sleep(POLL_SECONDS)

    log("run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
