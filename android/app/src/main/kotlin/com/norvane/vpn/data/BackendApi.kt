package com.norvane.vpn.data

/** What the connection logic needs from the backend (an interface so tests can fake it). */
interface BackendApi {
    suspend fun connect(exclude: List<String>): ConnectResponse
    suspend fun success(serverId: String, connectionId: String)
    suspend fun failure(serverId: String, connectionId: String, reason: String)
    suspend fun disconnect(connectionId: String)
}

class ApiException(
    val status: Int,
    val code: String,
    message: String,
    val retryable: Boolean,
) : Exception(message) {
    /** Text safe to show users. Never includes profiles, ids or server addresses. */
    fun userMessage(): String = when (code) {
        "no_server_available", "inventory_unavailable" -> "No servers are available right now. Try again in a few minutes."
        "rate_limited" -> "Too many attempts. Please wait a moment and try again."
        "unauthorized" -> "This app build is not authorized by the service."
        "network" -> "Can't reach the service. Check your internet connection."
        "not_configured" -> "Backend address is not set in this build."
        else -> "The service had a problem. Please try again."
    }
}
