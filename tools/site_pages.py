#!/usr/bin/env python3
"""Build the website's extra pages (platform pages, guides, privacy policy) and the sitemap.
The home page (website/index.html) is written by hand; everything here shares its look via /css/site.css.
Run after editing:  python3 tools/site_pages.py"""
import datetime, html, json, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'website')
SITE = 'https://whosees.app'
REL = 'https://github.com/techytj/whosees/releases/latest/download/'
CSS_V = 10
TODAY = datetime.date.today().isoformat()
UMAMI = '<script defer src="/s.js" data-website-id="e38b949b-cf74-4a5b-95e3-679e45386377"></script>'

NAV = ('<a href="/#how">How it works</a><a href="/android/">Android</a><a href="/windows/">Windows</a><a href="/linux/">Linux</a>'
       '<a href="/guides/">Guides</a><a class="coffee-link" href="/#support" data-umami-event="coffee-menu"><svg class="cup" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V9Z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3v3M12 3v3"/></svg>Buy me a coffee</a>')

FOOTER = '''<footer><div class="wrap">
  <div><a class="logo" href="/"><img src="/img/icon.png" alt="">WhoSees</a><p style="margin-top:14px;max-width:34ch">See which apps share your data, with which companies, and where. Free, open source, and private by design.</p></div>
  <div class="mono"><h4>GET WHOSEES</h4><div class="flinks" style="flex-direction:column"><a href="/android/">Android</a><a href="/windows/">Windows</a><a href="/linux/">Linux</a><a href="https://github.com/techytj/whosees/releases">All releases</a></div></div>
  <div class="mono"><h4>LEARN</h4><div class="flinks" style="flex-direction:column"><a href="/guide/">User guide</a><a href="/guides/which-apps-are-tracking-me/">Which apps are tracking me?</a><a href="/guides/private-dns-android/">Private DNS on Android</a><a href="/privacy/">Privacy policy</a><a href="https://github.com/techytj/whosees#code-signing-policy">Code signing policy</a><a href="https://github.com/techytj/whosees">Source code</a></div></div>
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


def page(path, title, desc, crumb, h1, lead, body, ld=(), ctas='', side_html=None, kicker='', doc_class=''):
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
  <nav id="menu">{NAV}</nav>
  <a class="btn sm" href="/#get" data-umami-event="download-button" data-umami-event-where="top bar">Download</a>
  <button class="menu-btn" type="button" aria-label="Menu" aria-expanded="false" aria-controls="menu"><span></span><span></span><span></span></button>
</div></header>
<main class="page"><div class="wrap">
  <div class="crumbs mono">{crumb_html}</div>
  <div class="phead">
    {f'<div class="idx mono"><b>{kicker}</b></div>' if kicker else ''}
    <h1>{h1}</h1>
    <p class="lead">{lead}</p>
    {f'<div class="ctas">{ctas}</div>' if ctas else ''}
  </div>
  <div class="doc{(" " + doc_class) if doc_class else ""}"><article>
{body}
  </article>
  {side_html if side_html is not None else side()}
  </div>
</div></main>
{FOOTER}
<script>
// phone menu: the links fold into a ☰ button on narrow screens
(() => {{ const bar = document.querySelector('.bar'), b = bar.querySelector('.menu-btn');
  const set = (o) => {{ bar.classList.toggle('open', o); b.setAttribute('aria-expanded', o); }};
  b.addEventListener('click', () => set(!bar.classList.contains('open')));
  bar.querySelectorAll('nav a').forEach((a) => a.addEventListener('click', () => set(false)));
  addEventListener('keydown', (e) => {{ if (e.key === 'Escape') set(false); }}); }})();
</script>
</body>
</html>
'''
    out = os.path.join(ROOT, path, 'index.html')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write(doc)
    return path


def app_ld(os_name, file):
    return {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": f"WhoSees for {os_name}",
            "applicationCategory": "SecurityApplication", "operatingSystem": os_name, "softwareVersion": "0.1.1",
            "downloadUrl": REL + file, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "license": "https://www.gnu.org/licenses/gpl-3.0.html", "url": SITE + '/',
            "author": {"@type": "Person", "name": "TechyTJ", "url": "https://github.com/techytj"}}


def faq_ld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


