#!/usr/bin/env python3
"""Build the website's extra pages (platform pages, guides, privacy policy) and the sitemap.
The home page (website/index.html) is written by hand; everything here shares its look via /css/site.css.
Run after editing:  python3 tools/site_pages.py"""
import datetime, html, json, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'website')
SITE = 'https://whosees.app'
REL = 'https://github.com/techytj/whosees/releases/latest/download/'
CSS_V = 4
TODAY = datetime.date.today().isoformat()
UMAMI = '<script defer src="/s.js" data-website-id="e38b949b-cf74-4a5b-95e3-679e45386377"></script>'

NAV = ('<a href="/#how">How it works</a><a href="/android/">Android</a><a href="/windows/">Windows</a><a href="/linux/">Linux</a>'
       '<a href="/guides/">Guides</a><a class="btn sm" href="/#get" data-umami-event="download-button" data-umami-event-where="top bar">Download</a>')

FOOTER = '''<footer><div class="wrap">
  <div><a class="logo" href="/"><img src="/img/icon.png" alt="">WhoSees</a><p style="margin-top:14px;max-width:34ch">See which apps share your data, with which companies, and where. Free, open source, and private by design.</p></div>
  <div class="mono"><h4>GET WHOSEES</h4><div class="flinks" style="flex-direction:column"><a href="/android/">Android</a><a href="/windows/">Windows</a><a href="/linux/">Linux</a><a href="https://github.com/techytj/whosees/releases">All releases</a></div></div>
  <div class="mono"><h4>LEARN</h4><div class="flinks" style="flex-direction:column"><a href="/guides/which-apps-are-tracking-me/">Which apps are tracking me?</a><a href="/guides/private-dns-android/">Private DNS on Android</a><a href="/privacy/">Privacy policy</a><a href="https://github.com/techytj/whosees#code-signing-policy">Code signing policy</a><a href="https://github.com/techytj/whosees">Source code</a></div></div>
</div><div class="wrap"><div class="huge" aria-hidden="true">WHOSEES</div></div></footer>'''


def btn(platform, label):
    f = {'android': 'WhoSees-Android.apk', 'windows': 'WhoSees-Windows-Setup.exe', 'linux': 'WhoSees-Linux.AppImage', 'fedora': 'whosees-fedora.x86_64.rpm'}[platform]
    return f'<a class="btn" href="{REL}{f}" data-umami-event="download" data-umami-event-platform="{platform}">{label} <span class="k">↓</span></a>'


def side(extra=''):
    return f'''<aside class="side"><h4>GET WHOSEES</h4>
  <a href="/android/">Android 10 and newer</a><a href="/windows/">Windows 10 and 11</a><a href="/linux/">Linux (any distribution)</a>
  <h4 style="margin-top:20px">GUIDES</h4>
  <a href="/guides/which-apps-are-tracking-me/">How to see which apps are tracking you</a><a href="/guides/private-dns-android/">What is Private DNS on Android?</a><a href="/privacy/">Privacy policy</a>
  {extra}</aside>'''


def page(path, title, desc, crumb, h1, lead, body, ld=(), ctas='', side_html=None, kicker=''):
    url = f'{SITE}/{path}'
    crumbs = [('Home', SITE + '/')] + crumb + [(h1 if len(h1) < 60 else title.split(':')[0], url)]
    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(crumbs)]}, *ld]
    crumb_html = ' / '.join(f'<a href="{u.replace(SITE, "") or "/"}">{html.escape(n)}</a>' for n, u in crumbs[:-1])
    doc = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta property="og:type" content="article">
<meta property="og:site_name" content="WhoSees">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:image" content="{SITE}/img/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0a0b0d">
<link rel="icon" href="/img/favicon.png">
<link rel="apple-touch-icon" href="/img/icon.png">
<link rel="preload" href="/fonts/archivo.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/css/site.css?v={CSS_V}">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False, separators=(',', ':'))}</script>
{UMAMI}
</head>
<body>
<header class="bar"><div class="wrap">
  <a class="logo" href="/"><img src="/img/icon.png" alt="">WhoSees</a>
  <nav>{NAV}</nav>
