#pragma once

#include <Windows.h>
#include <msctf.h>

#include <string>

#include "voice_type_tsf_composition.h"
#include "voice_type_tsf_protocol.h"

namespace voicetype::tsf {

enum class RuntimeStatus {
    Ok,
    NoContext,
    StaleMessage,
    InvalidScope,
    Rejected,
    Failed,
};

class TsfCompositionRuntime final {
public:
    TsfCompositionRuntime() noexcept;
    ~TsfCompositionRuntime() noexcept;

    TsfCompositionRuntime(const TsfCompositionRuntime&) = delete;
    TsfCompositionRuntime& operator=(const TsfCompositionRuntime&) = delete;

    void Attach(ITfContext* context, TfClientId clientId, TfGuidAtom displayAttributeAtom) noexcept;
    void Detach() noexcept;
    RuntimeStatus Enqueue(const WireMessage& message) noexcept;
    RuntimeStatus ExecuteForTest(TfEditCookie editCookie, const WireMessage& message) noexcept;
    bool HasActiveComposition() const noexcept;
    std::wstring OwnedText() const;

private:
    RuntimeStatus UpdateComposition(TfEditCookie editCookie, const WireMessage& message) noexcept;
    RuntimeStatus CommitText(TfEditCookie editCookie, const WireMessage& message) noexcept;
    RuntimeStatus ReplaceInScope(TfEditCookie editCookie, const WireMessage& message) noexcept;
    RuntimeStatus SelectLast(TfEditCookie editCookie, const WireMessage& message) noexcept;

    HRESULT EnsureComposition(TfEditCookie editCookie, const std::wstring& text) noexcept;
    HRESULT SetCompositionText(TfEditCookie editCookie, const std::wstring& text) noexcept;
    HRESULT SelectOwnedRange(TfEditCookie editCookie, LONG start, LONG end) noexcept;
    HRESULT RequestEditSessionFor(const WireMessage& message) noexcept;
    void ClearCompositionState() noexcept;

    ITfContext* context_ = nullptr;
    ITfComposition* composition_ = nullptr;
    ITfRange* compositionRange_ = nullptr;
    TfClientId clientId_ = 0;
    TfGuidAtom displayAttributeAtom_ = TF_INVALID_GUIDATOM;
    SequenceGate sequenceGate_;
    std::wstring ownedText_;
};

}  // namespace voicetype::tsf
