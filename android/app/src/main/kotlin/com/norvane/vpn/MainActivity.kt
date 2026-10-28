package com.norvane.vpn

import android.Manifest
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.norvane.vpn.ui.HomeScreen
import com.norvane.vpn.ui.NorvaneTheme
import kotlinx.coroutines.CompletableDeferred

class MainActivity : ComponentActivity() {

    private var pendingPermission: CompletableDeferred<Boolean>? = null

    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pendingPermission?.complete(r.resultCode == RESULT_OK)
        pendingPermission = null
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val manager = (application as NorvaneApp).manager
        manager.ensurePermission = { requestVpnPermission() }

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)

        setContent { NorvaneTheme { HomeScreen(manager) } }
    }

    private suspend fun requestVpnPermission(): Boolean {
        val intent = VpnService.prepare(this) ?: return true   // null => already granted
        val d = CompletableDeferred<Boolean>()
        pendingPermission = d
        vpnPermission.launch(intent)
        return d.await()
    }

    override fun onDestroy() {
        if (!isChangingConfigurations) {
            pendingPermission?.complete(false)
            pendingPermission = null
            (application as NorvaneApp).manager.ensurePermission = { false }
        }
        super.onDestroy()
    }
}
