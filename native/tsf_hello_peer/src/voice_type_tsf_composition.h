#pragma once

#include <Windows.h>
#include <msctf.h>

#include <atomic>
#include <cstdint>
#include <mutex>
#include <optional>
#include <string>

#include "voice_type_tsf_protocol.h"

namespace voicetype::tsf {

enum class CompositionCommandType {
    UpdateComposition,
    CommitText,
    CancelComposition,
};

struct CompositionCommand {
    CompositionCommandType type = CompositionCommandType::UpdateComposition;
    uint64_t generation = 0;
    uint64_t seq = 0;
    std::wstring text;
    uint64_t selectionStartUtf16 = 0;
    uint64_t selectionEndUtf16 = 0;
    bool hasSelection = false;
};

struct NormalizedSelection {
    LONG start = 0;
    LONG end = 0;
    bool collapsed = true;
};

bool NormalizeSelection(
    size_t textLengthUtf16,
    uint64_t selectionStartUtf16,
    uint64_t selectionEndUtf16,
    NormalizedSelection* selection) noexcept;

class CompositionCommandQueue {
public:
    bool Push(const CompositionCommand& command) noexcept;
    std::optional<CompositionCommand> TakeNextForEditSession() noexcept;
    void MarkEditSessionComplete() noexcept;
    bool HasPending() const noexcept;
    bool EditSessionActive() const noexcept;

private:
    mutable std::mutex mutex_;
    SequenceGate sequenceGate_;
    bool editSessionActive_ = false;
    std::optional<CompositionCommand> pendingUpdate_;
    std::optional<CompositionCommand> pendingCommit_;
    std::optional<CompositionCommand> pendingCancel_;
};

class DisplayAttributePlan {
public:
    static const GUID& InterimAttributeGuid() noexcept;
    static TF_DISPLAYATTRIBUTE InterimAttribute() noexcept;
};

HRESULT ApplyInterimDisplayAttribute(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* compositionRange,
    TfGuidAtom displayAttributeAtom) noexcept;

HRESULT ClearDisplayAttribute(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* compositionRange) noexcept;

HRESULT SetSelectionToRangeEnd(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* range) noexcept;

class CallbackEditSession final : public ITfEditSession {
public:
    using Callback = HRESULT (*)(TfEditCookie editCookie, void* context) noexcept;
    using Cleanup = void (*)(void* context) noexcept;

    CallbackEditSession(Callback callback, void* context, Cleanup cleanup = nullptr) noexcept;

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** object) noexcept override;
    ULONG STDMETHODCALLTYPE AddRef() noexcept override;
    ULONG STDMETHODCALLTYPE Release() noexcept override;
    HRESULT STDMETHODCALLTYPE DoEditSession(TfEditCookie editCookie) noexcept override;

private:
    std::atomic<ULONG> refCount_{1};
    Callback callback_ = nullptr;
    Cleanup cleanup_ = nullptr;
    void* context_ = nullptr;
};

}  // namespace voicetype::tsf
