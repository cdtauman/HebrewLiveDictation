#include "voice_type_tsf_hello_peer.h"
#include "voice_type_tsf_protocol.h"

#include <algorithm>
#include <chrono>
#include <sstream>
#include <thread>
#include <utility>

namespace voicetype::tsf {
namespace {

constexpr DWORD kMinTimeoutMs = 50;
constexpr DWORD kMaxTimeoutMs = 150;
constexpr DWORD kPollMs = 5;

std::atomic<long> g_activeWorkers{0};

DWORD ClampTimeout(DWORD timeoutMs) noexcept {
    return std::min(kMaxTimeoutMs, std::max(kMinTimeoutMs, timeoutMs));
}

class UniqueHandle {
public:
    UniqueHandle() noexcept = default;
    explicit UniqueHandle(HANDLE handle) noexcept : handle_(handle) {}
    ~UniqueHandle() noexcept { reset(); }

    UniqueHandle(const UniqueHandle&) = delete;
    UniqueHandle& operator=(const UniqueHandle&) = delete;

    UniqueHandle(UniqueHandle&& other) noexcept : handle_(std::exchange(other.handle_, nullptr)) {}
    UniqueHandle& operator=(UniqueHandle&& other) noexcept {
        if (this != &other) {
            reset(std::exchange(other.handle_, nullptr));
        }
        return *this;
    }

    HANDLE get() const noexcept { return handle_; }
    explicit operator bool() const noexcept { return handle_ && handle_ != INVALID_HANDLE_VALUE; }

    HANDLE release() noexcept { return std::exchange(handle_, nullptr); }

    void reset(HANDLE handle = nullptr) noexcept {
        if (handle_ && handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
        }
        handle_ = handle;
    }

private:
    HANDLE handle_ = nullptr;
};

std::string JsonEscape(const std::string& input) {
    std::string output;
    output.reserve(input.size() + 8);
    for (char ch : input) {
        switch (ch) {
            case '\\':
                output += "\\\\";
                break;
            case '"':
                output += "\\\"";
                break;
            case '\n':
                output += "\\n";
                break;
            case '\r':
                output += "\\r";
                break;
            case '\t':
                output += "\\t";
                break;
            default:
                output += ch;
                break;
        }
    }
    return output;
}

std::string BuildHelloJson(const HandshakeConfig& config) {
    std::ostringstream stream;
    stream << "{\"type\":\"hello\",\"session_id\":\"" << JsonEscape(config.sessionId)
           << "\",\"nonce\":\"" << JsonEscape(config.nonce) << "\"}";
    return stream.str();
}

DWORD RemainingMs(std::chrono::steady_clock::time_point deadline) noexcept {
    const auto now = std::chrono::steady_clock::now();
    if (now >= deadline) {
        return 0;
    }
    return static_cast<DWORD>(std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count());
}

}  // namespace

struct HelloPeer::State {
    explicit State(HandshakeConfig value) : config(std::move(value)) {
        cancelEvent.reset(CreateEventW(nullptr, TRUE, FALSE, nullptr));
    }

