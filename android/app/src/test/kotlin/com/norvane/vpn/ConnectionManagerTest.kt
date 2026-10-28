package com.norvane.vpn

import com.norvane.vpn.data.ApiException
import com.norvane.vpn.data.BackendApi
import com.norvane.vpn.data.ConnectResponse
import com.norvane.vpn.data.ServerInfo
import com.norvane.vpn.vpn.ConnectionManager
import com.norvane.vpn.vpn.EngineState
import com.norvane.vpn.vpn.FailureReason
import com.norvane.vpn.vpn.UiState
import com.norvane.vpn.vpn.VpnEngine
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeApi(val noServers: Boolean = false) : BackendApi {
    val connectExcludes = mutableListOf<List<String>>()
    val failures = mutableListOf<Pair<String, String>>()   // serverId to reason
    val successes = mutableListOf<String>()
    var disconnects = 0
    private var n = 0
    override suspend fun connect(exclude: List<String>): ConnectResponse {
        if (noServers) throw ApiException(503, "no_server_available", "none", true)
        connectExcludes += exclude
        n++
        return ConnectResponse("conn-$n", ServerInfo(id = "srv$n", country = "Japan", countryCode = "JP"), "client\n")
    }
    override suspend fun success(serverId: String, connectionId: String) { successes += serverId }
    override suspend fun failure(serverId: String, connectionId: String, reason: String) { failures += serverId to reason }
    override suspend fun disconnect(connectionId: String) { disconnects++ }
}

/** outcomes[i] is what the i-th start() produces after 100 ms; null means "never answers". */
private class FakeEngine(private val scope: CoroutineScope, private val outcomes: List<EngineState?>) : VpnEngine {
    override val available = true
    private val _state = MutableStateFlow<EngineState>(EngineState.Idle)
    override val state: StateFlow<EngineState> = _state
    var starts = 0
    var stops = 0
    override fun start(profile: String) {
        _state.value = EngineState.Connecting
        val next = outcomes.getOrNull(starts++)
        if (next != null) scope.launch { delay(100); _state.value = next }
    }
    override fun stop() { stops++; _state.value = EngineState.Idle }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ConnectionManagerTest {

    @Test fun `connected only after engine reports connected, then success is reported`() = runTest {
        val api = FakeApi(); val engine = FakeEngine(backgroundScope, listOf(EngineState.Connected))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); runCurrent()
        assertTrue(m.ui.value is UiState.Connecting)           // HTTP 200 alone is NOT "connected"
        advanceTimeBy(150); runCurrent()
        assertTrue(m.ui.value is UiState.Connected)
        assertEquals(listOf("srv1"), api.successes)
    }

    @Test fun `failed server is reported and the next attempt excludes it`() = runTest {
        val api = FakeApi()
        val engine = FakeEngine(backgroundScope, listOf(EngineState.Failed(FailureReason.TLS), EngineState.Connected))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); advanceUntilIdle()
        assertEquals(listOf("srv1" to "tls"), api.failures)
        assertEquals(listOf(emptyList<String>(), listOf("srv1")), api.connectExcludes)
        assertTrue(m.ui.value is UiState.Connected)
    }

    @Test fun `silent engine times out, three servers tried, then error`() = runTest {
        val api = FakeApi(); val engine = FakeEngine(backgroundScope, listOf(null, null, null))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); advanceUntilIdle()
        assertEquals(3, api.failures.size)
        assertTrue(api.failures.all { it.second == "timeout" })
        assertTrue(m.ui.value is UiState.Error)
        assertEquals(3, engine.starts)                          // never loops beyond maxAttempts
    }

    @Test fun `disconnect during connecting reports cancelled and ends idle`() = runTest {
        val api = FakeApi(); val engine = FakeEngine(backgroundScope, listOf(null))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); advanceTimeBy(1_000); runCurrent()
        m.disconnect(); advanceUntilIdle()
        assertEquals(listOf("srv1" to "cancelled"), api.failures)
        assertTrue(m.ui.value is UiState.Idle)
    }

    @Test fun `no servers gives a friendly error without starting the engine`() = runTest {
        val api = FakeApi(noServers = true); val engine = FakeEngine(backgroundScope, emptyList())
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); advanceUntilIdle()
        val ui = m.ui.value
        assertTrue(ui is UiState.Error && ui.message.contains("No servers"))
        assertEquals(0, engine.starts)
    }

    @Test fun `denied vpn permission does not start the engine and releases the connection`() = runTest {
        val api = FakeApi(); val engine = FakeEngine(backgroundScope, listOf(EngineState.Connected))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.ensurePermission = { false }
        m.connect(); advanceUntilIdle()
        assertEquals(0, engine.starts)
        assertEquals(listOf("srv1" to "cancelled"), api.failures)
        assertTrue(m.ui.value is UiState.Error)
    }

    @Test fun `lost tunnel after connected shows error and tells backend`() = runTest {
        val api = FakeApi(); val engine = FakeEngine(backgroundScope, listOf(EngineState.Connected))
        val m = ConnectionManager(api, engine, backgroundScope)
        m.connect(); advanceUntilIdle()
        assertTrue(m.ui.value is UiState.Connected)
        engine.stop(); advanceUntilIdle()                        // simulates tunnel dropping
        assertTrue(m.ui.value is UiState.Error)
        assertEquals(1, api.disconnects)
    }
}
