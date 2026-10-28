package com.norvane.vpn.vpn

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Used when the ics-openvpn module is NOT present. It never pretends to connect. */
class StubEngine : VpnEngine {
    override val available = false
    private val _state = MutableStateFlow<EngineState>(EngineState.Idle)
    override val state: StateFlow<EngineState> = _state.asStateFlow()
    override fun start(profile: String) { _state.value = EngineState.Failed(FailureReason.ENGINE_UNAVAILABLE) }
    override fun stop() { _state.value = EngineState.Idle }
}

object EngineFactory {
    fun create(@Suppress("UNUSED_PARAMETER") context: Context): VpnEngine = StubEngine()
}
