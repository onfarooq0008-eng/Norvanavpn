package com.norvane.vpn.vpn

import com.norvane.vpn.data.ApiException
import com.norvane.vpn.data.BackendApi
import com.norvane.vpn.data.ConnectResponse
import com.norvane.vpn.data.ServerInfo
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

sealed interface UiState {
    data object Idle : UiState
    data object Requesting : UiState
    data class Connecting(val server: ServerInfo, val attempt: Int) : UiState
    /** Shown ONLY after the OpenVPN client reported an established tunnel, never on an HTTP 200. */
    data class Connected(val server: ServerInfo, val sinceMs: Long) : UiState
    data object Disconnecting : UiState
    data class Error(val message: String) : UiState
}

class ConnectionManager(
    private val api: BackendApi,
    private val engine: VpnEngine,
    private val scope: CoroutineScope,
    private val maxAttempts: Int = 3,
    private val connectTimeoutMs: Long = 45_000,
    private val backoffBaseMs: Long = 1_000,
    private val now: () -> Long = System::currentTimeMillis,
) {
    /** Set by the Activity: shows the system VPN consent dialog if needed. Returns true when granted. */
    @Volatile var ensurePermission: suspend () -> Boolean = { true }

    private val _ui = MutableStateFlow<UiState>(UiState.Idle)
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    private val _notice = MutableStateFlow("")
    val notice: StateFlow<String> = _notice.asStateFlow()

    private var job: Job? = null
    private var watcher: Job? = null
    @Volatile private var activeConnectionId: String? = null

    fun toggle() = when (_ui.value) {
        is UiState.Idle, is UiState.Error -> connect()
        is UiState.Disconnecting -> Unit
        else -> disconnect()
    }

    fun connect() {
        if (job?.isActive == true) return
        job = scope.launch { runConnect() }
    }

    fun disconnect() {
        if (_ui.value is UiState.Idle || _ui.value is UiState.Disconnecting) return
        watcher?.cancel()
        job?.cancel()
        scope.launch {
            _ui.value = UiState.Disconnecting
            engine.stop()
            activeConnectionId?.let { id -> runCatching { api.disconnect(id) } }
            activeConnectionId = null
            _ui.value = UiState.Idle
        }
    }

    private suspend fun runConnect() {
        _ui.value = UiState.Requesting
        val failedIds = mutableListOf<String>()
        var lastError = "Could not connect. Please try again."
        var attempt = 0
        while (attempt < maxAttempts) {
            attempt++
            var issued: ConnectResponse? = null   // set while a connection id is issued but not yet reported
            try {
                val resp = api.connect(failedIds.toList())
                issued = resp
                if (resp.notice.isNotEmpty()) _notice.value = resp.notice

                if (!engine.available) {
                    reportAndClear(resp, "other")
                    _ui.value = UiState.Error("The VPN engine is not installed in this build.")
                    return
                }
                if (!ensurePermission()) {
                    reportAndClear(resp, "cancelled")
                    _ui.value = UiState.Error("VPN permission is required to connect.")
                    return
                }
                _ui.value = UiState.Connecting(resp.server, attempt)
                engine.stop()
                engine.start(resp.openvpnProfile)

                val outcome = withTimeoutOrNull(connectTimeoutMs) {
                    engine.state.first { it is EngineState.Connected || it is EngineState.Failed }
                }
                if (outcome is EngineState.Connected) {
                    activeConnectionId = resp.connectionId
                    issued = null
                    _ui.value = UiState.Connected(resp.server, now())
                    runCatching { api.success(resp.server.id, resp.connectionId) }
                    watchConnection()
                    return
                }
                val reason = (outcome as? EngineState.Failed)?.reason ?: FailureReason.TIMEOUT
                engine.stop()
                runCatching { api.failure(resp.server.id, resp.connectionId, reason.apiValue) }
                issued = null
                failedIds += resp.server.id
                lastError = "Could not reach that server. " + if (attempt < maxAttempts) "Trying another…" else "Please try again."
            } catch (e: CancellationException) {
                withContext(NonCancellable) {
                    issued?.let { runCatching { api.failure(it.server.id, it.connectionId, "cancelled") } }
                    engine.stop()
                }
                throw e
            } catch (e: ApiException) {
                lastError = e.userMessage()
                if (!e.retryable) break
            }
            if (attempt < maxAttempts) delay(backoffBaseMs shl (attempt - 1))   // 1 s, 2 s
        }
        _ui.value = UiState.Error(lastError)
    }

    private suspend fun reportAndClear(resp: ConnectResponse, reason: String) {
        runCatching { api.failure(resp.server.id, resp.connectionId, reason) }
    }

    private fun watchConnection() {
        watcher?.cancel()
        watcher = scope.launch {
            engine.state.first { it !is EngineState.Connected }
            if (_ui.value is UiState.Connected) {
                val id = activeConnectionId
                engine.stop()
                id?.let { runCatching { api.disconnect(it) } }
                activeConnectionId = null
                _ui.value = UiState.Error("Connection lost.")   // deliberately no silent auto-reconnect
            }
        }
    }
}
