// Practical Kotlin/Android reference using OkHttp for NestyAI stream=true SSE.
// This is a copyable snippet, not a full Android project file.
//
// Dependencies (Gradle):
// implementation("com.squareup.okhttp3:okhttp:4.12.0")
//
// Never hardcode production API keys in source code.

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.BufferedReader

fun streamChatFromNestyAi(
    baseUrl: String,
    apiKey: String,
    model: String = "nesty-combined-1.0"
) {
    val client = OkHttpClient()
    val jsonBody = """
        {
          "model": "$model",
          "messages": [{"role":"user","content":"Write a short intro about NestyAI."}],
          "stream": true,
          "search": "off",
          "tools": "off"
        }
    """.trimIndent()

    val request = Request.Builder()
        .url("${baseUrl.trimEnd('/')}/v1/chat/completions")
        .addHeader("Content-Type", "application/json")
        .addHeader("Authorization", "Bearer $apiKey")
        .post(jsonBody.toRequestBody("application/json".toMediaType()))
        .build()

    client.newCall(request).execute().use { response ->
        if (!response.isSuccessful) {
            val errText = response.body?.string().orEmpty()
            println("HTTP ${response.code} error: $errText")
            return
        }

        val body = response.body ?: run {
            println("Empty streaming body")
            return
        }

        BufferedReader(body.charStream()).use { reader ->
            var line: String?
            while (true) {
                line = reader.readLine() ?: break
                if (!line!!.startsWith("data: ")) continue

                val payload = line!!.removePrefix("data: ").trim()
                if (payload == "[DONE]") {
                    println("\n[STREAM DONE]")
                    break
                }

                try {
                    val event = JSONObject(payload)
                    when (event.optString("object")) {
                        "chat.completion.chunk" -> {
                            val choices = event.optJSONArray("choices")
                            val delta = choices
                                ?.optJSONObject(0)
                                ?.optJSONObject("delta")
                            val content = delta?.optString("content", "") ?: ""
                            if (content.isNotEmpty()) {
                                print(content)
                            }
                        }
                        "chat.completion.metadata" -> {
                            println("\n[METADATA] $event")
                        }
                        "chat.completion.error" -> {
                            println("\n[STREAM ERROR] ${event.optJSONObject("error")}")
                        }
                    }
                } catch (_: Exception) {
                    // Ignore malformed lines and continue parsing SSE stream.
                }
            }
        }
    }
}