    HandshakeConfig config;
    HelloPeer::MessageHandler messageHandler = nullptr;
    void* messageHandlerContext = nullptr;
    UniqueHandle pipe;
    UniqueHandle cancelEvent;
    std::atomic_bool cancelRequested{false};
    std::atomic_bool running{false};
    mutable std::mutex mutex;
    HandshakeResult result{HelloStatus::NotStarted, ERROR_SUCCESS};
};

const wchar_t* ToString(HelloStatus status) noexcept {
    switch (status) {
        case HelloStatus::NotStarted:
            return L"not_started";
        case HelloStatus::Started:
            return L"started";
        case HelloStatus::Connected:
            return L"connected";
        case HelloStatus::Cancelled:
            return L"cancelled";
        case HelloStatus::Timeout:
            return L"timeout";
        case HelloStatus::InvalidArgument:
            return L"invalid_argument";
        case HelloStatus::PipeUnavailable:
            return L"pipe_unavailable";
        case HelloStatus::AccessDenied:
            return L"access_denied";
        case HelloStatus::IoError:
            return L"io_error";
        case HelloStatus::ProtocolError:
            return L"protocol_error";
    }
    return L"unknown";
}

long ActiveWorkerCount() noexcept {
    return g_activeWorkers.load(std::memory_order_acquire);
}

namespace {

void SetResult(const std::shared_ptr<HelloPeer::State>& state, HelloStatus status, DWORD error = ERROR_SUCCESS) noexcept {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->result = HandshakeResult{status, error};
}

bool IsCancelled(const std::shared_ptr<HelloPeer::State>& state) noexcept {
    return state->cancelRequested.load(std::memory_order_acquire);
}

void CancelPipeIo(const std::shared_ptr<HelloPeer::State>& state) noexcept {
    std::lock_guard<std::mutex> lock(state->mutex);
    if (state->pipe) {
        CancelIoEx(state->pipe.get(), nullptr);
    }
}

bool WaitForIoOrCancel(
    const std::shared_ptr<HelloPeer::State>& state,
    HANDLE ioEvent,
    OVERLAPPED* overlapped,
    std::chrono::steady_clock::time_point deadline,
    DWORD* transferred) noexcept {
    HANDLE handles[2] = {ioEvent, state->cancelEvent.get()};
    while (!IsCancelled(state)) {
        const DWORD remaining = RemainingMs(deadline);
        if (remaining == 0) {
            CancelPipeIo(state);
            return false;
        }
        const DWORD wait = WaitForMultipleObjects(2, handles, FALSE, remaining);
        if (wait == WAIT_OBJECT_0) {
            std::lock_guard<std::mutex> lock(state->mutex);
            return state->pipe && GetOverlappedResult(state->pipe.get(), overlapped, transferred, FALSE);
        }
        if (wait == WAIT_OBJECT_0 + 1) {
            CancelPipeIo(state);
            return false;
        }
        if (wait == WAIT_TIMEOUT) {
            CancelPipeIo(state);
            return false;
        }
        return false;
    }
    CancelPipeIo(state);
    return false;
}

bool OverlappedWrite(
    const std::shared_ptr<HelloPeer::State>& state,
    const std::string& payload,
    std::chrono::steady_clock::time_point deadline) noexcept {
    UniqueHandle event(CreateEventW(nullptr, TRUE, FALSE, nullptr));
    if (!event) {
        return false;
    }

    OVERLAPPED overlapped{};
    overlapped.hEvent = event.get();
    DWORD written = 0;
    BOOL ok = FALSE;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (!state->pipe) {
            return false;
        }
        ok = WriteFile(state->pipe.get(), payload.data(), static_cast<DWORD>(payload.size()), nullptr, &overlapped);
    }
    if (ok) {
        return true;
    }
    const DWORD error = GetLastError();
    if (error != ERROR_IO_PENDING) {
        return false;
    }
    return WaitForIoOrCancel(state, event.get(), &overlapped, deadline, &written);
}

bool OverlappedRead(
    const std::shared_ptr<HelloPeer::State>& state,
    std::string* output,
    std::chrono::steady_clock::time_point deadline) noexcept {
    UniqueHandle event(CreateEventW(nullptr, TRUE, FALSE, nullptr));
    if (!event) {
        return false;
    }

    std::string buffer(kFrameHeaderBytes + kMaxFrameBytes, '\0');
    OVERLAPPED overlapped{};
    overlapped.hEvent = event.get();
    BOOL ok = FALSE;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (!state->pipe) {
            return false;
        }
        ok = ReadFile(state->pipe.get(), buffer.data(), static_cast<DWORD>(buffer.size()), nullptr, &overlapped);
    }
    DWORD read = 0;
    if (!ok) {
        const DWORD error = GetLastError();
        if (error != ERROR_IO_PENDING) {
            return false;
        }
        if (!WaitForIoOrCancel(state, event.get(), &overlapped, deadline, &read)) {
            return false;
        }
    } else {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (!state->pipe || !GetOverlappedResult(state->pipe.get(), &overlapped, &read, FALSE)) {
            return false;
        }
    }
    output->assign(buffer.data(), read);
    return true;
}

UniqueHandle TryOpenPipe(
    const std::shared_ptr<HelloPeer::State>& state,
    std::chrono::steady_clock::time_point deadline,
    DWORD* lastError) noexcept {
    while (!IsCancelled(state)) {
        if (RemainingMs(deadline) == 0) {
            *lastError = ERROR_TIMEOUT;
            return UniqueHandle();
        }
        HANDLE handle = CreateFileW(
            state->config.pipeName.c_str(),
            GENERIC_READ | GENERIC_WRITE,
            0,
            nullptr,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            nullptr);
        if (handle != INVALID_HANDLE_VALUE) {
            return UniqueHandle(handle);
        }

        *lastError = GetLastError();
        if (*lastError == ERROR_ACCESS_DENIED) {
            return UniqueHandle();
        }
        if (*lastError != ERROR_FILE_NOT_FOUND && *lastError != ERROR_PIPE_BUSY) {
            return UniqueHandle();
        }
        Sleep(std::min(kPollMs, RemainingMs(deadline)));
    }
    *lastError = ERROR_CANCELLED;
    return UniqueHandle();
}

