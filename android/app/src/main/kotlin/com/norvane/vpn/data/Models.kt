package com.norvane.vpn.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ConnectRequest(
    val protocol: String = "any",
    val exclude: List<String> = emptyList(),
)

@Serializable
data class ReportBody(
    @SerialName("connection_id") val connectionId: String,
    val reason: String? = null,
)

@Serializable
data class ServerInfo(
    val id: String,
    val hostname: String = "",
    val country: String = "",
    @SerialName("country_code") val countryCode: String = "XX",
    val transport: String = "udp",
    val port: Int = 0,
    @SerialName("verification_status") val verificationStatus: String = "candidate",
    @SerialName("latency_ms") val latencyMs: Double? = null,
    @SerialName("quality_score") val qualityScore: Double = 0.0,
)

@Serializable
data class ConnectResponse(
    @SerialName("connection_id") val connectionId: String,
    val server: ServerInfo,
    @SerialName("openvpn_profile") val openvpnProfile: String,
    val notice: String = "",
)

@Serializable
data class ErrorDetail(val code: String = "error", val message: String = "")

@Serializable
data class ErrorEnvelope(val error: ErrorDetail = ErrorDetail())
