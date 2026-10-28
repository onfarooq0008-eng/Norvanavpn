package com.norvane.vpn.vpn

import android.content.Context

object EngineFactory {
    fun create(context: Context): VpnEngine = IcsOpenVpnEngine(context.applicationContext)
}
