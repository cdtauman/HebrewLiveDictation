#include "voice_type_tsf_protocol.h"

#include <algorithm>
#include <charconv>
#include <system_error>
#include <utility>

namespace voicetype::tsf {
namespace {

uint32_t ReadLe32(const char* data) noexcept {
    return static_cast<uint32_t>(static_cast<unsigned char>(data[0])) |
           (static_cast<uint32_t>(static_cast<unsigned char>(data[1])) << 8) |
           (static_cast<uint32_t>(static_cast<unsigned char>(data[2])) << 16) |
           (static_cast<uint32_t>(static_cast<unsigned char>(data[3])) << 24);
}

void WriteLe32(uint32_t value, std::string* output) {
    output->push_back(static_cast<char>(value & 0xFF));
    output->push_back(static_cast<char>((value >> 8) & 0xFF));
    output->push_back(static_cast<char>((value >> 16) & 0xFF));
    output->push_back(static_cast<char>((value >> 24) & 0xFF));
}

std::optional<size_t> FindJsonStringValueStart(std::string_view json, std::string_view key) {
    const std::string pattern = "\"" + std::string(key) + "\":";
    const size_t keyPos = json.find(pattern);
    if (keyPos == std::string_view::npos) {
        return std::nullopt;
    }
    size_t pos = keyPos + pattern.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
        ++pos;
    }
    if (pos >= json.size() || json[pos] != '"') {
        return std::nullopt;
    }
    return pos + 1;
}

bool AppendUtf8CodePoint(uint32_t codePoint, std::string* output) {
    if (codePoint <= 0x7F) {
        output->push_back(static_cast<char>(codePoint));
    } else if (codePoint <= 0x7FF) {
        output->push_back(static_cast<char>(0xC0 | (codePoint >> 6)));
        output->push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    } else if (codePoint <= 0xFFFF) {
        output->push_back(static_cast<char>(0xE0 | (codePoint >> 12)));
        output->push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
        output->push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    } else if (codePoint <= 0x10FFFF) {
        output->push_back(static_cast<char>(0xF0 | (codePoint >> 18)));
        output->push_back(static_cast<char>(0x80 | ((codePoint >> 12) & 0x3F)));
        output->push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
        output->push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    } else {
        return false;
    }
    return true;
}

bool ParseHex4(std::string_view text, uint32_t* value) {
    if (text.size() < 4) {
        return false;
    }
    uint32_t result = 0;
    for (size_t i = 0; i < 4; ++i) {
        const char ch = text[i];
        result <<= 4;
        if (ch >= '0' && ch <= '9') {
            result |= static_cast<uint32_t>(ch - '0');
        } else if (ch >= 'a' && ch <= 'f') {
            result |= static_cast<uint32_t>(10 + ch - 'a');
        } else if (ch >= 'A' && ch <= 'F') {
            result |= static_cast<uint32_t>(10 + ch - 'A');
        } else {
            return false;
        }
    }
    *value = result;
    return true;
}

}  // namespace

bool Utf8ToWideStrict(std::string_view input, std::wstring* output) noexcept {
    if (!output) {
        return false;
    }
    output->clear();
    if (input.empty()) {
        return true;
    }
    const int required = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        input.data(),
        static_cast<int>(input.size()),
        nullptr,
        0);
    if (required <= 0) {
        return false;
    }
    std::wstring value(static_cast<size_t>(required), L'\0');
    const int written = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        input.data(),
        static_cast<int>(input.size()),
        value.data(),
        required);
    if (written != required) {
        return false;
    }
    *output = std::move(value);
    return true;
}

bool WideToUtf8Strict(std::wstring_view input, std::string* output) noexcept {
    if (!output) {
        return false;
    }
    output->clear();
    if (input.empty()) {
        return true;
    }
    const int required = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        input.data(),
        static_cast<int>(input.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (required <= 0) {
        return false;
    }
    std::string value(static_cast<size_t>(required), '\0');
    const int written = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        input.data(),
        static_cast<int>(input.size()),
        value.data(),
        required,
        nullptr,
        nullptr);
    if (written != required) {
        return false;
    }
    *output = std::move(value);
    return true;
}

bool EncodeFrame(std::string_view json, std::string* frame) noexcept {
    if (!frame || json.size() > kMaxFrameBytes) {
        return false;
    }
    std::wstring ignored;
    if (!Utf8ToWideStrict(json, &ignored)) {
        return false;
    }
    frame->clear();
    frame->reserve(kFrameHeaderBytes + json.size());
    WriteLe32(static_cast<uint32_t>(json.size()), frame);
    frame->append(json.data(), json.size());
    return true;
}

DecodedFrame DecodeFrame(std::string_view frame) noexcept {
    if (frame.size() < kFrameHeaderBytes) {
        return {FrameStatus::Truncated, {}};
    }
    const uint32_t size = ReadLe32(frame.data());
    if (size > kMaxFrameBytes) {
        return {FrameStatus::TooLarge, {}};
    }
    const size_t payloadSize = frame.size() - kFrameHeaderBytes;
    if (payloadSize < size) {
        return {FrameStatus::Truncated, {}};
    }
    if (payloadSize > size) {
        return {FrameStatus::InvalidFrame, {}};
    }
    const std::string_view payload(frame.data() + kFrameHeaderBytes, size);
    std::wstring ignored;
    if (!Utf8ToWideStrict(payload, &ignored)) {
        return {FrameStatus::InvalidUtf8, {}};
    }
    return {FrameStatus::Ok, std::string(payload)};
}

