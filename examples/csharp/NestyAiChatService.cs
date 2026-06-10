using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Options;

namespace ExternalApp.Ai;

public interface INestyAiChatService
{
    Task<string> CompleteAsync(string userMessage, CancellationToken cancellationToken = default);
}

public sealed class NestyAiChatService : INestyAiChatService
{
    private readonly HttpClient _httpClient;
    private readonly NestyAiOptions _options;

    public NestyAiChatService(HttpClient httpClient, IOptions<NestyAiOptions> options)
    {
        _httpClient = httpClient;
        _options = options.Value;
    }

    public async Task<string> CompleteAsync(string userMessage, CancellationToken cancellationToken = default)
    {
        var request = new ChatCompletionRequest
        {
            Model = _options.DefaultModel,
            Messages =
            [
                new ChatMessage { Role = "system", Content = "You are an AI assistant inside an external app." },
                new ChatMessage { Role = "user", Content = userMessage },
            ],
            Stream = false,
        };

        using var httpRequest = new HttpRequestMessage(HttpMethod.Post, "chat/completions")
        {
            Content = JsonContent.Create(request),
        };
        httpRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _options.ApiKey);

        using var response = await _httpClient.SendAsync(httpRequest, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        var requestId = response.Headers.TryGetValues("X-Request-ID", out var values)
            ? values.FirstOrDefault()
            : null;

        if (!response.IsSuccessStatusCode)
        {
            var error = JsonSerializer.Deserialize<GatewayErrorEnvelope>(body);
            throw new NestyAiGatewayException(
                statusCode: (int)response.StatusCode,
                errorCode: error?.Error?.Code,
                errorType: error?.Error?.Type,
                message: error?.Error?.Message ?? "NestyAI Gateway request failed.",
                requestId: requestId);
        }

        var completion = JsonSerializer.Deserialize<ChatCompletionResponse>(body);
        return completion?.Choices?.FirstOrDefault()?.Message?.Content
            ?? throw new InvalidOperationException("Unexpected Gateway response shape.");
    }
}

public sealed class NestyAiGatewayException : Exception
{
    public int StatusCode { get; }
    public string? ErrorCode { get; }
    public string? ErrorType { get; }
    public string? RequestId { get; }

    public NestyAiGatewayException(
        int statusCode,
        string? errorCode,
        string? errorType,
        string message,
        string? requestId)
        : base(FormatMessage(statusCode, errorCode, errorType, message, requestId))
    {
        StatusCode = statusCode;
        ErrorCode = errorCode;
        ErrorType = errorType;
        RequestId = requestId;
    }

    private static string FormatMessage(
        int statusCode,
        string? errorCode,
        string? errorType,
        string message,
        string? requestId)
    {
        var parts = new List<string> { $"HTTP {statusCode}" };
        if (!string.IsNullOrWhiteSpace(errorCode))
        {
            parts.Add($"code={errorCode}");
        }
        if (!string.IsNullOrWhiteSpace(errorType))
        {
            parts.Add($"type={errorType}");
        }
        if (!string.IsNullOrWhiteSpace(requestId))
        {
            parts.Add($"request_id={requestId}");
        }
        parts.Add(message);
        return string.Join("; ", parts);
    }
}

public sealed class NestyAiOptions
{
    public const string SectionName = "NestyAI";
    /// <summary>OpenAI-compatible base URL, e.g. https://gateway.example.com/v1</summary>
    public string BaseUrl { get; set; } = "";
    public string ApiKey { get; set; } = "";
    public string DefaultModel { get; set; } = "nesty-combined-1.0";
}

internal sealed class ChatCompletionRequest
{
    [JsonPropertyName("model")]
    public string Model { get; set; } = "";

    [JsonPropertyName("messages")]
    public List<ChatMessage> Messages { get; set; } = [];

    [JsonPropertyName("stream")]
    public bool Stream { get; set; }
}

internal sealed class ChatMessage
{
    [JsonPropertyName("role")]
    public string Role { get; set; } = "";

    [JsonPropertyName("content")]
    public string Content { get; set; } = "";
}

internal sealed class ChatCompletionResponse
{
    [JsonPropertyName("choices")]
    public List<ChatChoice>? Choices { get; set; }
}

internal sealed class ChatChoice
{
    [JsonPropertyName("message")]
    public ChatMessage? Message { get; set; }
}

internal sealed class GatewayErrorEnvelope
{
    [JsonPropertyName("error")]
    public GatewayError? Error { get; set; }
}

internal sealed class GatewayError
{
    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("type")]
    public string? Type { get; set; }

    [JsonPropertyName("code")]
    public string? Code { get; set; }

    [JsonPropertyName("param")]
    public string? Param { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

// Server-side only. Never log ApiKey. Streaming is not implemented in this example.
//
// Program.cs registration example:
//
// builder.Services.Configure<NestyAiOptions>(
//     builder.Configuration.GetSection(NestyAiOptions.SectionName));
// builder.Services.AddHttpClient<INestyAiChatService, NestyAiChatService>((sp, client) =>
// {
//     var options = sp.GetRequiredService<IOptions<NestyAiOptions>>().Value;
//     // BaseUrl must include /v1, e.g. https://gateway.example.com/v1
//     client.BaseAddress = new Uri(options.BaseUrl.TrimEnd('/') + "/");
//     client.Timeout = TimeSpan.FromSeconds(60);
// });