</div></header>
<main class="page"><div class="wrap">
  <div class="crumbs mono">{crumb_html}</div>
  <div class="phead">
    {f'<div class="idx mono"><b>{kicker}</b></div>' if kicker else ''}
    <h1>{h1}</h1>
    <p class="lead">{lead}</p>
    {f'<div class="ctas">{ctas}</div>' if ctas else ''}
  </div>
  <div class="doc"><article>
{body}
  </article>
  {side_html if side_html is not None else side()}
  </div>
</div></main>
{FOOTER}
</body>
</html>
'''
    out = os.path.join(ROOT, path, 'index.html')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write(doc)
    return path


def app_ld(os_name, file):
    return {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": f"WhoSees for {os_name}",
            "applicationCategory": "SecurityApplication", "operatingSystem": os_name, "softwareVersion": "0.1.0",
            "downloadUrl": REL + file, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "license": "https://www.gnu.org/licenses/gpl-3.0.html", "url": SITE + '/',
            "author": {"@type": "Person", "name": "TechyTJ", "url": "https://github.com/techytj"}}


def faq_ld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


def faq_html(pairs):
    return '<h2>Questions</h2>\n' + '\n'.join(f'<h3>{html.escape(q)}</h3><p>{html.escape(a)}</p>' for q, a in pairs)


SHOWS = '''<ul>
<li><b>Which app</b> is sending data, by its real name.</li>
<li><b>Which company</b> receives it: Google, Meta, Amazon, or an advertising or analytics firm you've never heard of. Trackers and advertisers are labelled.</li>
<li><b>Where in the world</b> it goes, drawn live on a map from wherever you are.</li>
<li><b>What kind of data</b> it probably is, like your location or advertising ID, plus a privacy report for each app.</li>
<li><b>Warnings</b> when an app connects to a known scam website or malware server.</li>
</ul>'''

pages = []

# ---------------------------------------------------------------- Android
android_faq = [
    ("Does WhoSees need root?", "No. WhoSees uses Android's built-in VPN feature, which any app can use with your permission. No root or special setup is needed."),
    ("Is WhoSees a VPN service?", "No. Android calls it a VPN because that's the only way an app can see where other apps send data. Everything stays on your phone: nothing is sent to a VPN server or to us, and your data goes exactly where it was going anyway."),
    ("Will it drain my battery?", "Only while it's running. WhoSees runs only while you have a live view on, and stops completely when you press Stop."),
    ("Is WhoSees on Google Play?", "Not yet. For now, install it from this page. A Google Play version is planned."),
]
pages.append(page('android/', 'WhoSees for Android: see which apps are tracking you',
    'Free, open-source app for Android 10 and newer that shows which apps send data, to which companies and where, live on a map. No root, no account, nothing leaves your phone.',
    [], 'See which apps on your Android phone are tracking you',
    'WhoSees shows, live on a map, which app on your phone is sending data, which company receives it, and where in the world it goes. Free, open source, no root and no account.',
    f'''<h2>What you'll see</h2>
{SHOWS}
<h2>How to install WhoSees on Android</h2>
<ol>
<li>On your phone, tap <b>Download for Android</b> above to get <code>WhoSees-Android.apk</code> (about 80 MB).</li>
<li>Open the downloaded file. If Android says your browser isn't allowed to install apps, tap <b>Settings</b>, turn on <b>Allow from this source</b>, then go back.</li>
<li>Tap <b>Install</b>. Because WhoSees isn't on Google Play yet, Google Play Protect may ask you to scan the app or confirm. Choose to install it.</li>
<li>Open WhoSees, set your city if asked, and tap <b>Start live view</b>.</li>
</ol>
<h2>Why Android asks to "set up a VPN connection"</h2>
<p>The first time you press Start, Android asks whether WhoSees may set up a VPN connection. Tap <b>OK</b>. A VPN is the only way Android lets an app see where other apps send data.</p>
<div class="box"><b class="mono">IT STAYS ON YOUR PHONE</b><p>WhoSees isn't a VPN service. Your traffic isn't sent to any server: WhoSees notes where each connection goes and passes it straight on, so your apps work exactly as before. You'll see a key icon while it runs, and it stops the moment you press Stop.</p></div>
<h2>Private DNS and website names</h2>
<p>If your phone uses <b>Private DNS</b> with a named provider, the names of the websites your apps visit are encrypted, so WhoSees can't show them. You'll still see which app, which company and which country. WhoSees tells you when this is the case. <a href="/guides/private-dns-android/">Read about Private DNS</a>.</p>
<h2>Requirements</h2>
<table><tr><th>NEEDS</th><th></th></tr>
<tr><td>Android</td><td>Android 10 or newer</td></tr>
<tr><td>Phone</td><td>64-bit (almost every phone from the last several years)</td></tr>
<tr><td>Space</td><td>About 80 MB to download</td></tr></table>
<h2>Updating and uninstalling</h2>
<p>To update, download the newest version from this page and install it over the old one. Your settings are kept. To remove WhoSees: <b>Settings → Apps → WhoSees → Uninstall</b>.</p>
{faq_html(android_faq)}''',
    [app_ld('Android 10+', 'WhoSees-Android.apk'), faq_ld(android_faq)], btn('android', 'Download for Android'), kicker='ANDROID'))

# ---------------------------------------------------------------- Windows
win_faq = [
    ("Why does Windows say 'Windows protected your PC'?", "Windows shows this for new programs that aren't code-signed yet. It doesn't mean anything is wrong with WhoSees. Click More info, then Run anyway. WhoSees has applied for free code signing from the SignPath Foundation."),
    ("Is WhoSees a firewall?", "Not in this version. WhoSees shows which apps connect where; blocking is built but switched off for now."),
    ("Does WhoSees read my traffic?", "It reads where your data goes, never what's inside it. Almost all traffic is encrypted, and WhoSees doesn't open it."),
]
pages.append(page('windows/', 'WhoSees for Windows: see which apps send your data and where',
    'Free, open-source network monitor for Windows 10 and 11 that shows which app sends data to which company and where, live on a map. No account, nothing leaves your PC.',
    [], 'See which apps on your Windows PC send your data, and where',
    'WhoSees is a free, open-source network monitor made for everyone: it shows which app is sending data, which company receives it and where in the world it goes, live on a map, in plain English.',
    f'''<h2>What you'll see</h2>
{SHOWS}
<h2>How to install WhoSees on Windows</h2>
<ol>
<li>Click <b>Download for Windows</b> to get <code>WhoSees-Windows-Setup.exe</code> (about 190 MB).</li>
<li>Run the installer. Windows shows a blue <b>"Windows protected your PC"</b> screen: click <b>More info</b>, then <b>Run anyway</b>.</li>
<li>Choose where to install it and click <b>Install</b>.</li>
<li>Open WhoSees from the Start menu and click <b>Start live view</b>.</li>
</ol>
<div class="box"><b class="mono">WHY WINDOWS WARNS YOU</b><p>Windows shows that warning for any new program that isn't <i>code-signed</i> yet, meaning it doesn't carry a digital signature proving who published it. It doesn't mean anything is wrong with WhoSees. WhoSees has applied for free code signing from the <a href="https://signpath.org">SignPath Foundation</a>; once approved, the installer will be signed and the warning fades as more people install it.</p></div>
<h2>Standard and Deep mode</h2>
<table><tr><th>MODE</th><th>WHAT IT DOES</th></tr>
<tr><td>Standard</td><td>No administrator rights needed. Shows apps, companies and places from Windows' own connection list.</td></tr>
<tr><td>Deep</td><td>Asks Windows for permission (a Yes/No prompt) each time you press Start. Adds website names and catches every connection, even ones that last a split second. Still only reads where data goes, never what's inside it.</td></tr></table>
<h2>Check your download</h2>
<p>The Windows installer is built automatically by GitHub from the <a href="https://github.com/techytj/whosees">public source code</a>, never on a personal computer. To confirm your copy wasn't changed, open PowerShell in your Downloads folder and run <code>Get-FileHash WhoSees-Windows-Setup.exe</code>, then compare the result with <a href="{REL}SHA256SUMS.txt">SHA256SUMS.txt</a>.</p>
<h2>Requirements</h2>
<table><tr><th>NEEDS</th><th></th></tr><tr><td>Windows</td><td>Windows 10 or 11, 64-bit</td></tr><tr><td>Space</td><td>About 190 MB to download</td></tr></table>
<h2>Uninstalling</h2>
<p><b>Settings → Apps → Installed apps → WhoSees → Uninstall</b>. Nothing keeps running after you close WhoSees.</p>
{faq_html(win_faq)}''',
    [app_ld('Windows 10, Windows 11', 'WhoSees-Windows-Setup.exe'), faq_ld(win_faq)], btn('windows', 'Download for Windows'), kicker='WINDOWS'))

# ---------------------------------------------------------------- Linux
lin_faq = [
    ("Which Linux distributions does WhoSees run on?", "The AppImage runs on most 64-bit desktop distributions. Fedora users can also install the .rpm package."),
    ("Why does Deep mode ask for my password?", "Reading website names from network traffic needs administrator rights on Linux. Your system's own password window asks for it; WhoSees never sees or stores your password."),
]
pages.append(page('linux/', 'WhoSees for Linux: see which programs send your data and where',
    'Free, open-source network monitor for Linux that shows which program sends data to which company and where, live on a map. AppImage for any distribution, plus a Fedora package.',
    [], 'See which programs on your Linux computer send your data, and where',
    'WhoSees shows, live on a map, which program is sending data, which company receives it and where in the world it goes. Free and open source, as an AppImage for any distribution or a Fedora package.',
    f'''<h2>What you'll see</h2>
{SHOWS}
<h2>How to install WhoSees on Linux</h2>
<h3>AppImage (any distribution)</h3>
<ol>
<li>Download <code>WhoSees-Linux.AppImage</code> (about 210 MB).</li>
<li>Make it executable: right-click it, open <b>Properties</b> and turn on <b>Allow executing file as program</b>, or run <code>chmod +x WhoSees-Linux.AppImage</code>.</li>
<li>Double-click it to start WhoSees. If it doesn't start, install your distribution's <code>libfuse2</code> (or <code>fuse</code>) package.</li>
</ol>
<h3>Fedora</h3>
<p>Download <a href="{REL}whosees-fedora.x86_64.rpm" data-umami-event="download" data-umami-event-platform="fedora">whosees-fedora.x86_64.rpm</a> and install it with <code>sudo dnf install ./whosees-fedora.x86_64.rpm</code>. WhoSees then appears in your app menu.</p>
<h2>Standard and Deep mode</h2>
<table><tr><th>MODE</th><th>WHAT IT DOES</th></tr>
<tr><td>Standard</td><td>No password needed. Shows programs, companies and places from the kernel's connection table.</td></tr>
<tr><td>Deep</td><td>Asks for your login password through your system's password window each time you press Start. Adds website names and catches every connection. Reads packet headers only, never contents.</td></tr></table>
<h2>Uninstalling</h2>
<p>AppImage: delete the file. Fedora: <code>sudo dnf remove whosees</code>.</p>
{faq_html(lin_faq)}''',
    [app_ld('Linux', 'WhoSees-Linux.AppImage'), faq_ld(lin_faq)], btn('linux', 'Download for Linux'), kicker='LINUX'))

# ---------------------------------------------------------------- Guide: which apps are tracking me
g1 = page('guides/which-apps-are-tracking-me/', 'How to see which apps are tracking you (Android, iPhone, Windows)',
    'Simple ways to find out which apps share your data with advertisers and trackers on Android, iPhone and Windows, and what you can do about it.',
    [('Guides', SITE + '/guides/')], 'How to see which apps are tracking you',
    "Most apps include code from advertising and analytics companies. Here's how to find out which of your apps share data, who receives it, and what you can do about it, in plain English.",
    '''<h2>What "tracking" means</h2>