bool TryGetJsonString(std::string_view json, std::string_view key, std::string* value) noexcept {
    if (!value) {
        return false;
    }
    value->clear();
    const auto start = FindJsonStringValueStart(json, key);
    if (!start) {
        return false;
    }

    for (size_t pos = *start; pos < json.size(); ++pos) {
        const char ch = json[pos];
        if (ch == '"') {
            std::wstring ignored;
            return Utf8ToWideStrict(*value, &ignored);
        }
        if (ch != '\\') {
            value->push_back(ch);
            continue;
        }
        if (++pos >= json.size()) {
            return false;
        }
        switch (json[pos]) {
            case '"':
            case '\\':
            case '/':
                value->push_back(json[pos]);
                break;
            case 'b':
                value->push_back('\b');
                break;
            case 'f':
                value->push_back('\f');
                break;
            case 'n':
                value->push_back('\n');
                break;
            case 'r':
                value->push_back('\r');
                break;
            case 't':
                value->push_back('\t');
                break;
            case 'u': {
                uint32_t codePoint = 0;
                if (!ParseHex4(json.substr(pos + 1), &codePoint)) {
                    return false;
                }
                pos += 4;
                if (!AppendUtf8CodePoint(codePoint, value)) {
                    return false;
                }
                break;
            }
            default:
                return false;
        }
    }
    return false;
}

bool TryGetJsonUInt64(std::string_view json, std::string_view key, uint64_t* value) noexcept {
    if (!value) {
        return false;
    }
    const std::string pattern = "\"" + std::string(key) + "\":";
    const size_t keyPos = json.find(pattern);
    if (keyPos == std::string_view::npos) {
        return false;
    }
    size_t pos = keyPos + pattern.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
        ++pos;
    }
    const char* begin = json.data() + pos;
    const char* end = json.data() + json.size();
    uint64_t parsed = 0;
    const auto result = std::from_chars(begin, end, parsed);
    if (result.ec != std::errc()) {
        return false;
    }
    if (result.ptr == begin) {
        return false;
    }
    if (result.ptr != end && *result.ptr != ',' && *result.ptr != '}' && *result.ptr != ' ' && *result.ptr != '\t') {
        return false;
    }
    *value = parsed;
    return true;
}

bool TryParseWireMessage(std::string_view json, WireMessage* message) noexcept {
    if (!message) {
        return false;
    }
    WireMessage parsed;
    if (!TryGetJsonString(json, "type", &parsed.type)) {
        return false;
    }
    TryGetJsonString(json, "session_id", &parsed.sessionId);
    TryGetJsonString(json, "nonce", &parsed.nonce);
    TryGetJsonUInt64(json, "generation", &parsed.generation);
    TryGetJsonUInt64(json, "seq", &parsed.seq);
    const bool hasSelectionStart = TryGetJsonUInt64(json, "selection_start_utf16", &parsed.selectionStartUtf16);
    const bool hasSelectionEnd = TryGetJsonUInt64(json, "selection_end_utf16", &parsed.selectionEndUtf16);
    parsed.hasSelection = hasSelectionStart && hasSelectionEnd;
    std::string textUtf8;
    if (TryGetJsonString(json, "text", &textUtf8) && !Utf8ToWideStrict(textUtf8, &parsed.text)) {
        return false;
    }
    std::string oldTextUtf8;
    if (TryGetJsonString(json, "old_text", &oldTextUtf8) && !Utf8ToWideStrict(oldTextUtf8, &parsed.oldText)) {
        return false;
    }
    std::string newTextUtf8;
    if (TryGetJsonString(json, "new_text", &newTextUtf8) && !Utf8ToWideStrict(newTextUtf8, &parsed.newText)) {
        return false;
    }
    TryGetJsonString(json, "unit", &parsed.unit);
    *message = std::move(parsed);
    return true;
}

bool SequenceGate::Accept(uint64_t generation, uint64_t seq) noexcept {
    if (!initialized_) {
        initialized_ = true;
        generation_ = generation;
        seq_ = seq;
        return true;
    }
    if (generation < generation_) {
        return false;
    }
    if (generation > generation_) {
        generation_ = generation;
        seq_ = seq;
        return true;
    }
    if (seq <= seq_) {
        return false;
    }
    seq_ = seq;
    return true;
}

MessageQueue::MessageQueue(size_t maxSize) noexcept : maxSize_(std::max<size_t>(1, maxSize)) {}

bool MessageQueue::Push(const WireMessage& message) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.size() >= maxSize_) {
        queue_.pop_front();
    }
    queue_.push_back(message);
    return true;
}

std::optional<WireMessage> MessageQueue::Pop() noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.empty()) {
        return std::nullopt;
    }
    WireMessage item = std::move(queue_.front());
    queue_.pop_front();
    return item;
}

size_t MessageQueue::Size() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
}

}  // namespace voicetype::tsf
