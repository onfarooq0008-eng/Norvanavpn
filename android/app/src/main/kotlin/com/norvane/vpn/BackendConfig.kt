package com.norvane.vpn

/** Backend location comes from local.properties at build time (see README). */
object BackendConfig {
    val baseUrl: String = BuildConfig.BACKEND_BASE_URL
    val apiKey: String = BuildConfig.BACKEND_API_KEY
    val isConfigured: Boolean get() = baseUrl.startsWith("https://")
}