void WorkerMain(std::shared_ptr<HelloPeer::State> state) noexcept {
    g_activeWorkers.fetch_add(1, std::memory_order_acq_rel);
    state->running.store(true, std::memory_order_release);
    SetResult(state, HelloStatus::Started);

    struct CompletionGuard {
        std::shared_ptr<HelloPeer::State> state;
        ~CompletionGuard() noexcept {
            state->running.store(false, std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(state->mutex);
                state->pipe.reset();
            }
            g_activeWorkers.fetch_sub(1, std::memory_order_acq_rel);
        }
    } guard{state};

    try {
        if (state->config.pipeName.empty() || state->config.sessionId.empty() || state->config.nonce.empty()) {
            SetResult(state, HelloStatus::InvalidArgument, ERROR_INVALID_PARAMETER);
            return;
        }
        if (!state->cancelEvent) {
            SetResult(state, HelloStatus::IoError, ERROR_NOT_ENOUGH_MEMORY);
            return;
        }

        const DWORD timeoutMs = ClampTimeout(state->config.timeoutMs);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);

        DWORD lastError = ERROR_SUCCESS;
        UniqueHandle pipe = TryOpenPipe(state, deadline, &lastError);
        if (!pipe) {
            if (lastError == ERROR_CANCELLED) {
                SetResult(state, HelloStatus::Cancelled, lastError);
            } else if (lastError == ERROR_TIMEOUT) {
                SetResult(state, HelloStatus::Timeout, lastError);
            } else if (lastError == ERROR_ACCESS_DENIED) {
                SetResult(state, HelloStatus::AccessDenied, lastError);
            } else {
                SetResult(state, HelloStatus::PipeUnavailable, lastError);
            }
            return;
        }

        {
            std::lock_guard<std::mutex> lock(state->mutex);
            state->pipe = std::move(pipe);
        }

        DWORD mode = PIPE_READMODE_MESSAGE;
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (state->pipe) {
                SetNamedPipeHandleState(state->pipe.get(), &mode, nullptr, nullptr);
            }
        }

        const std::string helloJson = BuildHelloJson(state->config);
        std::string helloFrame;
        if (!EncodeFrame(helloJson, &helloFrame)) {
            SetResult(state, HelloStatus::ProtocolError, ERROR_INVALID_DATA);
            return;
        }
        if (!OverlappedWrite(state, helloFrame, deadline)) {
            SetResult(state, IsCancelled(state) ? HelloStatus::Cancelled : HelloStatus::IoError, GetLastError());
            return;
        }

        std::string ackFrame;
        if (!OverlappedRead(state, &ackFrame, deadline)) {
            SetResult(state, IsCancelled(state) ? HelloStatus::Cancelled : HelloStatus::IoError, GetLastError());
            return;
        }

        const DecodedFrame decoded = DecodeFrame(ackFrame);
        WireMessage message;
        if (decoded.status != FrameStatus::Ok || !TryParseWireMessage(decoded.json, &message) ||
            message.type != "hello_ack") {
            SetResult(state, HelloStatus::ProtocolError, ERROR_INVALID_DATA);
            return;
        }

        SetResult(state, HelloStatus::Connected);
        while (!IsCancelled(state)) {
            std::string commandFrame;
            if (!OverlappedRead(state, &commandFrame, std::chrono::steady_clock::now() + std::chrono::hours(24))) {
                if (IsCancelled(state)) {
                    break;
                }
                continue;
            }
            const DecodedFrame commandDecoded = DecodeFrame(commandFrame);
            WireMessage command;
            if (commandDecoded.status == FrameStatus::Ok && TryParseWireMessage(commandDecoded.json, &command) &&
                state->messageHandler) {
                state->messageHandler(command, state->messageHandlerContext);
            }
        }
    } catch (...) {
        SetResult(state, HelloStatus::IoError, ERROR_UNHANDLED_EXCEPTION);
    }

}

}  // namespace

HelloPeer::HelloPeer() noexcept = default;

HelloPeer::~HelloPeer() noexcept {
    Deactivate();
}

bool HelloPeer::StartAsync(const HandshakeConfig& config) noexcept {
    return StartAsync(config, nullptr, nullptr);
}

bool HelloPeer::StartAsync(const HandshakeConfig& config, MessageHandler handler, void* handlerContext) noexcept {
    try {
        std::lock_guard<std::mutex> lock(stateMutex_);
        if (state_ && state_->running.load(std::memory_order_acquire)) {
            return false;
        }
        state_ = std::make_shared<State>(config);
        state_->messageHandler = handler;
        state_->messageHandlerContext = handlerContext;
        std::thread(WorkerMain, state_).detach();
        return true;
    } catch (...) {
        return false;
    }
}

void HelloPeer::Deactivate() noexcept {
    std::shared_ptr<State> state;
    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        state = state_;
    }
    if (!state) {
        return;
    }
    state->cancelRequested.store(true, std::memory_order_release);
    if (state->cancelEvent) {
        SetEvent(state->cancelEvent.get());
    }
    CancelPipeIo(state);
}

bool HelloPeer::IsRunning() const noexcept {
    std::lock_guard<std::mutex> lock(stateMutex_);
    return state_ && state_->running.load(std::memory_order_acquire);
}

HandshakeResult HelloPeer::LastResult() const noexcept {
    std::shared_ptr<State> state;
    {
        std::lock_guard<std::mutex> lock(stateMutex_);
        state = state_;
    }
    if (!state) {
        return {};
    }
    std::lock_guard<std::mutex> lock(state->mutex);
    return state->result;
}

bool HelloPeer::WaitForCompletionForTest(DWORD timeoutMs) noexcept {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    while (std::chrono::steady_clock::now() < deadline) {
        if (!IsRunning()) {
            return true;
        }
        Sleep(kPollMs);
    }
    return !IsRunning();
}

}  // namespace voicetype::tsf
