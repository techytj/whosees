package io.github.techytj.wiretrace

import android.content.Context
import android.content.pm.ApplicationInfo
import android.net.ConnectivityManager
import android.os.Process
import org.json.JSONObject
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.ConcurrentHashMap

/** Bridge to the Rust engine (libwtengine.so). */
object Engine {
    init { System.loadLibrary("wtengine") }

    @JvmStatic external fun nativeStart(tunFd: Int, configJson: String): Int
    @JvmStatic external fun nativeStop()
    @JvmStatic external fun nativePoll(): String
    @JvmStatic external fun nativeCommand(json: String)
    @JvmStatic external fun nativeFindCity(geoPath: String, query: String): String

    lateinit var app: Context
    private val byUid = ConcurrentHashMap<Int, String>()

    /**
     * Called by the engine for each new connection: which app owns it?
     * Android tells VPN apps the owner's uid; PackageManager turns that into a name and icon.
     */
    @JvmStatic
    fun appFor(proto: Int, src: String, sport: Int, dst: String, dport: Int): String {
        val uid = try {
            val cm = app.getSystemService(ConnectivityManager::class.java)
            cm.getConnectionOwnerUid(proto, InetSocketAddress(InetAddress.getByName(src), sport), InetSocketAddress(InetAddress.getByName(dst), dport))
        } catch (e: Exception) { Process.INVALID_UID }
        return byUid.getOrPut(uid) { describe(uid) }
    }

    /** Sensitive permissions this app has actually been granted (so we can say what *could* be in its traffic). */
    private fun grantedSensitive(pkg: String): List<String> {
        val map = mapOf(
            "android.permission.ACCESS_FINE_LOCATION" to "location", "android.permission.ACCESS_COARSE_LOCATION" to "location",
            "android.permission.ACCESS_BACKGROUND_LOCATION" to "location", "android.permission.READ_CONTACTS" to "contacts",
            "android.permission.CAMERA" to "camera", "android.permission.RECORD_AUDIO" to "microphone",
            "android.permission.READ_PHONE_STATE" to "phone", "android.permission.READ_PHONE_NUMBERS" to "phone",
            "android.permission.READ_CALL_LOG" to "calls", "android.permission.READ_SMS" to "sms",
            "android.permission.READ_CALENDAR" to "calendar", "android.permission.READ_MEDIA_IMAGES" to "photos",
            "android.permission.READ_MEDIA_VIDEO" to "photos", "android.permission.READ_EXTERNAL_STORAGE" to "photos",
            "android.permission.BODY_SENSORS" to "health", "android.permission.ACTIVITY_RECOGNITION" to "activity",
        )
        return try {
            val pi = app.packageManager.getPackageInfo(pkg, android.content.pm.PackageManager.GET_PERMISSIONS)
            val req = pi.requestedPermissions ?: return emptyList()
            val flags = pi.requestedPermissionsFlags ?: return emptyList()
            req.indices.filter { (flags[it] and android.content.pm.PackageInfo.REQUESTED_PERMISSION_GRANTED) != 0 }
                .mapNotNull { map[req[it]] }.distinct()
        } catch (e: Exception) { emptyList() }
    }

    private fun describe(uid: Int): String {
        val o = JSONObject().put("uid", uid)
        if (uid < 0) return o.put("id", "unknown").put("name", "Unknown app").put("system", false).toString()
        if (uid < Process.FIRST_APPLICATION_UID) {
            val name = when (uid) { 0 -> "Android system (root)"; 1000 -> "Android system"; 1013 -> "Media server"; 1051 -> "Android DNS"; else -> "Android system service" }
            return o.put("id", "uid:$uid").put("name", name).put("system", true).toString()
        }
        val pm = app.packageManager
        val pkgs = pm.getPackagesForUid(uid) ?: emptyArray()
        val pkg = pkgs.firstOrNull() ?: return o.put("id", "uid:$uid").put("name", "App $uid").put("system", false).toString()
        return try {
            val ai = pm.getApplicationInfo(pkg, 0)
            val label = pm.getApplicationLabel(ai).toString() + if (pkgs.size > 1) " (+${pkgs.size - 1})" else ""
            o.put("id", pkg).put("name", label).put("icon", "pkg:$pkg").put("system", false) // preinstalled apps (Chrome, Play Store) are still apps to the user
                .put("preinstalled", (ai.flags and ApplicationInfo.FLAG_SYSTEM) != 0)
                .put("perms", org.json.JSONArray(grantedSensitive(pkg))).toString()
        } catch (e: Exception) {
            o.put("id", pkg).put("name", pkg).put("system", false).toString()
        }
    }
}
