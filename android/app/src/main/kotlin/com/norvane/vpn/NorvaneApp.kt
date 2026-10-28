package com.norvane.vpn

import android.app.Application
import com.norvane.vpn.data.ApiClient
import com.norvane.vpn.vpn.ConnectionManager
import com.norvane.vpn.vpn.EngineFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class NorvaneApp : Application() {
    lateinit var manager: ConnectionManager
        private set

    override fun onCreate() {
        super.onCreate()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        manager = ConnectionManager(
            api = ApiClient(BackendConfig.baseUrl, BackendConfig.apiKey),
            engine = EngineFactory.create(this),
            scope = scope,
        )
    }
}
