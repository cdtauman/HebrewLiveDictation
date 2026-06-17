#pragma once

#include <Windows.h>

#include <cstdint>
#include <deque>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>

namespace voicetype::tsf {

constexpr uint32_t kMaxFrameBytes = 64 * 1024;
constexpr uint32_t kFrameHeaderBytes = 4;

enum class FrameStatus {
    Ok,
    Truncated,
    TooLarge,
    InvalidUtf8,
    InvalidJson,
    InvalidFrame,
};

struct DecodedFrame {
    FrameStatus status = FrameStatus::InvalidFrame;
    std::string json;
};

struct WireMessage {
    std::string type;
    std::string sessionId;
    std::string nonce;
    uint64_t generation = 0;
    uint64_t seq = 0;
    uint64_t selectionStartUtf16 = 0;
    uint64_t selectionEndUtf16 = 0;
    bool hasSelection = false;
    std::wstring text;
    std::wstring oldText;
    std::wstring newText;
    std::string unit;
};

bool Utf8ToWideStrict(std::string_view input, std::wstring* output) noexcept;
bool WideToUtf8Strict(std::wstring_view input, std::string* output) noexcept;
bool EncodeFrame(std::string_view json, std::string* frame) noexcept;
DecodedFrame DecodeFrame(std::string_view frame) noexcept;
bool TryParseWireMessage(std::string_view json, WireMessage* message) noexcept;
bool TryGetJsonString(std::string_view json, std::string_view key, std::string* value) noexcept;
bool TryGetJsonUInt64(std::string_view json, std::string_view key, uint64_t* value) noexcept;

class SequenceGate {
public:
    bool Accept(uint64_t generation, uint64_t seq) noexcept;

private:
    bool initialized_ = false;
    uint64_t generation_ = 0;
    uint64_t seq_ = 0;
};

class MessageQueue {
public:
    explicit MessageQueue(size_t maxSize = 64) noexcept;
    bool Push(const WireMessage& message) noexcept;
    std::optional<WireMessage> Pop() noexcept;
    size_t Size() const noexcept;

private:
    size_t maxSize_;
    mutable std::mutex mutex_;
    std::deque<WireMessage> queue_;
};

}  // namespace voicetype::tsf
