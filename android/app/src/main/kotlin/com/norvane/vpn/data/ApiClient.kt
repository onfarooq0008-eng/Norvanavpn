package com.norvane.vpn.data

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

@OptIn(ExperimentalSerializationApi::class)
class ApiClient(
    private val baseUrl: String,
    private val apiKey: String,
    private val http: OkHttpClient = defaultHttp(),
) : BackendApi {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false }  // omit null 'reason': backend rejects unknown fields
    private val jsonType = "application/json; charset=utf-8".toMediaType()

    override suspend fun connect(exclude: List<String>): ConnectResponse {
        val body = json.encodeToString(ConnectRequest(exclude = exclude.take(10)))
        return json.decodeFromString(post("/api/v1/connect", body))
    }

    override suspend fun success(serverId: String, connectionId: String) {
        post("/api/v1/servers/$serverId/success", json.encodeToString(ReportBody(connectionId)))
    }

    override suspend fun failure(serverId: String, connectionId: String, reason: String) {
        post("/api/v1/servers/$serverId/failure", json.encodeToString(ReportBody(connectionId, reason)))
    }

    override suspend fun disconnect(connectionId: String) {
        post("/api/v1/disconnect", json.encodeToString(ReportBody(connectionId)))
    }

    private suspend fun post(path: String, body: String): String {
        if (!baseUrl.startsWith("https://")) throw ApiException(0, "not_configured", "no https backend", false)
        val req = Request.Builder()
            .url(baseUrl + path)
            .post(body.toRequestBody(jsonType))
            .header("Accept", "application/json")
            .apply { if (apiKey.isNotEmpty()) header("X-API-Key", apiKey) }
            .build()
        val resp = http.newCall(req).await()
        resp.use {
            val text = it.body?.string().orEmpty()
            if (it.isSuccessful) return text
            val err = runCatching { json.decodeFromString<ErrorEnvelope>(text).error }.getOrNull()
            val code = err?.code ?: "http_${it.code}"
            // 5xx / 429 / 503 are worth another attempt; 4xx client errors are not.
            val retryable = it.code == 429 || it.code >= 500
            throw ApiException(it.code, code, "HTTP ${it.code}", retryable)
        }
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (!cont.isCancelled) cont.resumeWithException(ApiException(0, "network", "network error", true))
            }
            override fun onResponse(call: Call, response: Response) {
                if (cont.isCancelled) response.close() else cont.resume(response)
            }
        })
        cont.invokeOnCancellation { cancel() }
    }

    companion object {
        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .callTimeout(15, TimeUnit.SECONDS)
            .followRedirects(false)       // the API never redirects; never follow one to another host
            .retryOnConnectionFailure(true)
            .build()
    }
}
