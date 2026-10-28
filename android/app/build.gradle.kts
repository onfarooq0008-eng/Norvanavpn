import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val backendUrl = (localProps.getProperty("BACKEND_BASE_URL") ?: "").trim().trimEnd('/')
val backendKey = (localProps.getProperty("BACKEND_API_KEY") ?: "").trim()
// Validate so nothing odd can be injected into generated source.
if (backendUrl.isNotEmpty() && !Regex("^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$").matches(backendUrl)) {
    throw GradleException("BACKEND_BASE_URL must look like https://host[:port] (https, no path)")
}
if (!Regex("^[A-Za-z0-9_-]{0,128}$").matches(backendKey)) {
    throw GradleException("BACKEND_API_KEY may only contain letters, digits, '_' and '-'")
}

// CI passes these; local builds fall back to defaults.
val ciVersionCode = (System.getenv("VERSION_CODE") ?: "1").also {
    require(Regex("^[0-9]{1,9}$").matches(it)) { "VERSION_CODE must be a number" }
}.toInt()
val ciVersionName = (System.getenv("VERSION_NAME") ?: "0.1.0").also {
    require(Regex("^[0-9A-Za-z._-]{1,40}$").matches(it)) { "VERSION_NAME has invalid characters" }
}

// Release signing comes ONLY from environment variables (never from files in the repo).
val keystorePath: String? = System.getenv("KEYSTORE_PATH")
val signingReady = !keystorePath.isNullOrBlank() && file(keystorePath).exists() &&
    listOf("KEYSTORE_PASSWORD", "KEY_ALIAS", "KEY_PASSWORD").all { !System.getenv(it).isNullOrBlank() }

val hasIcsEngine = rootProject.file("ics-openvpn/main").let {
    it.resolve("build.gradle").exists() || it.resolve("build.gradle.kts").exists()
}

android {
    namespace = "com.norvane.vpn"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.norvane.vpn"   // change before publishing if you rename the app
        minSdk = 26
        targetSdk = 35                      // Google Play raises this requirement yearly: bump before release
        versionCode = ciVersionCode
        versionName = ciVersionName
        buildConfigField("String", "BACKEND_BASE_URL", "\"$backendUrl\"")
        buildConfigField("String", "BACKEND_API_KEY", "\"$backendKey\"")
        // Only needed when the ics-openvpn module is present. Names come from that module's build.gradle;
        // verify them after adding the submodule.
        missingDimensionStrategy("implementation", "skeleton")
        missingDimensionStrategy("ovpnimpl", "ovpn23")
    }

    buildFeatures { compose = true; buildConfig = true }

    signingConfigs {
        if (signingReady) {
            create("release") {
                storeFile = file(keystorePath!!)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            if (signingReady) signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false   // enable + add keep rules only after the engine is verified working
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    sourceSets {
        getByName("main").java.srcDir(if (hasIcsEngine) "src/ics/kotlin" else "src/stub/kotlin")
    }
    packaging { resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}") }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    if (hasIcsEngine) implementation(project(":openvpn-main"))

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
}

// Refuse to produce a release artifact that is unsigned, has no backend, or has no VPN engine.
gradle.taskGraph.whenReady {
    val releaseRequested = allTasks.any { it.path == ":app:bundleRelease" || it.path == ":app:assembleRelease" }
    if (releaseRequested) {
        if (!signingReady) throw GradleException(
            "Release build needs signing: set KEYSTORE_PATH (existing file), KEYSTORE_PASSWORD, KEY_ALIAS, KEY_PASSWORD.")
        if (backendUrl.isEmpty()) throw GradleException(
            "Release build needs BACKEND_BASE_URL (local.properties or CI variable).")
        if (!hasIcsEngine) throw GradleException(
            "Release build needs the ics-openvpn engine (run android/scripts/setup-openvpn-engine.sh).")
    }
}
