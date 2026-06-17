#pragma once

#include <Windows.h>

#include <atomic>
#include <memory>
#include <mutex>
#include <string>

#include "voice_type_tsf_protocol.h"

namespace voicetype::tsf {

enum class HelloStatus {
    NotStarted,
    Started,
    Connected,
    Cancelled,
    Timeout,
    InvalidArgument,
    PipeUnavailable,
    AccessDenied,
    IoError,
    ProtocolError,
};

struct HandshakeConfig {
    std::wstring pipeName;
    std::string sessionId;
    std::string nonce;
    DWORD timeoutMs = 100;
};

struct HandshakeResult {
    HelloStatus status = HelloStatus::NotStarted;
    DWORD win32Error = ERROR_SUCCESS;
};

const wchar_t* ToString(HelloStatus status) noexcept;
long ActiveWorkerCount() noexcept;

class HelloPeer final {
public:
    using MessageHandler = void (*)(const WireMessage& message, void* context) noexcept;

    struct State;

    HelloPeer() noexcept;
    ~HelloPeer() noexcept;

    HelloPeer(const HelloPeer&) = delete;
    HelloPeer& operator=(const HelloPeer&) = delete;

    bool StartAsync(const HandshakeConfig& config) noexcept;
    bool StartAsync(const HandshakeConfig& config, MessageHandler handler, void* handlerContext) noexcept;
    void Deactivate() noexcept;

    bool IsRunning() const noexcept;
    HandshakeResult LastResult() const noexcept;

    // Test/CLI helper only. TSF callbacks must not call this.
    bool WaitForCompletionForTest(DWORD timeoutMs) noexcept;

private:
    std::shared_ptr<State> state_;
    mutable std::mutex stateMutex_;
};

}  // namespace voicetype::tsf
