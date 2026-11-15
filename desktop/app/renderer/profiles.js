// What specific services are built to collect, and what you can do about it.
//
// Every entry is based on the company's own documentation (or, for a few OS services, its own published
// policy), linked in `src`. Contents of encrypted traffic can't be read, so the app shows these as "Likely":
// they describe what the service is designed to receive, not what this particular connection carried.
//
// hosts: hostname suffixes ("app-measurement.com" also matches "region1.app-measurement.com");
//        a leading "=" means that exact name only.
// os:    only show on this platform ('linux' | 'win32' | 'android'), for operating-system services.
// app:   only for connections from a program whose name matches.
// how:   a short "where to change it" note, for settings that have no web page.

export const PROFILES = [
  // ---------- Google ----------
  { id: 'firebase-analytics', name: 'Google Analytics for Firebase', owner: 'Google', hosts: ['app-measurement.com'],
    what: 'Usage measurement built into many apps.',
    sends: ['Screens and actions in the app', 'An ID for this app install', 'Advertising ID (all zeros if you turned off ad personalisation)', 'Device and session details', 'Rough location'],
    src: 'https://support.google.com/analytics/answer/11593727' },
  { id: 'google-analytics', name: 'Google Analytics', owner: 'Google', hosts: ['google-analytics.com', 'analytics.google.com'],
    what: 'Website and app usage measurement.',
    sends: ['Pages and screens you view, and what you do there', 'A cookie or app ID that recognises you on return', 'Browser and device details', 'Rough location'],
    src: 'https://support.google.com/analytics/answer/11593727' },
  { id: 'crashlytics', name: 'Firebase Crashlytics', owner: 'Google', hosts: ['crashlytics.com', 'crashlyticsreports-pa.googleapis.com'],
    what: 'Crash reporting for app developers.',
    sends: ['Crash reports', 'An ID for this app install', 'Device model and OS version', 'App version'],
    src: 'https://firebase.google.com/support/privacy' },
  { id: 'firebase-core', name: 'Firebase installs, push and remote settings', owner: 'Google',
    hosts: ['firebaseinstallations.googleapis.com', 'fcm.googleapis.com', 'fcmregistrations.googleapis.com', 'firebaseremoteconfig.googleapis.com', 'firebaseperformance.googleapis.com'],
    what: 'Background plumbing many apps use for notifications and settings.',
    sends: ['An ID for this app install', 'Device details', 'Your internet address (Performance Monitoring maps it to a country)'],
    src: 'https://firebase.google.com/support/privacy' },
  { id: 'google-ads', name: 'Google advertising', owner: 'Google',
    hosts: ['doubleclick.net', 'googlesyndication.com', 'googleadservices.com', 'googletagservices.com', '=adservice.google.com', '2mdn.net'],
    what: 'DoubleClick, AdSense and Google Ads: shows ads and measures them across many sites and apps.',
    sends: ['Websites you visit that show Google ads', 'Ads you see and click', 'Your internet address', 'Browser type and language', 'Cookie ID, or on phones the advertising ID'],
    src: 'https://policies.google.com/technologies/ads' },
  { id: 'android-checkin', name: 'Android check-in (Google Play services)', owner: 'Google', os: 'android',
    hosts: ['=android.clients.google.com', '=android.googleapis.com'],
    what: 'Android phones with Google apps check in with Google regularly.',
    sends: ['Device type and carrier name', 'Crash reports', 'Which apps you have installed'],
    src: 'https://policies.google.com/privacy' },

  // ---------- Meta ----------
  { id: 'meta-app-events', name: 'Meta SDK (Facebook app events)', owner: 'Meta', hosts: ['=graph.facebook.com', '=b-graph.facebook.com'],
    what: 'Apps add it for Facebook login, sharing or ad measurement. It can report app activity even if you never log in with Facebook.',
    sends: ['That the app was installed and opened', 'Purchases made in the app', 'App details such as screen titles'],
    src: 'https://developers.facebook.com/docs/app-events/automatic-event-collection-detail' },
  { id: 'meta-pixel', name: 'Meta Pixel', owner: 'Meta', hosts: ['=connect.facebook.net', 'facebook.net'],
    what: 'Websites add it to measure Facebook and Instagram ads.',
    sends: ['Your internet address and browser details', 'The page you are on and the page you came from', 'Buttons you click', 'The Facebook cookie, which links visits to you'],
    src: 'https://developers.facebook.com/docs/meta-pixel/' },

  // ---------- other ad and social platforms ----------
  { id: 'tiktok-pixel', name: 'TikTok Pixel', owner: 'ByteDance', hosts: ['=analytics.tiktok.com'],
    what: 'Websites add it to measure TikTok ads.',
    sends: ['Ads you clicked and what you do on the site', 'Your internet address (used for location)', 'Device, OS and browser', 'Cookies'],
    src: 'https://ads.tiktok.com/help/article/tiktok-pixel' },
  { id: 'clarity', name: 'Microsoft Clarity', owner: 'Microsoft', hosts: ['clarity.ms'],
    what: 'Records visits so site owners can replay them.',
    sends: ['Clicks, scrolling, mouse movement and typing events', 'The page layout, to replay your visit (sensitive text is masked)', 'A user and session ID'],
    src: 'https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data' },

  // ---------- app measurement and attribution ----------
  { id: 'appsflyer', name: 'AppsFlyer', owner: 'AppsFlyer', hosts: ['appsflyer.com', 'appsflyersdk.com', 'onelink.me'],
    what: 'Tells advertisers which ad led you to install or use an app.',
    sends: ['Advertising ID, Android ID and internet address', 'Ads you saw and clicked', 'App installs and in-app events such as purchases', 'Device model, OS, language and carrier'],
    src: 'https://www.appsflyer.com/legal/services-privacy-policy/' },
  { id: 'branch', name: 'Branch', owner: 'Branch Metrics', hosts: ['branch.io', '=app.link', 'bnc.lt'],
    what: 'Deep links and ad attribution for apps.',
    sends: ['Advertising IDs and internet address', 'Links and ads you clicked', 'App installs, opens and in-app events', 'Device model, OS, language and carrier'],
    src: 'https://legal.branch.io/saas/privacy-policy/' },
  { id: 'onesignal', name: 'OneSignal', owner: 'OneSignal', hosts: ['onesignal.com', '=os.tc'],
    what: 'Push notifications and in-app messages.',
    sends: ['Device and account IDs', 'Internet address and the location it points to', 'Purchases and taps in the app', 'Device, OS, carrier, language and time zone', 'Session times', 'Precise location, only if the app has that permission'],
    src: 'https://onesignal.com/privacy_policy' },
  { id: 'mixpanel', name: 'Mixpanel', owner: 'Mixpanel', hosts: ['mixpanel.com', 'mxpnl.com'],
    what: 'Product analytics: which features people use.',
    sends: ['Actions you take in the app', 'A device ID, and your user ID once you sign in', 'OS, screen size, device model and carrier', 'City and region (worked out from your internet address)'],
    src: 'https://docs.mixpanel.com/docs/data-structure/property-reference/default-properties' },
  { id: 'sentry', name: 'Sentry', owner: 'Sentry', hosts: ['sentry.io'],
    what: 'Error reporting for app and website developers.',
    sends: ['Error reports', 'Your internet address', 'Browser, OS and device type', 'Recent app log lines, which can include personal details'],
    src: 'https://docs.sentry.io/platforms/javascript/data-management/data-collected/' },

  // ---------- operating systems and browsers ----------
  { id: 'windows-diag', name: 'Windows diagnostic data', owner: 'Microsoft', os: 'win32',
    hosts: ['events.data.microsoft.com', 'vortex-win.data.microsoft.com', 'telemetry.microsoft.com'],
    what: 'Windows reports on itself to Microsoft. "Required" is always on; "Optional" sends more.',
    sends: ['Hardware, driver and Windows details', 'Crashes, hangs and how apps perform', 'Which apps are installed', 'Microsoft Store downloads and installs', 'With Optional data: apps you open, Edge browsing history and searches, crash memory'],
    src: 'https://learn.microsoft.com/en-us/windows/privacy/configure-windows-diagnostic-data-in-your-organization' },
  { id: 'firefox-telemetry', name: 'Firefox technical and interaction data', owner: 'Mozilla', hosts: ['=incoming.telemetry.mozilla.org'],
    what: 'Firefox reports how it performs. Mozilla says it does not include browsing history, searches or passwords.',
    sends: ['Performance, such as page load times and memory use', 'Which Firefox features you use', 'OS, Firefox version and hardware'],
    src: 'https://support.mozilla.org/kb/telemetry-clientid' },
  { id: 'fedora-countme', name: 'Fedora update check (DNF)', owner: 'Fedora', os: 'linux', hosts: ['=mirrors.fedoraproject.org'],
    what: 'Finds update mirrors. About once a week it also adds a "count me" flag so Fedora can count active systems.',
    sends: ['Fedora version and edition, and processor type', 'Roughly how long this system has been installed (no unique ID)'],
    src: 'https://fedoraproject.org/wiki/Changes/DNF_Better_Counting' },
  { id: 'nm-connectivity', name: 'Internet connection check', owner: '', os: 'linux', app: /networkmanager/i, // a browser visit to fedoraproject.org is not a check
    hosts: ['=fedoraproject.org', '=connectivity-check.ubuntu.com', '=nmcheck.gnome.org', '=networkcheck.kde.org', '=network-test.debian.org'],
    what: 'NetworkManager fetches a small test page (every 5 minutes by default) to see whether you are online or behind a hotel-style login page.',
    sends: ['Only that this computer is online, and its internet address'],
    src: 'https://networkmanager.dev/docs/api/latest/NetworkManager.conf.html' },
];