<p>Many free apps make money by sharing information with other companies: advertising networks, analytics firms and data brokers. Often this happens through small pieces of code ("trackers") built into the app. They can report things like your rough location, your phone's advertising ID, which screens you open and how long you use the app.</p>
<h2>1. Read what each app says it collects</h2>
<p>On Android, open the app's page in Google Play and scroll to <b>Data safety</b>. On iPhone, open the app's page in the App Store and look for <b>App Privacy</b>. These are a good starting point, but they're written by the app makers themselves.</p>
<h2>2. Check which permissions apps use</h2>
<ul>
<li><b>Android:</b> open Settings and search for <b>Privacy dashboard</b> to see which apps recently used your location, camera or microphone. Under <b>Permission manager</b> you can switch off anything an app doesn't need.</li>
<li><b>iPhone:</b> go to <b>Settings → Privacy &amp; Security</b> and check Location Services, Camera, Microphone and the others.</li>
</ul>
<h2>3. Watch what apps actually send</h2>
<p>Permissions only tell you what an app <i>could</i> do. To see who your apps really talk to:</p>
<ul>
<li><b>iPhone:</b> turn on <b>Settings → Privacy &amp; Security → App Privacy Report</b>. After a few days it lists the websites each app contacted.</li>
<li><b>Android, Windows and Linux:</b> use <a href="/">WhoSees</a>. It shows, live on a map, which app sends data, which company receives it (trackers and advertisers are labelled) and where in the world it goes. It's free and open source, and nothing leaves your device.</li>
</ul>
<div class="box"><b class="mono">WHAT YOU CAN AND CAN'T SEE</b><p>Almost all app traffic is encrypted, so no tool can honestly show you every detail inside it. What you <i>can</i> see is who receives it. WhoSees marks data it actually saw (sent without encryption) as "seen", and otherwise tells you what that kind of company usually collects, marked "likely".</p></div>
<h2>4. What you can do about it</h2>
<ul>
<li><b>Reset or delete your advertising ID.</b> Android: open Settings and search for <b>Ads</b>, then choose <b>Delete advertising ID</b>. iPhone: <b>Settings → Privacy &amp; Security → Tracking</b>, and turn off "Allow Apps to Request to Track".</li>
<li><b>Remove permissions</b> an app doesn't need, especially location.</li>
<li><b>Uninstall apps you don't use.</b> Many keep sending data in the background.</li>
<li><b>Use a privacy-friendly DNS</b> that blocks known trackers for the whole phone. See <a href="/guides/private-dns-android/">Private DNS on Android</a>.</li>
</ul>''',
    [{"@context": "https://schema.org", "@type": "Article", "headline": "How to see which apps are tracking you", "datePublished": "2026-11-15", "dateModified": TODAY,
      "author": {"@type": "Person", "name": "TechyTJ"}, "publisher": {"@type": "Organization", "name": "WhoSees", "logo": {"@type": "ImageObject", "url": SITE + "/img/icon.png"}},
      "image": SITE + "/img/og.png", "mainEntityOfPage": SITE + "/guides/which-apps-are-tracking-me/"}],
    '<a class="btn" href="/#get">Try WhoSees, free <span class="k">→</span></a>', kicker='GUIDE')

# ---------------------------------------------------------------- Guide: Private DNS
g2 = page('guides/private-dns-android/', 'What is Private DNS on Android, and when should you turn it off?',
    "Private DNS on Android encrypts your phone's website lookups. What it does, the three settings, how to change it on Samsung, Pixel and other phones, and how it affects WhoSees.",
    [('Guides', SITE + '/guides/')], 'What is Private DNS on Android?',
    "Private DNS keeps the names of the websites your phone looks up private from your Wi-Fi or mobile network. Here's what it does, how to change it, and when you might want to turn it off for a while.",
    '''<h2>What DNS is</h2>
