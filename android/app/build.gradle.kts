import java.util.Properties
plugins { id("com.android.application") }

android {
    namespace = "io.github.techytj.wiretrace"
    compileSdk = 36
    defaultConfig {
        applicationId = "io.github.techytj.whosees"
        minSdk = 29          // getConnectionOwnerUid (which app owns a connection) needs Android 10
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    // Release signing: the key lives outside the repo. android/keystore.properties (never committed) points to it;
    // without that file, release builds fall back to the debug key (fine for testing, not for publishing).
    val ks = rootProject.file("keystore.properties").takeIf { it.exists() }?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }
    signingConfigs {
        if (ks != null) create("release") {
            storeFile = file(ks.getProperty("storeFile")); storePassword = ks.getProperty("storePassword")
            keyAlias = ks.getProperty("keyAlias"); keyPassword = ks.getProperty("keyPassword")
        }
    }
    buildTypes {
        release { isMinifyEnabled = false; signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug") }
    }
    androidResources { noCompress += listOf("pmtiles") } // read map tiles straight out of the APK
    sourceSets["main"].assets.directories.add(layout.buildDirectory.dir("wtassets").get().asFile.path)
    packaging { jniLibs { useLegacyPackaging = false } }
}

dependencies { implementation("androidx.webkit:webkit:1.18.0") }

// The shared UI and data come straight from the desktop app and shared/ (one design, one codebase).
val copyShared by tasks.registering(Sync::class) {
    val root = rootDir.parentFile
    into(layout.buildDirectory.dir("wtassets"))
    from(File(root, "desktop/app")) {
        include("renderer/**", "build/icon.png",
            "node_modules/maplibre-gl/dist/maplibre-gl.mjs", "node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs",
            "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "node_modules/maplibre-gl/dist/maplibre-gl.css",
            "node_modules/pmtiles/dist/esm/**", "node_modules/fflate/esm/browser.js", "node_modules/@protomaps/basemaps/dist/esm/**",
            "node_modules/maplibre-gl/LICENSE.txt", "node_modules/fflate/LICENSE")
        exclude("**/*.map")
        into("app")
    }
    from(File(root, "shared")) {
        include("geo/world.wtgeo", "map/world-z6.pmtiles", "map/fonts/**", "categories/domains.json", "threats/domains.txt", "threats/ips.txt")
        into("shared")
    }
}
// Build the Rust engine (android/engine) for phones (arm64) and the emulator (x86_64).
val buildEngine by tasks.registering(Exec::class) {
    val root = rootDir.parentFile
    workingDir = File(root, "android/engine")
    val home = System.getProperty("user.home")
    environment("ANDROID_NDK_HOME", File("$home/Android/Sdk/ndk").listFiles()!!.maxOf { it.path })
    environment("PATH", "$home/.cargo/bin:" + System.getenv("PATH"))
    commandLine("$home/.cargo/bin/cargo", "ndk", "-t", "arm64-v8a", "-t", "x86_64", "-o", File(projectDir, "src/main/jniLibs").path, "build", "--release")
}
tasks.named("preBuild") { dependsOn(copyShared, buildEngine) }