// What you can do, per company. `os` limits a step to one platform.
export const CONTROLS = {
  Google: [
    { label: 'Turn off personalised ads (My Ad Center)', url: 'https://myadcenter.google.com/' },
    { label: 'Choose what Google saves (Activity controls)', url: 'https://myactivity.google.com/activitycontrols' },
    { label: 'Reset or delete your advertising ID', how: 'Settings › Privacy › Ads', os: 'android', url: 'https://support.google.com/googleplay/android-developer/answer/6048248' },
  ],
  Meta: [
    { label: 'Disconnect your activity off Meta (future and past)', how: 'Accounts Center › Your information and permissions › Your activity off Meta technologies', url: 'https://www.facebook.com/off_facebook_activity/' },
  ],
  Microsoft: [
    { label: 'Turn off personalised ads', url: 'https://account.microsoft.com/privacy/ad-settings' },
    { label: 'Send only required diagnostic data', how: 'Settings › Privacy & security › Diagnostics & feedback', os: 'win32', url: 'https://support.microsoft.com/windows/28808a2b-a31b-dd73-dcd3-4559a5199319' },
    { label: 'Turn off the advertising ID', how: 'Settings › Privacy & security › General', os: 'win32' },
  ],
  Amazon: [{ label: 'Turn off interest-based ads', url: 'https://www.amazon.com/adprefs' }],
  'X (formerly Twitter)': [{ label: 'Ad preferences', url: 'https://x.com/settings/ads_preferences' }],
  AppsFlyer: [{ label: 'Ask AppsFlyer to stop tracking your device', url: 'https://appsflyer.com/legal/opt-out/' }],
  Mozilla: [{ label: 'Turn off technical and interaction data', how: 'Firefox Settings › Privacy & Security › Firefox Data Collection and Use', url: 'https://support.mozilla.org/kb/telemetry-clientid' }],
  Fedora: [{ label: 'Stop the weekly count', how: 'set countme=0 for your repositories (a [*] section in /etc/dnf/repos.override.d/ on DNF5)', os: 'linux', url: 'https://discussion.fedoraproject.org/t/opt-out-countme-is-anything-but-easy/113551' }],
};
// For advertising companies with no page of their own: the industry opt-out (works per browser).
export const ADS_FALLBACK = { label: 'Opt out of many ad companies at once (per browser)', url: 'https://optout.networkadvertising.org/' };
// Profiles for connection checks have no company to act on, but NetworkManager can be told not to check.
CONTROLS[''] = [];
PROFILES.find((p) => p.id === 'nm-connectivity').control =
  { label: 'Turn the check off', how: 'add [connectivity] enabled=false to a file in /etc/NetworkManager/conf.d/', url: 'https://networkmanager.dev/docs/api/latest/NetworkManager.conf.html' };