<p>Before an app can connect to a website, your phone has to look up its address, a bit like checking a phone book. That lookup is called <b>DNS</b>. Normally it isn't encrypted, so your Wi-Fi or mobile network can see every website name your phone looks up.</p>
<h2>What Private DNS does</h2>
<p><b>Private DNS</b> (available since Android 9) encrypts those lookups and sends them to a DNS provider you trust. Some providers, like AdGuard DNS, can also block known ad and tracking websites for every app on your phone.</p>
<h2>The three settings</h2>
<table><tr><th>SETTING</th><th>WHAT IT MEANS</th></tr>
<tr><td>Off</td><td>Lookups aren't encrypted and go to your network's DNS.</td></tr>
<tr><td>Automatic</td><td>The default on most phones. Encrypts lookups when your network's DNS supports it; otherwise works as normal.</td></tr>
<tr><td>Private DNS provider hostname</td><td>Always uses the provider you name, for example <code>dns.google</code>, <code>one.one.one.one</code> or <code>dns.adguard-dns.com</code>.</td></tr></table>
<h2>How to change it</h2>
<ul>
<li><b>Samsung:</b> Settings → Connections → More connection settings → Private DNS.</li>
<li><b>Google Pixel and most other phones:</b> Settings → Network &amp; internet → Private DNS.</li>
<li><b>Any phone:</b> open Settings and search for <b>Private DNS</b>.</li>
</ul>
<h2>Private DNS and WhoSees</h2>
<p>When Private DNS is set to a named provider, website lookups are encrypted all the way to that provider, so <a href="/android/">WhoSees</a> can't read the website names. It still shows which app sent data, which company received it and where, because those come from the address each app connects to.</p>
<div class="box"><b class="mono">FOR THE FULL PICTURE</b><p>Switch Private DNS to <b>Off</b> while you look, then switch it back on afterwards. WhoSees tells you when Private DNS is on, and reminds you to turn it back on when you press Stop.</p></div>
<h2>Should you keep it on?</h2>
<p>For everyday privacy, yes: encrypted lookups are better, and a blocking provider cuts down on trackers. Turning it off is only useful for the few minutes you want to see exactly which websites your apps visit.</p>''',
    [{"@context": "https://schema.org", "@type": "Article", "headline": "What is Private DNS on Android?", "datePublished": "2026-11-15", "dateModified": TODAY,
      "author": {"@type": "Person", "name": "TechyTJ"}, "publisher": {"@type": "Organization", "name": "WhoSees", "logo": {"@type": "ImageObject", "url": SITE + "/img/icon.png"}},
      "image": SITE + "/img/og.png", "mainEntityOfPage": SITE + "/guides/private-dns-android/"}],
    kicker='GUIDE')
pages += [g1, g2]

# ---------------------------------------------------------------- Guides index
pages.append(page('guides/', 'Guides: app tracking and phone privacy, in plain English',
    'Short, plain-English guides about which apps are tracking you, Private DNS, and how to keep your data private on Android, iPhone and Windows.',
    [], 'Guides', 'Short, plain-English guides about apps, tracking and keeping your data private.',
    '''<div class="cards" style="grid-template-columns:1fr 1fr">
