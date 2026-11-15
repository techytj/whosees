<p align="center"><img src="website/img/icon.png" width="96" alt=""></p>

# WhoSees

See who your apps are talking to. WhoSees shows, live on a world map, which app on your computer or phone is sending data, which company receives it, where in the world it goes, and what kind of data it probably is, in plain English.

- **Windows, Linux and Android.**
- **Nothing leaves your device.** All the work happens locally. There's no account, no server and no tracking.
- **Only runs while you look.** Press Start to see what's happening, press Stop and it's completely off.
- **Free, every feature.** If it's useful to you, you can [buy me a coffee](https://whosees.app/#support).

Website: [whosees.app](https://whosees.app)

## How it was made

WhoSees is built by one independent developer with the help of an AI assistant (Claude, by Anthropic), which wrote much of the code under my direction. I designed it, made the decisions and tested every version on real Windows, Linux and Android devices. Because an app that looks at network traffic has to earn trust, all of it is open source so anyone can check what it does.

## What it shows

- **Which app**: real app names and icons.
- **Which company**: the owner of each address, with trackers, advertisers and analytics labelled (AdGuard companiesdb / WhoTracks.me).
- **Where**: city and country from the offline DB-IP Lite database, drawn on an offline map.
- **What kind of data**: "seen" when an app sends something unencrypted (for example your location), otherwise what that kind of company usually collects, clearly marked "likely".
- **Warnings**: dangerous websites, known malware and botnet servers, and suspicious behaviour like programs running from a temporary folder.

WhoSees reads where traffic goes, never what's inside encrypted traffic.

## How it works

| | How WhoSees sees connections |
|---|---|
| **Linux** | Standard mode reads the kernel's connection table. Deep mode (asks for your password) also reads packet headers for website names. |
| **Windows** | Standard mode reads Windows' connection tables. Deep mode (asks for administrator approval) uses Windows' built-in network events (ETW). |
| **Android** | A local-only VPN: the phone hands every connection to WhoSees, which sends it straight on to where it was going. Nothing goes to a VPN server. |

WhoSees can also block, while a live view runs: a whole app (Windows, Android), a company, a website, a country, or every tracker and advertiser at once. On a computer blocking needs Deep mode; the firewall rules are removed when you press Stop. You can save a PDF report of everything a live view found.

## Build from source

You need Rust, Node.js and, for Android, the Android SDK/NDK and JDK 21.

```
cd desktop/app && npm install
desktop/run.sh                              # run on Linux from source

shared/geo/fetch_and_build.sh               # IP location + network owner (DB-IP Lite)
shared/categories/fetch_and_build.sh        # tracker and ad domains (AdGuard companiesdb)
shared/threats/fetch_and_build.sh           # dangerous domains and servers
pmtiles extract https://build.protomaps.com/<date>.pmtiles shared/map/world-z6.pmtiles --maxzoom=6

cd android && ./gradlew assembleRelease     # Android app
```

The Windows build and tests run in a Windows VM over SSH. Copy `tools/local.env.example` to `tools/local.env` and fill in your own machines.

## Tests

`tools/regress.sh` runs everything: the Rust unit tests, a private network sandbox with fake servers, the real app on hidden screens at desktop and phone size, Deep mode, the Android engine, the Android app on an emulator, the Windows VM, and the installers.

## Layout

- `desktop/agent`: Rust capture agent for Linux and Windows
- `desktop/app`: the app's interface (Electron, MapLibre with an offline map), also used on Android
- `android/engine`: Rust VPN engine for Android, sharing the agent's analysis code; `android/app`: the Android shell
- `shared/`: location, tracker and threat data builders, map fonts
- `website/`: whosees.app

## Code signing policy

Windows installers are built automatically from this repository by GitHub Actions (`.github/workflows/windows.yml`), never on a personal computer. Free code signing for them is being set up with [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- **Committers and reviewers:** [TechyTJ](https://github.com/techytj)
- **Approvers** (each signed release is approved by hand): [TechyTJ](https://github.com/techytj)

**Privacy policy:** WhoSees will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it. Everything it shows is worked out on your own device. The only links that leave the app (the website, source code and "buy me a coffee") open in your browser when you click them.

## Licences

WhoSees is free software under the GPL-3.0-or-later. In the app, Settings > About > Open-source licences lists every included component.

Data: IP location by [DB-IP.com](https://db-ip.com) (CC BY 4.0); tracker data from AdGuard companiesdb / WhoTracks.me (CC BY-SA 4.0); threat data from Hagezi Threat Intelligence Feeds (GPL-3.0) and abuse.ch Feodo Tracker and SSL Blacklist (CC0); map data © OpenStreetMap contributors (ODbL) via Protomaps. Fonts: Archivo, IBM Plex Mono and Noto Sans (SIL Open Font License).