def faq_html(pairs):
    return '<h2>Questions</h2>\n' + '\n'.join(f'<h3>{html.escape(q)}</h3><p>{html.escape(a)}</p>' for q, a in pairs)


# figures with numbered markers (screenshots from tools/guide_shots.py and tools/android_install_shots.py)
MARKS = json.load(open(os.path.join(ROOT, 'img', 'guide', 'marks.json')))

def fig(name, caption, keys, phone=False, src=None):
    m = MARKS.get(('i-' + name) if src else name, {})
    dots = ''.join(f'<span class="mk" style="left:{m[k][0]}%;top:{m[k][1]}%">{k}</span>' for k in keys if k in m)
    w, h = (540, 1200) if phone else (1440, 900)
    key_html = ''.join(f'<li><span class="mk-n">{k}</span><span>{t}</span></li>' for k, t in sorted(keys.items()) if k in m)
    return (f'<figure class="gfig{" phone" if phone else ""}"><div class="shot"><img src="{src or f'/img/guide/{name}.webp'}" alt="{html.escape(caption)}" width="{w}" height="{h}" loading="lazy">{dots}</div>'
            f'<figcaption>{caption}</figcaption>{f"<ol class=keys>{key_html}</ol>" if key_html else ""}</figure>')

def phones(*figs): return '<div class="phones">' + ''.join(figs) + '</div>'

