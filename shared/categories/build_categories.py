#!/usr/bin/env python3
"""Build shared/categories/domains.json from AdGuard companiesdb (CC BY-SA 4.0,
https://github.com/AdguardTeam/companiesdb, data derived from WhoTracks.me).

Usage: build_categories.py trackers.json companies.json out.json

Output: {"v":1, "source":..., "domains": {"doubleclick.net": ["ads", "Google", "Google Marketing"], ...}}
Lookup is by longest matching domain suffix.
"""
import json, sys

# AdGuard category -> WhoSees category
CAT = {
    "advertising": "ads", "pornvertising": "ads",
    "site_analytics": "analytics", "mobile_analytics": "analytics", "telemetry": "analytics",
    "social_media": "social",
    "audio_video_player": "streaming",
    "cdn": "cdn", "hosting": "cloud", "essential": "cloud",
    # third-party scripts that follow you across sites
    "customer_interaction": "tracker", "comments": "tracker", "misc": "tracker", "unknown": "tracker",
    "extensions": "tracker", "email": "tracker", "consent": "tracker",
}

# Services people use on purpose: label them for what they are, not as trackers.
OVERRIDES = {
    "facebook.com": ["social", "Meta", "Facebook"], "instagram.com": ["social", "Meta", "Instagram"],
    "cdninstagram.com": ["social", "Meta", "Instagram"], "whatsapp.net": ["messaging", "Meta", "WhatsApp"],
    "whatsapp.com": ["messaging", "Meta", "WhatsApp"], "messenger.com": ["messaging", "Meta", "Messenger"],
    "twitter.com": ["social", "X", "X (Twitter)"], "x.com": ["social", "X", "X (Twitter)"], "twimg.com": ["social", "X", "X (Twitter)"],
    "reddit.com": ["social", "Reddit", "Reddit"], "redd.it": ["social", "Reddit", "Reddit"], "redditmedia.com": ["social", "Reddit", "Reddit"],
    "tiktok.com": ["social", "ByteDance", "TikTok"], "tiktokcdn.com": ["social", "ByteDance", "TikTok"],
    "linkedin.com": ["social", "Microsoft", "LinkedIn"], "pinterest.com": ["social", "Pinterest", "Pinterest"],
    "github.com": ["cloud", "Microsoft", "GitHub"], "githubusercontent.com": ["cloud", "Microsoft", "GitHub"],
    "discord.com": ["messaging", "Discord", "Discord"], "discord.gg": ["messaging", "Discord", "Discord"],
    "discordapp.com": ["messaging", "Discord", "Discord"], "discordapp.net": ["messaging", "Discord", "Discord"],
    "slack.com": ["messaging", "Salesforce", "Slack"], "signal.org": ["messaging", "Signal", "Signal"],
    "telegram.org": ["messaging", "Telegram", "Telegram"], "zoom.us": ["messaging", "Zoom", "Zoom"],
    "teams.microsoft.com": ["messaging", "Microsoft", "Teams"],
    "netflix.com": ["streaming", "Netflix", "Netflix"], "nflxvideo.net": ["streaming", "Netflix", "Netflix"],
    "nflxso.net": ["streaming", "Netflix", "Netflix"], "spotify.com": ["streaming", "Spotify", "Spotify"],
    "scdn.co": ["streaming", "Spotify", "Spotify"], "twitch.tv": ["streaming", "Amazon", "Twitch"],
    "steampowered.com": ["streaming", "Valve", "Steam"], "steamcontent.com": ["streaming", "Valve", "Steam"],
    "steamstatic.com": ["streaming", "Valve", "Steam"], "steamserver.net": ["streaming", "Valve", "Steam"],
    "youtube.com": ["streaming", "Google", "YouTube"], "googlevideo.com": ["streaming", "Google", "YouTube"],
    "ytimg.com": ["streaming", "Google", "YouTube"],
    "google.com": ["cloud", "Google", "Google"],
    "1e100.net": ["cloud", "Google", "Google Servers"], "1e100cdn.net": ["cloud", "Google", "Google Servers"], "googleapis.com": ["cloud", "Google", "Google APIs"],
    "gstatic.com": ["cdn", "Google", "Google Static"], "gmail.com": ["cloud", "Google", "Gmail"],
    "anthropic.com": ["cloud", "Anthropic", "Claude"], "claude.ai": ["cloud", "Anthropic", "Claude"],
    "openai.com": ["cloud", "OpenAI", "OpenAI"], "chatgpt.com": ["cloud", "OpenAI", "ChatGPT"],
    "brave.com": ["cloud", "Brave", "Brave"], "bravesoftware.com": ["cloud", "Brave", "Brave"],
    "mozilla.org": ["cloud", "Mozilla", "Mozilla"], "mozilla.net": ["cloud", "Mozilla", "Mozilla"],
    "fedoraproject.org": ["cloud", "Fedora", "Fedora updates"], "flathub.org": ["cloud", "Flathub", "Flathub"],
    "ubuntu.com": ["cloud", "Canonical", "Ubuntu"], "microsoft.com": ["cloud", "Microsoft", "Microsoft"],
    "windowsupdate.com": ["cloud", "Microsoft", "Windows Update"], "live.com": ["cloud", "Microsoft", "Microsoft account"],
    "office.com": ["cloud", "Microsoft", "Microsoft 365"], "apple.com": ["cloud", "Apple", "Apple"],
    "icloud.com": ["cloud", "Apple", "iCloud"], "wikipedia.org": ["other", "Wikimedia", "Wikipedia"],
    "cloudflare.com": ["cdn", "Cloudflare", "Cloudflare"], "akamaihd.net": ["cdn", "Akamai", "Akamai"],
    "akamaized.net": ["cdn", "Akamai", "Akamai"], "fastly.net": ["cdn", "Fastly", "Fastly"],
}

# Shorter owner names
SHORT = {"Meta Platforms, Inc.": "Meta", "Microsoft Corporation": "Microsoft", "Amazon": "Amazon",
         "comScore, Inc.": "comScore", "Alphabet": "Google"}


def short(name):
    if name in SHORT: return SHORT[name]
    for suf in (", Inc.", " Inc.", " Inc", " LLC", " Ltd.", " Ltd", " GmbH", " Corporation", " Corp."):
        if name.endswith(suf): return name[: -len(suf)].rstrip(",")
    return name


def main(trackers_path, companies_path, out_path):
    t = json.load(open(trackers_path))
    companies = json.load(open(companies_path))["companies"]
    cats = t["categories"]
    out = {}
    for domain, tid in t["trackerDomains"].items():
        tr = t["trackers"].get(tid)
        if not tr: continue
        cat = CAT.get(cats.get(str(tr.get("categoryId"))), "tracker")
        owner = short(companies.get(tr.get("companyId"), {}).get("name") or tr.get("name") or "")
        out[domain.lower()] = [cat, owner, tr.get("name") or owner]
    out.update(OVERRIDES)
    json.dump({"v": 1, "source": "AdGuard companiesdb (CC BY-SA 4.0) + WhoSees overrides",
               "updated": t.get("timeUpdated"), "domains": dict(sorted(out.items()))},
              open(out_path, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"{len(out)} domains -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
