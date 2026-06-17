#include "voice_type_tsf_composition.h"

#include <OleAuto.h>
#include <algorithm>
#include <limits>
#include <utility>

namespace voicetype::tsf {
namespace {

constexpr GUID kVoiceTypeInterimDisplayAttribute = {
    0x49d26fc1,
    0x2f6d,
    0x4ca8,
    {0x8d, 0x4b, 0xe9, 0x4b, 0x89, 0x2f, 0x21, 0x5a}};

void ReleaseIfSet(IUnknown* value) noexcept {
    if (value) {
        value->Release();
    }
}

}  // namespace

bool NormalizeSelection(
    size_t textLengthUtf16,
    uint64_t selectionStartUtf16,
    uint64_t selectionEndUtf16,
    NormalizedSelection* selection) noexcept {
    if (!selection) {
        return false;
    }
    if (selectionStartUtf16 > selectionEndUtf16) {
        return false;
    }
    if (selectionEndUtf16 > textLengthUtf16) {
        return false;
    }
    if (selectionEndUtf16 > static_cast<uint64_t>(std::numeric_limits<LONG>::max())) {
        return false;
    }
    selection->start = static_cast<LONG>(selectionStartUtf16);
    selection->end = static_cast<LONG>(selectionEndUtf16);
    selection->collapsed = selectionStartUtf16 == selectionEndUtf16;
    return true;
}

bool CompositionCommandQueue::Push(const CompositionCommand& command) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!sequenceGate_.Accept(command.generation, command.seq)) {
        return false;
    }
    switch (command.type) {
        case CompositionCommandType::UpdateComposition:
            pendingUpdate_ = command;
            break;
        case CompositionCommandType::CommitText:
            pendingCommit_ = command;
            pendingUpdate_.reset();
            break;
        case CompositionCommandType::CancelComposition:
            pendingCancel_ = command;
            pendingCommit_.reset();
            pendingUpdate_.reset();
            break;
    }
    return true;
}

std::optional<CompositionCommand> CompositionCommandQueue::TakeNextForEditSession() noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    if (editSessionActive_) {
        return std::nullopt;
    }

    std::optional<CompositionCommand> next;
    if (pendingCancel_) {
        next = std::exchange(pendingCancel_, std::nullopt);
    } else if (pendingCommit_) {
        next = std::exchange(pendingCommit_, std::nullopt);
    } else if (pendingUpdate_) {
        next = std::exchange(pendingUpdate_, std::nullopt);
    }

    if (next) {
        editSessionActive_ = true;
    }
    return next;
}

void CompositionCommandQueue::MarkEditSessionComplete() noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    editSessionActive_ = false;
}

bool CompositionCommandQueue::HasPending() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return pendingCancel_.has_value() || pendingCommit_.has_value() || pendingUpdate_.has_value();
}

bool CompositionCommandQueue::EditSessionActive() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return editSessionActive_;
}

const GUID& DisplayAttributePlan::InterimAttributeGuid() noexcept {
    return kVoiceTypeInterimDisplayAttribute;
}

TF_DISPLAYATTRIBUTE DisplayAttributePlan::InterimAttribute() noexcept {
    TF_DISPLAYATTRIBUTE attribute = {};
    attribute.crText.type = TF_CT_NONE;
    attribute.crBk.type = TF_CT_NONE;
    attribute.lsStyle = TF_LS_DOT;
    attribute.fBoldLine = TRUE;
    attribute.crLine.type = TF_CT_SYSCOLOR;
    attribute.crLine.nIndex = COLOR_HIGHLIGHT;
    attribute.bAttr = TF_ATTR_INPUT;
    return attribute;
}

HRESULT ApplyInterimDisplayAttribute(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* compositionRange,
    TfGuidAtom displayAttributeAtom) noexcept {
    if (!context || !compositionRange || displayAttributeAtom == TF_INVALID_GUIDATOM) {
        return E_INVALIDARG;
    }

    ITfProperty* property = nullptr;
    HRESULT hr = context->GetProperty(GUID_PROP_ATTRIBUTE, &property);
    if (FAILED(hr) || !property) {
        return hr;
    }

    VARIANT value;
    VariantInit(&value);
    value.vt = VT_I4;
    value.lVal = displayAttributeAtom;
    hr = property->SetValue(editCookie, compositionRange, &value);
    VariantClear(&value);
    ReleaseIfSet(property);
    return hr;
}

HRESULT ClearDisplayAttribute(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* compositionRange) noexcept {
    if (!context || !compositionRange) {
        return E_INVALIDARG;
    }

    ITfProperty* property = nullptr;
    HRESULT hr = context->GetProperty(GUID_PROP_ATTRIBUTE, &property);
    if (FAILED(hr) || !property) {
        return hr;
    }

    hr = property->Clear(editCookie, compositionRange);
    ReleaseIfSet(property);
    return hr;
}

HRESULT SetSelectionToRangeEnd(
    TfEditCookie editCookie,
    ITfContext* context,
    ITfRange* range) noexcept {
    if (!context || !range) {
        return E_INVALIDARG;
    }

    ITfRange* caretRange = nullptr;
    HRESULT hr = range->Clone(&caretRange);
    if (FAILED(hr) || !caretRange) {
        return hr;
    }

    hr = caretRange->Collapse(editCookie, TF_ANCHOR_END);
    if (SUCCEEDED(hr)) {
        TF_SELECTION selection = {};
        selection.range = caretRange;
        selection.style.ase = TF_AE_NONE;
        selection.style.fInterimChar = FALSE;
        hr = context->SetSelection(editCookie, 1, &selection);
    }

    ReleaseIfSet(caretRange);
    return hr;
}

CallbackEditSession::CallbackEditSession(Callback callback, void* context, Cleanup cleanup) noexcept
    : callback_(callback), cleanup_(cleanup), context_(context) {}

HRESULT CallbackEditSession::QueryInterface(REFIID riid, void** object) noexcept {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == IID_ITfEditSession) {
        *object = static_cast<ITfEditSession*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}

ULONG CallbackEditSession::AddRef() noexcept {
    return refCount_.fetch_add(1, std::memory_order_relaxed) + 1;
}

ULONG CallbackEditSession::Release() noexcept {
    const ULONG count = refCount_.fetch_sub(1, std::memory_order_acq_rel) - 1;
    if (count == 0) {
        if (context_ && cleanup_) {
            cleanup_(context_);
            context_ = nullptr;
        }
        delete this;
    }
    return count;
}

HRESULT CallbackEditSession::DoEditSession(TfEditCookie editCookie) noexcept {
    if (!callback_) {
        return E_FAIL;
    }
    void* context = std::exchange(context_, nullptr);
    return callback_(editCookie, context);
}

}  // namespace voicetype::tsf
