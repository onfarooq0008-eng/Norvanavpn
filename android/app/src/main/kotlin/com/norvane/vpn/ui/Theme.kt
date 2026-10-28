package com.norvane.vpn.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Bg = Color(0xFF0B1220)
val Surface = Color(0xFF131C2E)
val Accent = Color(0xFF2DD4BF)
val Warn = Color(0xFFF59E0B)
val Danger = Color(0xFFF87171)
val TextDim = Color(0xFF94A3B8)

@Composable
fun NorvaneTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent, background = Bg, surface = Surface, onSurface = Color(0xFFE2E8F0),
            onBackground = Color(0xFFE2E8F0), error = Danger,
        ),
        content = content,
    )
}
