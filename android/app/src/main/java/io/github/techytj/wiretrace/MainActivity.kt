package io.github.techytj.wiretrace

import android.annotation.SuppressLint
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.provider.Settings
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.print.PrintAttributes
import android.print.PrintManager
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer

/**
 * Hosts the same UI as the desktop app (desktop/app/renderer) in a WebView. A small bridge plays
 * the role of the desktop preload script: start/stop the VPN, relay engine events, settings, icons.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val ui = Handler(Looper.getMainLooper())
    private var pendingStart: JSONObject? = null
    private val prefs by lazy { getSharedPreferences("wiretrace", MODE_PRIVATE) }
    private val iconCache = HashMap<String, String?>()
    private var printWeb: WebView? = null // kept alive while Android's print screen reads it

    private val pump = object : Runnable {
        override fun run() {
            if (WtVpnService.running) {
                val evs = Engine.nativePoll()
                if (evs != "[]") web.evaluateJavascript("window.__wtOnEvents && window.__wtOnEvents($evs)", null)
            }
            ui.postDelayed(this, 80)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Engine.app = applicationContext
        Thread { unpackData() }.start()
        // Test builds only: let the regression tests drive the UI over the DevTools protocol.
        WebView.setWebContentsDebuggingEnabled((applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0)
        web = WebView(this)
        setContentView(web)
        window.setDecorFitsSystemWindows(false)
        val loader = WebViewAssetLoader.Builder().addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build()
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest) = loader.shouldInterceptRequest(request.url)
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                if (u.host == "appassets.androidplatform.net") return false
                if (u.scheme == "https") startActivity(Intent(Intent.ACTION_VIEW, u))
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: android.webkit.ConsoleMessage): Boolean {
                android.util.Log.i("WhoSeesUI", m.message()); return true
            }
        }
        with(web.settings) { javaScriptEnabled = true; domStorageEnabled = true; allowFileAccess = false; allowContentAccess = false; mediaPlaybackRequiresUserGesture = true }
        web.addJavascriptInterface(Bridge(), "WtAndroid")
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(web, SHIM, setOf("https://appassets.androidplatform.net"))
        }
        web.setBackgroundColor(0xff0a0b0d.toInt())
        web.loadUrl("https://appassets.androidplatform.net/assets/app/renderer/index.html")
        ui.post(pump)
        if (intent?.getBooleanExtra("autostart", false) == true) ui.postDelayed({ web.evaluateJavascript("document.getElementById('startBtn')?.click()", null) }, 4000)
    }

    /** Big data files are unpacked once (the engine memory-maps them). */
    private fun unpackData() {
        val marker = File(filesDir, "shared/.version")
        val version = packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        if (marker.exists() && marker.readText() == version) return
        for (f in listOf("geo/world.wtgeo", "categories/domains.json", "threats/domains.txt", "threats/ips.txt")) {
            val out = File(filesDir, "shared/$f"); out.parentFile?.mkdirs()
            assets.open("shared/$f").use { i -> out.outputStream().use { i.copyTo(it, 1 shl 16) } }
        }
        marker.writeText(version)
    }

    private fun emit(js: String) = ui.post { web.evaluateJavascript(js, null) }

    private fun startVpn(opts: JSONObject) {
        WtVpnService.lan = opts.optBoolean("lan")
        val consent = VpnService.prepare(this)
        if (consent != null) { pendingStart = opts; startActivityForResult(consent, 42); return }
        launchVpn()
    }

    private fun launchVpn() {
        Thread {
            // the engine needs the unpacked data
            var n = 0; while (!File(filesDir, "shared/.version").exists() && n++ < 300) Thread.sleep(100)
            WtVpnService.lastError = null
            startService(Intent(this, WtVpnService::class.java))
            n = 0; while (!WtVpnService.running && WtVpnService.lastError == null && n++ < 50) Thread.sleep(100)
            val r = if (WtVpnService.running) JSONObject().put("ok", true)
                    else JSONObject().put("ok", false).put("error", WtVpnService.lastError ?: "The VPN could not start. Is another VPN app on?")
            emit("window.__wtStartResolve && window.__wtStartResolve($r)")
        }.start()
    }

    @Deprecated("Activity API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 42) return
        if (resultCode == RESULT_OK) launchVpn()
        else emit("window.__wtStartResolve && window.__wtStartResolve({ok:true});" +
                  "window.__wtOnEvents && window.__wtOnEvents([{t:'deepfail',code:126,detail:'VPN permission declined'}]);" +
                  "window.__wtOnExit && window.__wtOnExit({code:126})")
    }

    override fun onDestroy() {
        // A live view never outlives the app.
        if (WtVpnService.running) startService(Intent(this, WtVpnService::class.java).setAction("stop"))
        ui.removeCallbacks(pump)
        super.onDestroy()
    }

    override fun onConfigurationChanged(c: Configuration) { super.onConfigurationChanged(c); emit("window.dispatchEvent(new Event('resize'))") }

    @Deprecated("Activity API")
    override fun onBackPressed() {
        web.evaluateJavascript("(function(){var b=document.querySelector('[data-back]');if(b&&!document.getElementById('detail').hidden){b.click();return 1}var d=document.getElementById('dlg');if(d&&d.open){d.close();return 1}return 0})()") {
            if (it != "1") @Suppress("DEPRECATION") super.onBackPressed()
        }
    }

    inner class Bridge {
        @JavascriptInterface fun start(opts: String) { ui.post { startVpn(JSONObject(opts)) } }
        @JavascriptInterface fun stop(): String {
            startService(Intent(this@MainActivity, WtVpnService::class.java).setAction("stop"))
            return "{\"ok\":true}"
        }
        @JavascriptInterface fun send(msg: String): Boolean { if (WtVpnService.running) Engine.nativeCommand(msg); return WtVpnService.running }
        @JavascriptInterface fun findCity(q: String): String {
            val geo = File(filesDir, "shared/geo/world.wtgeo")
            return if (geo.exists()) Engine.nativeFindCity(geo.path, q) else "[]"
        }
        /** Byte range of the offline map (stored uncompressed inside the APK). */
        @JavascriptInterface fun readTiles(offset: Double, length: Double): String {
            assets.openFd("shared/map/world-z6.pmtiles").use { afd ->
                FileInputStream(afd.fileDescriptor).channel.use { ch ->
                    val buf = ByteBuffer.allocate(length.toInt())
                    var pos = afd.startOffset + offset.toLong()
                    while (buf.hasRemaining()) { val n = ch.read(buf, pos); if (n <= 0) break; pos += n }
                    return Base64.encodeToString(buf.array(), 0, buf.position(), Base64.NO_WRAP)
                }
            }
        }
        @JavascriptInterface fun icon(id: String): String? = synchronized(iconCache) {
            iconCache.getOrPut(id) {
                if (!id.startsWith("pkg:")) return@getOrPut null
                try {
                    val d = packageManager.getApplicationIcon(id.removePrefix("pkg:"))
                    val bmp = Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888)
                    d.setBounds(0, 0, 96, 96); d.draw(Canvas(bmp))
                    val out = ByteArrayOutputStream(); bmp.compress(Bitmap.CompressFormat.PNG, 100, out)
                    "data:image/png;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                } catch (e: Exception) { null }
            }
        }
        @JavascriptInterface fun getSettings(): String = prefs.getString("settings", "{}") ?: "{}"
        @JavascriptInterface fun setSettings(patch: String): String {
            val cur = JSONObject(getSettings()); val p = JSONObject(patch)
            for (k in p.keys()) cur.put(k, p.get(k))
            prefs.edit().putString("settings", cur.toString()).apply()
            return cur.toString()
        }
        /** Update check (off unless the user turns it on): one small public file, bare user agent, nothing about the user. */
        @JavascriptInterface fun checkUpdate() {
            Thread {
                val r = try {
                    val c = java.net.URL("https://whosees.app/version.json").openConnection() as java.net.HttpURLConnection
                    c.connectTimeout = 8000; c.readTimeout = 8000; c.useCaches = false
                    c.setRequestProperty("User-Agent", "WhoSees"); c.setRequestProperty("Accept", "application/json")
                    if (c.responseCode != 200) JSONObject().put("ok", false).put("error", "HTTP ${c.responseCode}")
                    else {
                        val j = JSONObject(c.inputStream.bufferedReader().use { it.readText().take(65536) })
                        JSONObject().put("ok", true).put("latest", j.optString("latest")).put("released", j.optString("released")).put("notes", j.optString("notes"))
                    }
                } catch (e: Exception) { JSONObject().put("ok", false).put("error", e.message ?: "error") }
                emit("window.__wtUpdateResolve && window.__wtUpdateResolve($r)")
            }.start()
        }
        @JavascriptInterface fun info(): String = JSONObject().put("version", packageManager.getPackageInfo(packageName, 0).versionName ?: "0.0.0").put("platform", "android")
            .put("agent", true).put("geo", true).put("tiles", true).put("user", "").toString()
        /** Private DNS on the real network (not our VPN). "server" is set only in hostname mode, the one that hides website names. */
        @JavascriptInterface fun privateDns(): String {
            val cm = getSystemService(ConnectivityManager::class.java)
            @Suppress("DEPRECATION")
            val net = cm.allNetworks.firstOrNull { n -> cm.getNetworkCapabilities(n)?.let {
                it.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) && !it.hasTransport(NetworkCapabilities.TRANSPORT_VPN) } == true }
            val lp = net?.let { cm.getLinkProperties(it) }
            return JSONObject().put("active", lp?.isPrivateDnsActive == true).put("server", lp?.privateDnsServerName ?: JSONObject.NULL).toString()
        }
        @JavascriptInterface fun openNetworkSettings() {
            runCatching { startActivity(Intent(Settings.ACTION_WIRELESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                .onFailure { startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }
        /** Report: Android's print screen, where "Save as PDF" makes the file. Scripts and network are off for the page. */
        @JavascriptInterface fun printReport(html: String, name: String, paper: String) {
            ui.post {
                val w = WebView(this@MainActivity)
                w.settings.javaScriptEnabled = false
                w.settings.blockNetworkLoads = true
                var done = false
                w.webViewClient = object : WebViewClient() {
                    override fun onPageFinished(view: WebView, url: String?) {
                        if (done) return; done = true
                        val job = name.removeSuffix(".pdf")
                        val attrs = PrintAttributes.Builder()
                            .setMediaSize(if (paper == "a4") PrintAttributes.MediaSize.ISO_A4 else PrintAttributes.MediaSize.NA_LETTER)
                            .setMinMargins(PrintAttributes.Margins.NO_MARGINS).build()
                        getSystemService(PrintManager::class.java).print(job, view.createPrintDocumentAdapter(job), attrs)
                    }
                }
                printWeb = w
                w.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
            }
        }
        @JavascriptInterface fun isDark(): Boolean = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        @JavascriptInterface fun notify(title: String, body: String) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel("alerts", "Threat alerts", NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(this@MainActivity, 0, Intent(this@MainActivity, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
            nm.notify((System.currentTimeMillis() % 100000).toInt(), Notification.Builder(this@MainActivity, "alerts")
                .setSmallIcon(R.drawable.ic_stat).setContentTitle(title).setContentText(body)
                .setStyle(Notification.BigTextStyle().bigText(body)).setContentIntent(open).setAutoCancel(true).build())
        }
    }

    companion object {
        /** Runs before the page's own scripts: provides window.wt like the desktop preload does. */
        const val SHIM = """
(function () {
  if (!window.WtAndroid) return;
  const A = window.WtAndroid;
  const b64 = (s) => { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };
  let onEvents = null, onExit = null;
  window.__wtOnEvents = (evs) => onEvents && onEvents(evs);
  window.__wtOnExit = (i) => onExit && onExit(i);
  window.wt = {
    platform: 'android',
    glyphs: 'https://appassets.androidplatform.net/assets/shared/map/fonts/{fontstack}/{range}.pbf',
    start: (o) => new Promise((res) => { window.__wtStartResolve = (r) => { window.__wtStartResolve = null; res(r); }; A.start(JSON.stringify(o || {})); }),
    stop: async () => JSON.parse(A.stop()),
    send: async (m) => A.send(JSON.stringify(m)),
    onEvents: (fn) => { onEvents = fn; },
    onExit: (fn) => { onExit = fn; },
    findCity: async (q) => JSON.parse(A.findCity(q)),
    readTiles: async (o, l) => b64(A.readTiles(o, l)),
    icon: async (p) => A.icon(p) || null,
    getSettings: async () => JSON.parse(A.getSettings()),
    setSettings: async (p) => JSON.parse(A.setSettings(JSON.stringify(p))),
    setTheme: async (mode) => mode === 'dark' || (mode === 'system' && A.isDark()),
    info: async () => JSON.parse(A.info()),
    checkUpdate: () => new Promise((res) => { window.__wtUpdateResolve = (r) => { window.__wtUpdateResolve = null; res(r); }; A.checkUpdate(); }),
    privateDns: async () => JSON.parse(A.privateDns()),
    openNetworkSettings: () => A.openNetworkSettings(),
    saveReport: async (o) => { A.printReport(o.html, o.name, o.paper || 'letter'); return { ok: true, system: true }; },
  };
  window.Notification = class { constructor(t, o) { A.notify(String(t), String((o && o.body) || '')); } static get permission() { return 'granted'; } };
})();
"""
    }
}
