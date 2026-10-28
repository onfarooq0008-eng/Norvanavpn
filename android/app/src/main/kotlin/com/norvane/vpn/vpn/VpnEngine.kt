package com.norvane.vpn.vpn

import kotlinx.coroutines.flow.StateFlow

enum class FailureReason(val apiValue: String) {
    TIMEOUT("timeout"), AUTH("auth"), TLS("tls"), NO_NETWORK("network"),
    ENGINE_UNAVAILABLE("other"), OTHER("other"),
}

sealed interface EngineState {
    data object Idle : EngineState
    data object Connecting : EngineState
    /** Only emitted when the OpenVPN client itself reports an established tunnel. */
    data object Connected : EngineState
    data class Failed(val reason: FailureReason) : EngineState
}

interface VpnEngine {
    /** False when the OpenVPN library is not bundled in this build. */
    val available: Boolean
    val state: StateFlow<EngineState>

    /** Must set state to Connecting before returning (so stale results are never observed). */
    fun start(profile: String)
    fun stop()
}