<a href="/guides/which-apps-are-tracking-me/"><b>How to see which apps are tracking you</b><span>Find out which apps share your data with advertisers and trackers on Android, iPhone and Windows, and what to do about it.</span><em>READ THE GUIDE →</em></a>
<a href="/guides/private-dns-android/"><b>What is Private DNS on Android?</b><span>What it does, the three settings, how to change it on Samsung and Pixel, and when to turn it off.</span><em>READ THE GUIDE →</em></a>
</div>''', kicker='GUIDES'))

# ---------------------------------------------------------------- Privacy policy
pages.append(page('privacy/', 'Privacy policy: WhoSees',
    'WhoSees processes everything on your own device and sends no data anywhere. How the app and the whosees.app website handle information.',
    [], 'Privacy policy', 'The short version: the WhoSees app sends nothing anywhere, and this website counts visits privately, without cookies.',
    f'''<p class="mono" style="font-size:13px">Last updated {TODAY}</p>
<h2>The WhoSees app</h2>
<p><b>WhoSees does not collect, send or sell any of your information.</b> Everything it shows is worked out on your own device, and nothing is sent to us or to anyone else.</p>
<ul>
<li><b>What it looks at:</b> while a live view is running, the details of your device's network connections: which app made them, the address and port they go to, the website name when it's visible, and how much data was sent. For data sent without encryption, it checks the parts needed to say what kind of data it was (for example a location). It does not read the contents of encrypted traffic.</li>
<li><b>Where that goes:</b> nowhere. It's shown on your screen and discarded when you press Stop or close WhoSees.</li>
<li><b>What it saves:</b> only your settings (such as your home city and display preferences), stored on your device.</li>
<li><b>Lists it uses:</b> the IP-location, tracker and threat lists are built into the app and used offline. WhoSees doesn't look anything up online.</li>
<li><b>Links:</b> the website, source code and "buy me a coffee" links open in your browser only when you click them.</li>
</ul>
<h3>Android permissions</h3>
<table><tr><th>PERMISSION</th><th>WHY</th></tr>
<tr><td>VPN</td><td>The only way Android lets an app see where other apps send data. Traffic stays on your phone and goes on to where it was going; nothing goes to a VPN server.</td></tr>
<tr><td>See installed apps</td><td>To show each app's real name and icon instead of a number.</td></tr>
<tr><td>Notifications</td><td>To warn you if an app connects to a dangerous website while WhoSees is running.</td></tr>
<tr><td>Internet</td><td>To pass your apps' traffic on to where it was going.</td></tr>
<tr><td>Network state</td><td>To know whether you're on Wi-Fi or mobile data, so apps behave the same as without WhoSees.</td></tr></table>
<h3>Windows and Linux</h3>
<p>Deep mode asks your system for administrator permission so WhoSees can read where network traffic goes. Your password goes to your system's own security prompt; WhoSees never sees or stores it.</p>
<h2>The whosees.app website</h2>
<ul>
<li><b>Visit counting:</b> we use <a href="https://umami.is">Umami</a>, an open-source analytics tool running on our own server. It doesn't use cookies and doesn't store your IP address. It records the page you viewed, the site that linked you here, your browser, operating system, device type and approximate country, plus clicks on the download and "buy me a coffee" buttons. We use this only to see how many people visit and download WhoSees.</li>
<li><b>Delivery:</b> the site is delivered through <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare</a>, which, like any network, sees your IP address to send you the page.</li>
<li><b>Downloads</b> come from <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub</a>, and tips go through <a href="https://www.paypal.com/myaccount/privacy/privacyhub">PayPal</a>. Their own privacy policies apply there.</li>
</ul>
<h2>Children</h2>
<p>WhoSees doesn't collect information from anyone, including children.</p>
<h2>Changes</h2>
<p>If this policy changes, the new version will be posted on this page with a new date. Because WhoSees is open source, you can always check what the app does in its <a href="https://github.com/techytj/whosees">source code</a>.</p>''',
    [], side_html=side(), kicker='PRIVACY'))

# ---------------------------------------------------------------- sitemap
urls = [('', '1.0', 'weekly')] + [(p, '0.8' if p in ('android/', 'windows/', 'linux/') else '0.6', 'monthly') for p in pages]
open(os.path.join(ROOT, 'sitemap.xml'), 'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    ''.join(f'  <url><loc>{SITE}/{p}</loc><lastmod>{TODAY}</lastmod><changefreq>{f}</changefreq><priority>{pr}</priority></url>\n' for p, pr, f in urls) + '</urlset>\n')
print(f'{len(pages)} pages + sitemap ({len(urls)} URLs)')
