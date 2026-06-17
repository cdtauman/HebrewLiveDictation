#include "voice_type_tsf_runtime.h"

#include <algorithm>
#include <cwctype>
#include <new>
#include <utility>

namespace voicetype::tsf {
namespace {

void ReleaseIfSet(IUnknown* value) noexcept {
    if (value) {
        value->Release();
    }
}

bool FindSingle(const std::wstring& text, const std::wstring& needle, size_t* position) noexcept {
    if (!position || needle.empty()) {
        return false;
    }
    const size_t first = text.find(needle);
    if (first == std::wstring::npos) {
        return false;
    }
    if (text.find(needle, first + needle.size()) != std::wstring::npos) {
        return false;
    }
    *position = first;
    return true;
}

std::pair<LONG, LONG> LastWordRange(const std::wstring& text) noexcept {
    LONG end = static_cast<LONG>(text.size());
    while (end > 0 && iswspace(text[static_cast<size_t>(end - 1)])) {
        --end;
    }
    LONG start = end;
    while (start > 0 && !iswspace(text[static_cast<size_t>(start - 1)])) {
        --start;
    }
    return {start, end};
}

std::pair<LONG, LONG> LastSentenceRange(const std::wstring& text) noexcept {
    LONG end = static_cast<LONG>(text.size());
    while (end > 0 && iswspace(text[static_cast<size_t>(end - 1)])) {
        --end;
    }
    LONG start = 0;
    for (LONG i = end - 1; i >= 0; --i) {
        const wchar_t ch = text[static_cast<size_t>(i)];
        if (ch == L'.' || ch == L'?' || ch == L'!' || ch == L'\n') {
            start = i + 1;
            break;
        }
    }
    while (start < end && iswspace(text[static_cast<size_t>(start)])) {
        ++start;
    }
    return {start, end};
}

}  // namespace

TsfCompositionRuntime::TsfCompositionRuntime() noexcept = default;

TsfCompositionRuntime::~TsfCompositionRuntime() noexcept {
    Detach();
}

void TsfCompositionRuntime::Attach(ITfContext* context, TfClientId clientId, TfGuidAtom displayAttributeAtom) noexcept {
    Detach();
    context_ = context;
    if (context_) {
        context_->AddRef();
    }
    clientId_ = clientId;
    displayAttributeAtom_ = displayAttributeAtom;
}

void TsfCompositionRuntime::Detach() noexcept {
    ClearCompositionState();
    ReleaseIfSet(std::exchange(context_, nullptr));
    clientId_ = 0;
    displayAttributeAtom_ = TF_INVALID_GUIDATOM;
    ownedText_.clear();
}

RuntimeStatus TsfCompositionRuntime::Enqueue(const WireMessage& message) noexcept {
    if (!context_ || clientId_ == 0) {
        return RuntimeStatus::NoContext;
    }
    if (!sequenceGate_.Accept(message.generation, message.seq)) {
        return RuntimeStatus::StaleMessage;
    }
    const HRESULT hr = RequestEditSessionFor(message);
    return SUCCEEDED(hr) ? RuntimeStatus::Ok : RuntimeStatus::Rejected;
}

RuntimeStatus TsfCompositionRuntime::ExecuteForTest(TfEditCookie editCookie, const WireMessage& message) noexcept {
    if (message.type == "update_composition") {
        return UpdateComposition(editCookie, message);
    }
    if (message.type == "commit_text") {
        return CommitText(editCookie, message);
    }
    if (message.type == "replace_in_scope") {
        return ReplaceInScope(editCookie, message);
    }
    if (message.type == "select_last") {
        return SelectLast(editCookie, message);
    }
    if (message.type == "cancel_composition") {
        ClearCompositionState();
        ownedText_.clear();
        return RuntimeStatus::Ok;
    }
    return RuntimeStatus::InvalidScope;
}

bool TsfCompositionRuntime::HasActiveComposition() const noexcept {
    return composition_ != nullptr && compositionRange_ != nullptr;
}

std::wstring TsfCompositionRuntime::OwnedText() const {
    return ownedText_;
}

RuntimeStatus TsfCompositionRuntime::UpdateComposition(TfEditCookie editCookie, const WireMessage& message) noexcept {
    if (!context_) {
        return RuntimeStatus::NoContext;
    }
    HRESULT hr = EnsureComposition(editCookie, message.text);
    if (FAILED(hr)) {
        return RuntimeStatus::Rejected;
    }
    hr = SetCompositionText(editCookie, message.text);
    if (FAILED(hr)) {
        return RuntimeStatus::Failed;
    }
    ownedText_ = message.text;
    ApplyInterimDisplayAttribute(editCookie, context_, compositionRange_, displayAttributeAtom_);
    if (message.hasSelection) {
        NormalizedSelection selection;
        if (NormalizeSelection(ownedText_.size(), message.selectionStartUtf16, message.selectionEndUtf16, &selection)) {
            SelectOwnedRange(editCookie, selection.start, selection.end);
        }
    } else {
        SetSelectionToRangeEnd(editCookie, context_, compositionRange_);
    }
    return RuntimeStatus::Ok;
}

RuntimeStatus TsfCompositionRuntime::CommitText(TfEditCookie editCookie, const WireMessage& message) noexcept {
    if (!context_) {
        return RuntimeStatus::NoContext;
    }
    HRESULT hr = EnsureComposition(editCookie, message.text);
    if (FAILED(hr)) {
        return RuntimeStatus::Rejected;
    }
    hr = SetCompositionText(editCookie, message.text);
    if (FAILED(hr)) {
        return RuntimeStatus::Failed;
    }
    ClearDisplayAttribute(editCookie, context_, compositionRange_);
    SetSelectionToRangeEnd(editCookie, context_, compositionRange_);
    if (composition_) {
        composition_->EndComposition(editCookie);
    }
    ownedText_ += message.text;
    ClearCompositionState();
    return RuntimeStatus::Ok;
}

RuntimeStatus TsfCompositionRuntime::ReplaceInScope(TfEditCookie editCookie, const WireMessage& message) noexcept {
    size_t position = 0;
    if (!FindSingle(ownedText_, message.oldText, &position)) {
        return RuntimeStatus::InvalidScope;
    }
    std::wstring next = ownedText_;
    next.replace(position, message.oldText.size(), message.newText);
    WireMessage update = message;
    update.text = next;
    update.selectionStartUtf16 = static_cast<uint64_t>(position + message.newText.size());
    update.selectionEndUtf16 = update.selectionStartUtf16;
    update.hasSelection = true;
    return UpdateComposition(editCookie, update);
}

RuntimeStatus TsfCompositionRuntime::SelectLast(TfEditCookie editCookie, const WireMessage& message) noexcept {
    if (!HasActiveComposition() || ownedText_.empty()) {
        return RuntimeStatus::InvalidScope;
    }
    std::pair<LONG, LONG> range = message.unit == "sentence" ? LastSentenceRange(ownedText_) : LastWordRange(ownedText_);
    if (range.first >= range.second) {
        return RuntimeStatus::InvalidScope;
    }
    return SUCCEEDED(SelectOwnedRange(editCookie, range.first, range.second)) ? RuntimeStatus::Ok : RuntimeStatus::Failed;
}

HRESULT TsfCompositionRuntime::EnsureComposition(TfEditCookie editCookie, const std::wstring& text) noexcept {
    if (HasActiveComposition()) {
        return S_OK;
    }

    TF_SELECTION selection = {};
    ULONG fetched = 0;
    HRESULT hr = context_->GetSelection(editCookie, TF_DEFAULT_SELECTION, 1, &selection, &fetched);
    if (FAILED(hr) || fetched == 0 || !selection.range) {
        return FAILED(hr) ? hr : E_FAIL;
    }

    ITfRange* range = selection.range;
    hr = range->Collapse(editCookie, TF_ANCHOR_END);
    if (SUCCEEDED(hr)) {
        hr = range->SetText(editCookie, 0, text.c_str(), static_cast<LONG>(text.size()));
    }
    if (FAILED(hr)) {
        range->Release();
        return hr;
    }

    ITfContextComposition* compositionContext = nullptr;
    hr = context_->QueryInterface(IID_ITfContextComposition, reinterpret_cast<void**>(&compositionContext));
    if (SUCCEEDED(hr) && compositionContext) {
        hr = compositionContext->StartComposition(editCookie, range, nullptr, &composition_);
        compositionContext->Release();
    }
    if (FAILED(hr)) {
        range->Release();
        return hr;
    }

    compositionRange_ = range;
    return S_OK;
}

HRESULT TsfCompositionRuntime::SetCompositionText(TfEditCookie editCookie, const std::wstring& text) noexcept {
    if (!compositionRange_) {
        return E_FAIL;
    }
    return compositionRange_->SetText(editCookie, 0, text.c_str(), static_cast<LONG>(text.size()));
}

HRESULT TsfCompositionRuntime::SelectOwnedRange(TfEditCookie editCookie, LONG start, LONG end) noexcept {
    if (!context_ || !compositionRange_ || start < 0 || end < start || static_cast<size_t>(end) > ownedText_.size()) {
        return E_INVALIDARG;
    }
    ITfRange* range = nullptr;
    HRESULT hr = compositionRange_->Clone(&range);
    if (FAILED(hr) || !range) {
        return hr;
    }
    LONG shifted = 0;
    hr = range->Collapse(editCookie, TF_ANCHOR_START);
    if (SUCCEEDED(hr)) {
        hr = range->ShiftStart(editCookie, start, &shifted, nullptr);
    }
    if (SUCCEEDED(hr)) {
        hr = range->ShiftEnd(editCookie, end - start, &shifted, nullptr);
    }
    if (SUCCEEDED(hr)) {
        TF_SELECTION selection = {};
        selection.range = range;
        selection.style.ase = TF_AE_NONE;
        selection.style.fInterimChar = FALSE;
        hr = context_->SetSelection(editCookie, 1, &selection);
    }
    range->Release();
    return hr;
}

HRESULT TsfCompositionRuntime::RequestEditSessionFor(const WireMessage& message) noexcept {
    struct EditContext {
        TsfCompositionRuntime* runtime;
        WireMessage message;
    };
    auto* editContext = new (std::nothrow) EditContext{this, message};
    if (!editContext) {
        return E_OUTOFMEMORY;
    }
    auto callback = [](TfEditCookie editCookie, void* raw) noexcept -> HRESULT {
        auto* data = static_cast<EditContext*>(raw);
        const RuntimeStatus status = data->runtime->ExecuteForTest(editCookie, data->message);
        delete data;
        return status == RuntimeStatus::Ok ? S_OK : E_FAIL;
    };
    auto cleanup = [](void* raw) noexcept {
        delete static_cast<EditContext*>(raw);
    };
    ITfEditSession* session = new (std::nothrow) CallbackEditSession(callback, editContext, cleanup);
    if (!session) {
        delete editContext;
        return E_OUTOFMEMORY;
    }
    HRESULT sessionResult = E_FAIL;
    HRESULT hr = context_->RequestEditSession(clientId_, session, TF_ES_ASYNC | TF_ES_READWRITE, &sessionResult);
    session->Release();
    return SUCCEEDED(hr) ? sessionResult : hr;
}

void TsfCompositionRuntime::ClearCompositionState() noexcept {
    ReleaseIfSet(std::exchange(compositionRange_, nullptr));
    ReleaseIfSet(std::exchange(composition_, nullptr));
}

}  // namespace voicetype::tsf
