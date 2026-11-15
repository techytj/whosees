package io.github.techytj.wiretrace

import android.content.Intent
import android.net.ConnectivityManager
import android.net.VpnService
import android.os.ParcelFileDescriptor
import org.json.JSONArray
import org.json.JSONObject

/**
 * Local-only VPN: Android routes every app's traffic to us, the engine forwards it to where it
 * was going anyway. Nothing is sent to any VPN server. Runs only while a live view is on.
 */
class WtVpnService : VpnService() {
    companion object {
        const val VIRTUAL_DNS = "10.111.222.3"
        @Volatile var running = false
        @Volatile var lastError: String? = null
        var lan = false
    }
    private var tun: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "stop") { shutdown(); stopSelf(); return START_NOT_STICKY }
        if (running) return START_NOT_STICKY
        // The phone's real DNS servers, captured before our VPN takes over, so lookups go where they always went.
        val cm = getSystemService(ConnectivityManager::class.java)
        val net = cm.activeNetwork
        val lp = cm.getLinkProperties(net)
        // The phone's real DNS servers (IPv4 first; link-local IPv6 servers need an interface we can't pass on).
        val dns = (lp?.dnsServers ?: emptyList())
            .filter { !it.isLinkLocalAddress && !it.isLoopbackAddress }
            .sortedBy { if (it is java.net.Inet4Address) 0 else 1 }
            .map { it.hostAddress!!.substringBefore('%') }
        // Only offer IPv6 to apps if the real network has it; otherwise apps try IPv6 first and some never fall back.
        val hasV6 = lp?.linkAddresses?.any { it.address is java.net.Inet6Address && !it.address.isLinkLocalAddress && !it.address.isSiteLocalAddress } == true &&
            lp.routes.any { it.destination.address is java.net.Inet6Address && it.isDefaultRoute }
        val b = Builder()
            .setSession("WhoSees live view")
            .addAddress("10.111.222.1", 24)
            .addRoute("0.0.0.0", 0)
            .addDnsServer(VIRTUAL_DNS)
            .setMtu(1500)
            .setBlocking(false)
        if (hasV6) b.addAddress("fd00:7772:7472::1", 64).addRoute("::", 0)
        // Tell Android which real network we ride on, and don't mark it metered unless that network is,
        // so apps that check "am I online / on Wi-Fi / metered?" see the same answer as without WhoSees.
        if (net != null) b.setUnderlyingNetworks(arrayOf(net))
        b.setMetered(false)
        b.addDisallowedApplication(packageName) // our own forwarding sockets go straight out
        val fd = try { b.establish() } catch (e: Exception) { lastError = e.message; null }
        if (fd == null) { running = false; stopSelf(); return START_NOT_STICKY }
        tun = fd
        val files = filesDir.absolutePath
        val cfg = JSONObject()
            .put("geo", "$files/shared/geo/world.wtgeo")
            .put("categories", "$files/shared/categories/domains.json")
            .put("threats", "$files/shared/threats")
            .put("upstream_dns", JSONArray(if (dns.isEmpty()) listOf("1.1.1.1") else dns))
            .put("virtual_dns", VIRTUAL_DNS)
            .put("lan", lan)
        // The engine takes ownership of the fd.
        val rc = Engine.nativeStart(fd.detachFd(), cfg.toString())
        running = rc == 0
        if (!running) { lastError = "engine failed to start"; stopSelf() }
        return START_NOT_STICKY
    }

    private fun shutdown() {
        if (running) Engine.nativeStop()
        running = false
        tun?.close(); tun = null
    }

    override fun onRevoke() { shutdown(); super.onRevoke() }   // user turned the VPN off in Settings
    override fun onDestroy() { shutdown(); super.onDestroy() }
}