const exact = new Map(), suffix = new Map();
for (const p of PROFILES) for (const h of p.hosts) (h.startsWith('=') ? exact : suffix).set(h.replace(/^=/, ''), p);

/** The profile for a hostname: exact names first, then the longest matching suffix. */
export function profileFor(host, platform, appName) {
  if (!host) return null;
  let h = String(host).toLowerCase().replace(/\.$/, '');
  const ok = (p) => p && (!p.os || p.os === platform) && (!p.app || p.app.test(appName || '')) ? p : null;
  if (exact.has(h)) return ok(exact.get(h));
  for (;;) {
    if (suffix.has(h)) return ok(suffix.get(h));
    const i = h.indexOf('.');
    if (i < 0) return null;
    h = h.slice(i + 1);
  }
}

/** Steps for one company (and profile), filtered to this platform. */
export function controlsFor(owner, profiles, platform, isAds) {
  const out = [], seen = new Set();
  const add = (c) => { if (c && (!c.os || c.os === platform) && !seen.has(c.label)) { seen.add(c.label); out.push(c); } };
  for (const p of profiles) { add(p.control); (CONTROLS[p.owner] || []).forEach(add); }
  (CONTROLS[owner] || []).forEach(add);
  if (isAds && !out.length) add(ADS_FALLBACK);
  return out;
}
