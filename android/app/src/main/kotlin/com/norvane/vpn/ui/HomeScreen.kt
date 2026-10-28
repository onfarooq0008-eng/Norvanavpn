package com.norvane.vpn.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.Image
import com.norvane.vpn.BackendConfig
import com.norvane.vpn.R
import com.norvane.vpn.data.ServerInfo
import com.norvane.vpn.vpn.ConnectionManager
import com.norvane.vpn.vpn.UiState
import kotlinx.coroutines.delay

@Composable
fun HomeScreen(manager: ConnectionManager) {
    val ui by manager.ui.collectAsState()
    val notice by manager.notice.collectAsState()
    var showInfo by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().background(Bg).safeDrawingPadding().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("Norvane", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            TextButton(onClick = { showInfo = true }) { Text("About", color = TextDim) }
        }

        Spacer(Modifier.weight(1f))
        PowerButton(ui, enabled = BackendConfig.isConfigured, onClick = manager::toggle)
        Spacer(Modifier.height(28.dp))
        StatusText(ui)
        Spacer(Modifier.height(20.dp))
        when (val s = ui) {
            is UiState.Connecting -> ServerCard(s.server, null)
            is UiState.Connected -> ServerCard(s.server, s.sinceMs)
            else -> Unit
        }
        if (!BackendConfig.isConfigured) {
            Spacer(Modifier.height(16.dp))
            Text(
                "Backend not set. Add BACKEND_BASE_URL to local.properties and rebuild.",
                color = Warn, fontSize = 13.sp, textAlign = TextAlign.Center,
            )
        }
        Spacer(Modifier.weight(1f))
        Text(
            "Public relays are run by volunteers. Not for anonymity.",
            color = TextDim, fontSize = 12.sp, textAlign = TextAlign.Center,
        )
    }

    if (showInfo) {
        AlertDialog(
            onDismissRequest = { showInfo = false },
            confirmButton = { TextButton(onClick = { showInfo = false }) { Text("OK") } },
            title = { Text("About Norvane") },
            text = {
                Text(
                    (if (notice.isNotEmpty()) notice + "\n\n" else "Public relays are run by volunteers. Operators may be able to observe " +
                        "connection metadata and any traffic that is not itself encrypted (use HTTPS). Do not rely on this for anonymity.\n\n") +
                        "Servers are chosen by a backend that checks them periodically. A server marked \"checked\" answered a test " +
                        "recently; it is not a guarantee that it will work or be fast.",
                    fontSize = 14.sp,
                )
            },
        )
    }
}

@Composable
private fun PowerButton(ui: UiState, enabled: Boolean, onClick: () -> Unit) {
    val busy = ui is UiState.Requesting || ui is UiState.Connecting || ui is UiState.Disconnecting
    val ring = when (ui) {
        is UiState.Connected -> Accent
        is UiState.Error -> Danger
        else -> if (busy) Warn else Color(0xFF334155)
    }
    val pulse by rememberInfiniteTransition(label = "pulse").animateFloat(
        initialValue = 0.35f, targetValue = 1f, label = "alpha",
        animationSpec = infiniteRepeatable(tween(800), RepeatMode.Reverse),
    )
    Box(
        Modifier.size(210.dp).clip(CircleShape).background(ring.copy(alpha = if (busy) 0.12f * pulse else 0.12f))
            .padding(14.dp).clip(CircleShape).background(Surface)
            .clickable(enabled = enabled, role = Role.Button, onClickLabel = "Connect or disconnect", onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Image(
            painterResource(R.drawable.ic_power), contentDescription = null, modifier = Modifier.size(72.dp).alpha(if (enabled) 1f else 0.3f),
            colorFilter = ColorFilter.tint(ring),
        )
    }
}

@Composable
private fun StatusText(ui: UiState) {
    val (title, sub, color) = when (ui) {
        is UiState.Idle -> Triple("Not connected", "Tap to connect", Color.White)
        is UiState.Requesting -> Triple("Finding a server…", "", Warn)
        is UiState.Connecting -> Triple("Connecting…", if (ui.attempt > 1) "Attempt ${ui.attempt}" else "", Warn)
        is UiState.Connected -> Triple("Connected", "", Accent)
        is UiState.Disconnecting -> Triple("Disconnecting…", "", Warn)
        is UiState.Error -> Triple("Not connected", ui.message, Danger)
    }
    Text(title, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, color = color)
    if (sub.isNotEmpty()) Text(sub, color = if (ui is UiState.Error) Danger else TextDim, fontSize = 14.sp, textAlign = TextAlign.Center,
        modifier = Modifier.padding(top = 6.dp))
}

@Composable
private fun ServerCard(server: ServerInfo, sinceMs: Long?) {
    var elapsed by remember { mutableLongStateOf(0L) }
    if (sinceMs != null) LaunchedEffect(sinceMs) {
        while (true) { elapsed = (System.currentTimeMillis() - sinceMs) / 1000; delay(1000) }
    }
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Surface).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text("${flag(server.countryCode)}  ${server.country.ifEmpty { server.countryCode }}", fontSize = 18.sp, color = Color.White)
        val ping = server.latencyMs?.let { " · ${it.toInt()} ms" }.orEmpty()
        Text("${server.transport.uppercase()}$ping", color = TextDim, fontSize = 13.sp)
        Text(statusLabel(server.verificationStatus), color = TextDim, fontSize = 13.sp)
        if (sinceMs != null) Text(formatElapsed(elapsed), color = Accent, fontSize = 20.sp, fontWeight = FontWeight.Medium)
    }
}

internal fun statusLabel(status: String) = when (status) {
    "vpn_verified" -> "Manually verified"
    "reachable" -> "Checked recently (answered a test)"
    else -> "Not checked recently"
}

internal fun formatElapsed(totalSeconds: Long): String {
    val h = totalSeconds / 3600; val m = (totalSeconds % 3600) / 60; val s = totalSeconds % 60
    return "%02d:%02d:%02d".format(h, m, s)
}

internal fun flag(cc: String): String {
    if (cc.length != 2 || !cc.all { it in 'A'..'Z' }) return "🌐"
    return cc.map { String(Character.toChars(0x1F1E6 + (it - 'A'))) }.joinToString("")
}
