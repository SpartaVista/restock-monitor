# Mall of Toys restock monitor

Polls Shopify's product JSON endpoint every 60 seconds and pushes a notification
to your phone the instant a sold-out item becomes buyable again.

## Setup (about 10 minutes)

### 1. Create the repo

Make a **public** repo on GitHub and drop these files in:

```
monitor.py
state.json                       <- just: {}
.github/workflows/restock.yml
```

Public matters: GitHub Actions is unlimited and free on public repos. On a
private repo you get 2,000 minutes/month, and this job burns ~55 minutes an
hour, which would blow the cap in about a day and a half. Nothing sensitive
lives in the code — your keys go in encrypted secrets, not the repo.

### 2. Pick a notification channel

**ntfy.sh** is the easiest — no account, no cost:

1. Install the ntfy app (iOS / Android).
2. Invent an obscure topic name, e.g. `mot-restock-a7f3k9qx`. Anyone who guesses
   the topic can read it, so make it random, not `beyblade`.
3. Subscribe to that topic in the app.

**Pushover** ($5 one-time) is more reliable for critical alerts and lets you set
a sound that overrides silent mode — worth it if a drop lands overnight.

Either works; the script fires whichever you configure, and you can enable both.

### 3. Add secrets

Repo → Settings → Secrets and variables → Actions → **New repository secret**.
Add only the ones you're using:

| Secret            | Value                                    |
| ----------------- | ---------------------------------------- |
| `NTFY_TOPIC`      | your topic name, e.g. `mot-restock-a7f3k9qx` |
| `PUSHOVER_USER`   | your Pushover user key                   |
| `PUSHOVER_TOKEN`  | your Pushover app token                  |
| `DISCORD_WEBHOOK` | a Discord webhook URL (optional)         |

### 4. Test it

Actions tab → **Restock monitor** → **Run workflow**. Watch the log. You should
see it list the four products; any that are currently in stock will fire an
alert immediately.

To force a test alert, temporarily add a handle you know is in stock (grab one
from the store's front page) and re-run.

## Adding or removing products

Edit the `HANDLES` list at the top of `monitor.py`. The handle is just the part
of the URL after `/products/` — drop any `?_pos=...&_sid=...` tracking junk:

```
https://malloftoys.com/products/cx-13-bahamut-blitz-bk1-50i?_pos=16&_sid=abc
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^ this bit
```

## How it works, and why it's built this way

- **It reads `/products/<handle>.js`, not the HTML page.** Shopify serves a JSON
  object with an `available: true/false` flag per variant. That's the same data
  the "Add to cart" button uses. Scraping the rendered page instead would give
  you false alarms every time they tweak a banner.
- **The cron fires hourly, but the job long-polls for 55 minutes.** GitHub's
  scheduler is *not* punctual — a `*/5` cron routinely drifts 5–20 minutes,
  especially at peak times, and can be skipped entirely under load. Looping
  inside one job sidesteps that and gets you true 60-second granularity.
- **`state.json` is committed back to the repo** so a restock notifies you once,
  not sixty times an hour, and so state survives across runs.
- **Transient errors don't touch state.** A timeout is not a stock-out, so a
  blip won't fake a restock alert on the next successful poll.

## Things that will bite you

- **Scheduled workflows get disabled after 60 days of repo inactivity.** GitHub
  emails you first. Any commit resets the clock.
- **This site does timed drops.** The product pages carry a countdown and a
  "redrops tonight" banner, meaning stock appears at an announced moment and can
  be gone in minutes. A 60-second monitor is good, but for a hyped drop the
  people who checked out fastest are the ones who were already sitting on the
  page. Treat the monitor as your safety net, not your whole strategy — also get
  on the store's email list and follow the drop announcements.
- **Don't crank `POLL_SECONDS` down to 5.** Four products at 60s is ~240
  requests/hour, which is unremarkable. Hammering a small store's storefront is
  both rude and a good way to get your runner IPs rate-limited.
