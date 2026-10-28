package com.norvane.vpn.vpn

// UNVERIFIED against the real library: written from memory of the ics-openvpn API and never compiled.
// Class and method names below (ConfigParser, ProfileManager.setTemporaryProfile, VPNLaunchHelper,
// VpnStatus.StateListener, IOpenVPNServiceInternal) may differ in the revision you pin. Fix compile
// errors against ics-openvpn/main/src/main/java/de/blinkt/openvpn/. Licensing: GPL-2.0 (see README).

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import de.blinkt.openvpn.core.ConfigParser
import de.blinkt.openvpn.core.ConnectionStatus
import de.blinkt.openvpn.core.IOpenVPNServiceInternal
import de.blinkt.openvpn.core.OpenVPNService
import de.blinkt.openvpn.core.ProfileManager
import de.blinkt.openvpn.core.VPNLaunchHelper
import de.blinkt.openvpn.core.VpnStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.StringReader

class IcsOpenVpnEngine(private val app: Context) : VpnEngine, VpnStatus.StateListener {

    override val available = true
    private val _state = MutableStateFlow<EngineState>(EngineState.Idle)
    override val state: StateFlow<EngineState> = _state.asStateFlow()

    @Volatile private var userStopped = false

    init { VpnStatus.addStateListener(this) }

    override fun start(profile: String) {
        userStopped = false
        _state.value = EngineState.Connecting
        try {
            val parser = ConfigParser()
            parser.parseConfig(StringReader(profile))
            val vp = parser.convertProfile()
            vp.mName = "Norvane"
            // Temporary profile: not written to the saved-profile list.
            ProfileManager.setTemporaryProfile(app, vp)
            VPNLaunchHelper.startOpenVpn(vp, app, "Norvane", true)
        } catch (e: Exception) {
            _state.value = EngineState.Failed(FailureReason.OTHER)   // never log the profile or exception text
        }
    }

    override fun stop() {
        userStopped = true
        val intent = Intent(app, OpenVPNService::class.java).apply { action = OpenVPNService.START_SERVICE }
        val conn = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
                try { IOpenVPNServiceInternal.Stub.asInterface(binder).stopVPN(false) } catch (_: Exception) {}
                app.unbindService(this)
            }
            override fun onServiceDisconnected(name: ComponentName?) {}
        }
        if (!app.bindService(intent, conn, Context.BIND_AUTO_CREATE)) { /* service not running */ }
        ProfileManager.setConntectedVpnProfileDisconnected(app)
        _state.value = EngineState.Idle
    }

    // --- VpnStatus.StateListener -----------------------------------------------------------
    override fun updateState(
        state: String?, logmessage: String?, localizedResId: Int, level: ConnectionStatus?, intent: Intent?,
    ) {
        if (userStopped) return
        _state.value = when (level) {
            ConnectionStatus.LEVEL_CONNECTED -> EngineState.Connected
            ConnectionStatus.LEVEL_AUTH_FAILED -> EngineState.Failed(FailureReason.AUTH)
            ConnectionStatus.LEVEL_WAITING_FOR_USER_INPUT -> EngineState.Failed(FailureReason.AUTH) // profile wants credentials
            ConnectionStatus.LEVEL_NONETWORK -> EngineState.Failed(FailureReason.NO_NETWORK)
            // The library can emit stale NOTCONNECTED/NOPROCESS right after launch: only treat it as a
            // failure when the process is exiting or a live tunnel dropped. Verify on a real device.
            ConnectionStatus.LEVEL_NOTCONNECTED ->
                when {
                    _state.value is EngineState.Idle -> EngineState.Idle
                    _state.value is EngineState.Connected || state == "EXITING" ->
                        EngineState.Failed(if (state?.contains("TLS", ignoreCase = true) == true) FailureReason.TLS else FailureReason.OTHER)
                    else -> _state.value
                }
            ConnectionStatus.LEVEL_VPNPAUSED, null -> _state.value
            else -> if (_state.value is EngineState.Connected) _state.value else EngineState.Connecting
        }
    }

    override fun setConnectedVPN(uuid: String?) {}
}