def ishot(name, caption, keys):  # Android install pictures
    return fig(name, caption, keys, True, src=f'/img/guide/install/{name}.webp')


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
    ("Do I need Developer options to install WhoSees?", "Usually not. Most phones only need you to allow your browser to install apps. Developer options are only needed where Android requires apps from verified developers (Brazil, Indonesia, Singapore and Thailand since September 2026, and everywhere from 2027), or if you install from a computer."),
    ("Is it safe to allow installing unknown apps?", "Allowing one app, like your browser, to install apps is safe as long as you only install apps you trust. You can turn the permission off again right after installing WhoSees."),
]
pages.append(page('android/', 'WhoSees for Android: see which apps are tracking you',
    'Free, open-source app for Android 10 and newer that shows which apps send data, to which companies and where, live on a map. No root, no account, nothing leaves your phone.',
    [], 'See which apps on your Android phone are tracking you',
    'WhoSees shows, live on a map, which app on your phone is sending data, which company receives it, and where in the world it goes. Free, open source, no root and no account.',
    f'''<h2>What you'll see</h2>
{SHOWS}
<h2 id="install">How to install WhoSees on Android, step by step</h2>
<p>WhoSees isn't on Google Play yet, so you install it from this page. It takes about two minutes. The pictures are from a phone running Android 16 with Chrome; other phones look a little different but the steps are the same.</p>
<div class="box"><b class="mono">BEFORE YOU START</b><p>You need Android 10 or newer and about 200 MB free. You do <b>not</b> need to root your phone, and on most phones you do <b>not</b> need Developer options (see <a href="#developer">when you might</a>).</p></div>

<h3>1. Download the app</h3>
<p>On your phone, open this page in Chrome (or your usual browser) and tap <b>Download for Android</b>. The file is called <code>WhoSees-Android.apk</code> and is about 80 MB.</p>
{phones(ishot('a-page', 'This page in Chrome', {'1': 'Tap <b>Download for Android</b>.'}))}

<h3>2. Open the downloaded file</h3>
<p>When the download finishes, open it in one of these ways:</p>
<ul><li>Swipe down from the top of the screen and tap the <b>Download complete</b> notification for <code>WhoSees-Android.apk</code>.</li>
<li>Or in Chrome tap <b>⋮ → Downloads</b> and tap the file.</li>
<li>Or open the <b>Files</b> app (Samsung: <b>My Files</b>), go to <b>Downloads</b> and tap the file.</li></ul>
<p>If your browser asks whether to keep a file of this type, choose <b>Download anyway</b>.</p>
{phones(ishot('c-notification', 'The download notification', {'1': 'Tap the finished download.'}))}

<h3>3. Allow your browser to install apps (first time only)</h3>
<p>Android protects you from apps installed outside the Play Store, so the first time it asks for permission:</p>
<ol><li>Android says <i>"For your security, your phone currently isn't allowed to install unknown apps from this source."</i> Tap <b>Settings</b>.</li>
<li>Turn on <b>Allow from this source</b>. This only lets your browser install apps you choose to open; you can turn it off again afterwards.</li>
<li>The install question comes back on its own (on some phones, press <b>Back</b>).</li></ol>
{phones(ishot('d-blocked', 'Android asks first', {'1': 'Tap <b>Settings</b>.'}), ishot('e-allow', 'Install unknown apps', {'1': 'Turn on <b>Allow from this source</b>.'}))}

<h3>4. Install</h3>
<ol><li>Android asks <i>"Do you want to install this app?"</i> Tap <b>Install</b>.</li>
<li>When it says <b>App installed</b>, tap <b>Open</b>.</li></ol>
{phones(ishot('g-install', 'The install question', {'1': 'Tap <b>Install</b>.'}), ishot('i-done', 'Installed', {'1': 'Tap <b>Open</b>.'}))}

<h3>5. Start WhoSees</h3>
<p>Choose whether WhoSees may check for updates (it's off unless you turn it on), set your city if asked, and tap <b>Start live view</b>. Android then asks to allow a VPN: tap <b>OK</b>. The <a href="/guide/#live">user guide</a> shows what happens next.</p>

<h2 id="blocked">If something blocks the install</h2>
<h3>Google Play Protect</h3>
<p>Google Play Protect checks apps installed from outside the Play Store. For a new app it may show one of these:</p>
<ul><li><b>"App scan recommended"</b>: tap <b>Scan app</b>. WhoSees is open source and contains nothing harmful, so it installs after the scan. You can also choose <b>Install without scanning</b>.</li>
<li><b>"Unsafe app blocked"</b> or <b>"Harmful app blocked"</b>: tap <b>More details</b>, then <b>Install anyway</b>. Play Protect is cautious with apps it hasn't seen before, and apps that use a VPN look unusual to it.</li></ul>
<h3>Samsung phones: Auto Blocker</h3>
<p>Many Samsung Galaxy phones have <b>Auto Blocker</b> turned on, which stops any app from outside Google Play or the Galaxy Store, with no "install anyway" button. To install WhoSees:</p>
<ol><li>Open <b>Settings → Security and privacy → Auto Blocker</b>.</li>
<li>Turn it <b>off</b>, then install WhoSees as above.</li>
<li>Turn Auto Blocker back <b>on</b> afterwards if you like. WhoSees keeps working. (Newer Samsung software may turn it back on by itself after a while.)</li></ol>
<p>Other phone makers have similar switches, for example Xiaomi's <b>Install via USB</b> or security scan prompts. If an install is blocked with no way forward, look in <b>Settings → Security</b>.</p>

<h3 id="developer">"App from an unverified developer" and Developer options</h3>
<p>Google is changing how apps from outside the Play Store are installed. Since <b>September 30, 2026</b> in <b>Brazil, Indonesia, Singapore and Thailand</b>, and in every country from <b>2027</b>, Android only installs apps from developers who have verified their identity with Google, unless you choose to allow others. If Android tells you WhoSees is from an <b>unverified developer</b> and won't install it, you can allow it once through Developer options:</p>
<ol><li><b>Turn on Developer options.</b> Open <b>Settings → About phone</b> (Samsung: <b>Settings → About phone → Software information</b>) and tap <b>Build number</b> seven times. Enter your PIN if asked. Android says <b>"You are now a developer!"</b></li>
<li>Open <b>Settings → System → Developer options</b> (Samsung: Developer options is at the bottom of Settings).</li>
<li>Find <b>Apps from unverified developers</b>, turn it on, and confirm that nobody is asking you to do this.</li>
<li>Restart your phone. Android then makes you wait <b>24 hours</b> (once per phone), a safety measure against scammers who pressure people over the phone.</li>
<li>After the wait, go back to the same setting, confirm with your fingerprint, face or PIN, and choose <b>Allow temporarily</b> (7 days) or <b>Allow indefinitely</b>.</li>
<li>Install WhoSees as above. When Android warns about the unverified developer, tap <b>Install anyway</b>.</li>
<li>You can turn Developer options off again afterwards: <b>Developer options → Use developer options → off</b>.</li></ol>
{phones(ishot('j-build', 'About phone, Build number at the bottom', {'1': 'Tap <b>Build number</b> seven times.'}), ishot('k-developer', '"You are now a developer!"', {'1': 'The message appears here.'}), ishot('l-devoptions', 'Developer options is now in Settings', {}))}
<div class="box"><b class="mono">ANOTHER WAY: FROM A COMPUTER</b><p>If you're comfortable with a computer, you can install with Android's own tools instead, which skips the waiting period: turn on <b>Developer options → USB debugging</b>, connect the phone, and run <code>adb install WhoSees-Android.apk</code>. Turn USB debugging off again when you're done.</p></div>
<p>Outside the countries listed above, none of this is needed yet: the normal steps work.</p>
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
<p>To update, download the newest version from this page and install it over the old one, following the same steps; your settings are kept. WhoSees can also tell you when a new version is out if you turn on <b>Settings → Check for updates</b>. To remove WhoSees: <b>Settings → Apps → WhoSees → Uninstall</b>.</p>
<h2 id="trouble">Install problems</h2>
<table><tr><th>WHAT YOU SEE</th><th>WHAT TO DO</th></tr>
<tr><td>"App not installed" or "conflicts with an existing package"</td><td>An older test version of WhoSees is installed. Uninstall it first, then install again.</td></tr>
<tr><td>"There was a problem parsing the package"</td><td>The download didn't finish. Delete the file from Downloads and download it again.</td></tr>
<tr><td>The install is blocked with no button to continue</td><td>On Samsung, turn off <b>Auto Blocker</b> (see <a href="#blocked">above</a>). Otherwise check <b>Settings → Security</b>.</td></tr>
<tr><td>Can't find "Install unknown apps"</td><td>Open <b>Settings → Apps → Special app access → Install unknown apps</b>, pick your browser or Files app, and turn on <b>Allow from this source</b>.</td></tr>
<tr><td>"App from an unverified developer"</td><td>See <a href="#developer">Developer options</a> above.</td></tr>
<tr><td>Nothing happens when tapping the download</td><td>Open the <b>Files</b> app → <b>Downloads</b> and tap <code>WhoSees-Android.apk</code> there.</td></tr></table>
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
    '''<div class="cards two">
<a href="/guide/"><b>The WhoSees user guide</b><span>Step by step, with pictures: starting a live view, reading the map, finding out what an app sends, warnings, settings and troubleshooting.</span><em>OPEN THE USER GUIDE →</em></a>
<a href="/guides/which-apps-are-tracking-me/"><b>How to see which apps are tracking you</b><span>Find out which apps share your data with advertisers and trackers on Android, iPhone and Windows, and what to do about it.</span><em>READ THE GUIDE →</em></a>
<a href="/guides/private-dns-android/"><b>What is Private DNS on Android?</b><span>What it does, the three settings, how to change it on Samsung and Pixel, and when to turn it off.</span><em>READ THE GUIDE →</em></a>
</div>''', kicker='GUIDES'))

# ---------------------------------------------------------------- Privacy policy
pages.append(page('privacy/', 'Privacy policy: WhoSees',
    'WhoSees processes everything on your own device and sends no data anywhere. How the app and the whosees.app website handle information.',
    [], 'Privacy policy', 'The short version: the WhoSees app sends nothing anywhere, and this website counts visits privately, without cookies.',
    f'''<p class="mono" style="font-size:13px">Last updated {TODAY}</p>
<h2>The WhoSees app</h2>
<p><b>WhoSees does not collect, send or sell any of your information.</b> Everything it shows is worked out on your own device, and nothing is sent to us or to anyone else. The only request WhoSees ever makes on its own is the optional update check described below, which is off unless you turn it on.</p>
<ul>
<li><b>What it looks at:</b> while a live view is running, the details of your device's network connections: which app made them, the address and port they go to, the website name when it's visible, and how much data was sent. For data sent without encryption, it checks the parts needed to say what kind of data it was (for example a location). It does not read the contents of encrypted traffic.</li>
<li><b>Where that goes:</b> nowhere. It's shown on your screen and discarded when you press Stop or close WhoSees.</li>
<li><b>What it saves:</b> only your settings (such as your home city and display preferences), stored on your device.</li>
<li><b>Lists it uses:</b> the IP-location, tracker and threat lists are built into the app and used offline. WhoSees doesn't look anything up online.</li>
<li><b>Update checks (off unless you turn them on):</b> the first time you open WhoSees, it asks whether you'd like it to check for updates. If you say yes, once a day when you open it, WhoSees downloads one small public file, <a href="/version.json">whosees.app/version.json</a>, that lists the newest version. Like visiting any website, that request reveals your internet address. Nothing else is sent: no ID, no list of your apps, nothing about what WhoSees shows you. Our server doesn't keep a log of these requests. You can turn this off any time in Settings.</li>
<li><b>Links:</b> the website, source code and "buy me a coffee" links open in your browser only when you click them.</li>
</ul>
<h3>Android permissions</h3>
<table><tr><th>PERMISSION</th><th>WHY</th></tr>
<tr><td>VPN</td><td>The only way Android lets an app see where other apps send data. Traffic stays on your phone and goes on to where it was going; nothing goes to a VPN server.</td></tr>
<tr><td>See installed apps</td><td>To show each app's real name and icon instead of a number.</td></tr>
<tr><td>Notifications</td><td>To warn you if an app connects to a dangerous website while WhoSees is running.</td></tr>
<tr><td>Internet</td><td>To pass your apps' traffic on to where it was going, and, only if you turned it on, to check for updates.</td></tr>
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


# ---------------------------------------------------------------- User guide (screenshots from tools/guide_shots.py)


TOC = [('start', 'Getting started'), ('live', 'Start a live view'), ('map', 'Read the live map'), ('apps', 'See which apps send the most'),
       ('app', 'Find out what an app sends'), ('place', 'Check a place on the map'), ('companies', 'See every company and country'),
       ('feed', 'Watch connections as they happen'), ('search', 'Search'), ('expert', 'Technical details (Expert)'),
       ('alerts', 'When WhoSees warns you'), ('privatedns', 'Missing website names (Android)'), ('settings', 'Settings'),
       ('stop', 'Stop WhoSees'), ('support', 'Support WhoSees'), ('trouble', 'Troubleshooting')]
toc_html = ''.join(f'<a href="#{i}">{html.escape(t)}</a>' for i, t in TOC)
guide_side = f'<aside class="side toc"><h4>IN THIS GUIDE</h4>{toc_html}<a class="btn" href="/#get">Download WhoSees <span class="k">↓</span></a></aside>'

guide_faq = [
    ("I pressed Start but nothing appears.", "WhoSees shows connections as they happen. Open a few apps, a website or a video, and they'll appear within seconds."),
    ("Does WhoSees slow down my internet?", "No. It only notes where each connection goes. Streaming, browsing and downloads run at normal speed."),
    ("Can WhoSees read my messages or passwords?", "No. It sees where your data goes, never what's inside encrypted traffic."),
]
guide_body = f"""
<nav class="toc-m mono"><b>IN THIS GUIDE</b>{toc_html}</nav>

<h2 id="start">Getting started</h2>
<p>First install WhoSees: see the step-by-step install pages for <a href="/android/">Android</a>, <a href="/windows/">Windows</a> and <a href="/linux/">Linux</a>. Then open it. You'll see the start screen:</p>
{fig('d-start', 'The start screen on a computer', {'1': '<b>Start live view</b> begins watching. Nothing runs until you press it.', '2': '<b>Deep mode</b> switch (computers only): adds website names and catches every connection. More below.', '3': '<b>Your location</b>: where the lines on the map start from.'})}
<h3>Set your location</h3>
<ol><li>Click or tap the place name next to <b>Your location</b> (or open <b>Settings → Your location → Change</b>).</li>
<li>Start typing your city and pick it from the list. WhoSees looks it up on your device; it isn't sent anywhere.</li></ol>
{fig('d-location', 'Choosing your city', {'1': 'Type your city, then pick it from the list.'})}
<h3>Update checks</h3>
<p>The first time you open WhoSees, it asks whether you'd like it to check for updates. It's <b>off</b> unless you choose <b>Turn on update checks</b>. If you do, once a day when you open WhoSees it asks whosees.app for the newest version number. That request shows your internet address, like visiting any website, and nothing else. When a newer version is out, a short note appears with a <b>Download</b> button that opens the right page; WhoSees never installs anything by itself. You can change this any time in Settings.</p>
{phones(fig('p-updates', 'The first-launch question about update checks', {'1': '<b>No thanks</b> keeps it off.', '2': '<b>Turn on update checks</b>'}, True))}

<h2 id="live">Start a live view</h2>
<h3>On a computer</h3>
<ol><li>Press <b>Start live view</b>.</li>
<li>In <b>Standard</b> mode it starts right away, no password needed.</li>
<li>With <b>Deep mode</b> on, WhoSees first explains what's about to happen. Click <b>Continue</b>, then approve the request: Windows shows a Yes/No prompt; Linux asks for the password you log in with. Your password goes to your system, never to WhoSees.</li></ol>
{fig('d-deepask', 'Before Deep mode asks your system for permission', {'1': '<b>Continue</b> to Deep mode.', '2': '<b>Use Standard mode</b> instead (no password).'})}
<div class="box"><b class="mono">STANDARD OR DEEP?</b><p><b>Standard</b> shows apps, companies and places. <b>Deep</b> adds the names of the websites, labels trackers more precisely and catches very short connections. Both only look at where data goes, never what's inside it.</p></div>
<h3>On an Android phone</h3>
<ol><li>Tap <b>Start live view</b>.</li>
<li>The first time, WhoSees explains that Android will ask about a VPN. Tap <b>Continue</b>.</li>
<li>Android asks <i>"WhoSees wants to set up a VPN connection"</i>. Tap <b>OK</b>. The VPN stays on your phone: nothing is sent to a VPN server.</li></ol>
{phones(fig('p-start', 'Start screen on a phone', {'1': '<b>Start live view</b>', '2': '<b>Your location</b>'}, True),
        fig('p-vpnexplain', 'WhoSees explains the VPN question first', {'1': 'Tap <b>Continue</b>.'}, True),
        fig('p-vpnsystem', "Android's own question", {'1': 'Tap <b>OK</b>.'}, True))}

<h2 id="map">Read the live map</h2>
<p>Within seconds, lines start flying from your location to the places your apps send data to. Each colour is a kind of company.</p>
{fig('d-map', 'A live view on a computer', {'1': '<b>Totals</b>: how fast data is leaving now, how much has been sent, how many places and countries, and how many are trackers or advertisers.', '2': '<b>You</b>: your location. Every line starts here.', '3': '<b>A destination</b>: a company in another city. Brighter lines are active right now.', '4': '<b>Colour key</b>: what the colours mean. Click a colour to hide or show that kind.', '5': '<b>Tabs</b>: Apps, Feed, Places and Alerts.', '6': '<b>Stop</b> turns WhoSees off.'})}
<p>On a phone, the same things are stacked: the map on top, and a panel underneath you can tap the little handle on to make it bigger or smaller.</p>
{phones(fig('p-live', 'A live view on a phone', {'1': '<b>Totals</b>', '2': '<b>You</b>', '3': '<b>Tabs</b>', '4': '<b>Stop</b>'}, True))}

<h2 id="apps">See which apps send the most</h2>
<ol><li>Open the <b>Apps</b> tab. Apps are sorted by how much they've sent.</li>
<li>Each row says how many places and countries the app talks to, and the main company.</li>
<li>A red <b>TRACKER</b> label means the app talks to tracking or advertising companies.</li></ol>
{fig('d-apps', 'The Apps tab', {'1': 'An app, with the places and company it talks to. Click it for details.', '2': '<b>Tracker</b> label', '3': '<b>Search</b> apps, companies or countries.'})}

<h2 id="app">Find out what an app sends</h2>
<ol><li>In the <b>Apps</b> tab, click or tap an app.</li>
<li>Read the plain-English summary at the top.</li>
<li>Under <b>What this app sent</b>: <b>Seen</b> means WhoSees read it in data sent without encryption (like your location). <b>Likely</b> means the traffic was encrypted, so WhoSees tells you what that kind of company usually receives.</li>
<li>The <b>Privacy report</b> gives a simple grade (Good, Fair or Poor) and why.</li>
<li>Scroll down to see every place it sent data, then press <b>Back</b>.</li></ol>
{fig('d-appdetail', "An app's details", {'4': '<b>Back</b> to the list.', '1': 'A plain-English summary.', '3': '<b>What this app sent</b>: Seen and Likely.', '2': '<b>Privacy report</b> grade.'})}
{phones(fig('p-appdetail', 'The same on a phone (the panel is expanded)', {'1': 'Summary', '3': 'What it sent', '2': 'Privacy grade'}, True))}

<h2 id="place">Check a place on the map</h2>
<p>On a computer, point at any dot. On a phone, tap it. A card shows the city, the company, what it likely receives, and which of your apps send data there.</p>
{fig('d-hover', 'Pointing at a place', {'1': 'Point at (or tap) a dot.', '2': 'The city, company, likely data, and the apps sending there.'})}

<h2 id="companies">See every company and country</h2>
<p>Open the <b>Places</b> tab for a list of every company and place your data went, with a flag for each country. Click one to see which apps sent data there.</p>
{fig('d-places', 'The Places tab', {'1': '<b>Places</b> tab', '2': 'A company in a city, with how much was sent.'})}

<h2 id="feed">Watch connections as they happen</h2>
<p>The <b>Feed</b> tab lists each connection the moment it happens, newest first: which app, which company and where.</p>
{fig('d-feed', 'The Feed tab', {'1': '<b>Feed</b> tab', '2': 'The newest connection.'})}

<h2 id="search">Search</h2>
<p>Type in the search box above the list to find an app, a company or a country, for example <i>google</i> or <i>Ireland</i>. The list and the map show only what matches.</p>
{fig('d-search', 'Searching for "google"', {'1': 'Type here.', '2': 'Only matching results are shown.'})}

<h2 id="expert">Technical details (Expert)</h2>
<p>Switch from <b>Simple</b> to <b>Expert</b> at the top to see network addresses, ports, protocols and exact byte counts. Switch back to <b>Simple</b> any time.</p>
{fig('d-expert', 'Expert view', {'1': '<b>Expert</b> switch', '2': 'Technical details for each connection.'})}

<h2 id="alerts">When WhoSees warns you</h2>
<p>If an app connects to a known scam or malware website, or does something suspicious, a warning appears at once. On a phone you also get a notification.</p>
<ol><li>Read the warning: it says which app, where it connected and why that matters.</li>
<li>Press <b>Details</b> to see that app or place, or <b>Got it</b> if you recognise it and it's fine.</li>
<li>If you don't recognise the app, remove it. On a computer, if it runs from your Downloads or a temporary folder, close it and delete the file.</li>
<li>All warnings are kept in the <b>Alerts</b> tab until you stop.</li></ol>
{fig('d-alertcard', 'A warning on a computer', {'1': 'The warning.', '2': '<b>Got it</b> marks it as seen.', '3': 'The alert badge: click to see all warnings.'})}
{phones(fig('p-alert', 'A warning on a phone', {'1': 'The warning.', '2': '<b>Got it</b>'}, True))}
{fig('d-alerts', 'The Alerts tab', {'1': '<b>Alerts</b> tab', '2': 'Every warning from this session.'})}

<h2 id="privatedns">Missing website names on Android (Private DNS)</h2>
<p>If your phone uses <b>Private DNS</b> with a named provider, website names are encrypted before WhoSees can see them. WhoSees tells you when you press Start:</p>
<ol><li>To see website names, tap <b>Open Settings</b>, search for <b>Private DNS</b>, choose <b>Off</b>, then come back and press Start.</li>
<li>Or tap <b>Start anyway</b>: you'll still see the app, company and country.</li>
<li>Turn Private DNS back on when you're done. WhoSees reminds you when you press Stop.</li></ol>
{phones(fig('p-privatedns', 'The Private DNS notice', {'1': '<b>Open Settings</b>', '2': '<b>Start anyway</b>'}, True))}
<p>More in <a href="/guides/private-dns-android/">What is Private DNS on Android?</a></p>

<h2 id="settings">Settings</h2>
<p>Click or tap the <b>gear</b> at the top right.</p>
<table><tr><th>SETTING</th><th>WHAT IT DOES</th></tr>
<tr><td>Appearance</td><td>Follow your system, or always dark or light.</td></tr>
<tr><td>Your location</td><td>Where the lines start from. <b>Change</b> to pick another city.</td></tr>
<tr><td>Deep mode</td><td>(Computers) Website names and every connection; asks for permission each time you press Start.</td></tr>
<tr><td>Threat alerts</td><td>Warn about dangerous websites, malware servers and suspicious behaviour. On by default.</td></tr>
<tr><td>Include local network</td><td>Also list devices in your home, like printers and TVs.</td></tr>
<tr><td>Check for updates</td><td>Off unless you turn it on. When on, once a day when you open WhoSees it asks whosees.app for the newest version number and tells you if there's a newer one. <b>Check now</b> checks straight away.</td></tr>
<tr><td>About</td><td>Version, data credits and <b>Open-source licences</b>.</td></tr></table>
{fig('d-settings', 'Settings', {'1': 'The <b>gear</b> opens Settings.'})}

<h2 id="stop">Stop WhoSees</h2>
<p>Press <b>Stop</b> at the bottom of the map. WhoSees stops completely: nothing keeps running in the background. Closing the app does the same. On Android the VPN key icon disappears.</p>

<h2 id="support">Support WhoSees</h2>
<p>Every feature is free. If WhoSees is useful to you, open <b>Settings → Support WhoSees</b> (or the <a href="/#support">coffee section</a> on this website) and pick $5, $10 or $15. It opens PayPal in your browser; WhoSees never sees your payment details, and tipping doesn't change anything in the app.</p>
{fig('d-support', 'Buy me a coffee', {'1': 'Pick an amount to open PayPal.'})}

<h2 id="trouble">Troubleshooting</h2>
<table><tr><th>PROBLEM</th><th>WHAT TO DO</th></tr>
<tr><td>Nothing appears after Start</td><td>Use a few apps or open a website; connections appear within seconds.</td></tr>
<tr><td>The password window doesn't appear (Linux)</td><td>It may be behind the WhoSees window. Check your taskbar.</td></tr>
<tr><td>"Deep mode didn't start"</td><td>The password was wrong or the window was closed. Choose <b>Try again</b>, or <b>Keep Standard view</b>.</td></tr>
<tr><td>Windows says "Windows protected your PC" when installing</td><td>Click <b>More info</b>, then <b>Run anyway</b>. <a href="/windows/">Why this happens</a>.</td></tr>
<tr><td>"Is another VPN app on?" (Android)</td><td>Android allows one VPN at a time. Turn off the other VPN app, then press Start.</td></tr>
<tr><td>No website names (Android)</td><td>Private DNS is on. See <a href="#privatedns">above</a>.</td></tr>
<tr><td>An app shows as "Windows service" or "Short-lived program"</td><td>A protected Windows service, or a program that ran for only a moment. Deep mode names more of them.</td></tr></table>
{faq_html(guide_faq)}
"""
pages.append(page('guide/', 'WhoSees user guide: step by step, with pictures',
    'How to use WhoSees step by step: start a live view, read the map, find out what each app sends, handle warnings, change settings and fix common problems. With screenshots.',
    [], 'WhoSees user guide',
    'Everything you can do with WhoSees, step by step, with pictures from the app on a computer and an Android phone.',
    guide_body,
    [{"@context": "https://schema.org", "@type": "TechArticle", "headline": "WhoSees user guide", "datePublished": "2026-11-15", "dateModified": TODAY,
      "author": {"@type": "Person", "name": "TechyTJ"}, "publisher": {"@type": "Organization", "name": "WhoSees", "logo": {"@type": "ImageObject", "url": SITE + "/img/icon.png"}},
      "image": SITE + "/img/guide/d-map.webp", "mainEntityOfPage": SITE + "/guide/"}, faq_ld(guide_faq)],
    side_html=guide_side, kicker='USER GUIDE', doc_class='guide'))

# ---------------------------------------------------------------- sitemap
urls = [('', '1.0', 'weekly')] + [(p, '0.8' if p in ('android/', 'windows/', 'linux/', 'guide/') else '0.6', 'monthly') for p in pages]
open(os.path.join(ROOT, 'sitemap.xml'), 'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    ''.join(f'  <url><loc>{SITE}/{p}</loc><lastmod>{TODAY}</lastmod><changefreq>{f}</changefreq><priority>{pr}</priority></url>\n' for p, pr, f in urls) + '</urlset>\n')
print(f'{len(pages)} pages + sitemap ({len(urls)} URLs)')
