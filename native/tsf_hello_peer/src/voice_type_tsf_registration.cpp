#include "voice_type_tsf_registration.h"

#include <utility>

namespace voicetype::tsf {
namespace {

constexpr GUID kVoiceTypeTextServiceClsid = {
    0x7c358161,
    0x3d55,
    0x4c15,
    {0x9a, 0xf7, 0xf4, 0x60, 0xa9, 0x83, 0xc9, 0x51}};

constexpr GUID kVoiceTypeLanguageProfileGuid = {
    0x91c7e54b,
    0xd56f,
    0x4b33,
    {0xa0, 0x96, 0x64, 0x43, 0x80, 0x48, 0xd5, 0x98}};

std::atomic<long> g_activeThreadMgrActivations{0};
std::atomic<long> g_activeFocusAssociations{0};

void ReleaseIfSet(IUnknown* value) noexcept {
    if (value) {
        value->Release();
    }
}

HRESULT CoCreateProfiles(ITfInputProcessorProfiles** profiles) noexcept {
    if (!profiles) {
        return E_POINTER;
    }
    *profiles = nullptr;
    return CoCreateInstance(
        CLSID_TF_InputProcessorProfiles,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_ITfInputProcessorProfiles,
        reinterpret_cast<void**>(profiles));
}

}  // namespace

const GUID& VoiceTypeTextServiceClsid() noexcept {
    return kVoiceTypeTextServiceClsid;
}

const GUID& VoiceTypeLanguageProfileGuid() noexcept {
    return kVoiceTypeLanguageProfileGuid;
}

RegistrationResult ApplyRegistrationPlan(const RegistrationPlan& plan) noexcept {
    RegistrationResult result;
    if (plan.dryRun) {
        result.hr = S_FALSE;
        result.changedSystemState = false;
        return result;
    }
    if (!plan.explicitExperimentalConsent) {
        result.hr = E_ACCESSDENIED;
        result.changedSystemState = false;
        return result;
    }
    if (plan.registerLanguageProfile) {
        result.hr = E_NOTIMPL;
        result.changedSystemState = false;
        return result;
    }

    ITfInputProcessorProfiles* profiles = nullptr;
    HRESULT hr = CoCreateProfiles(&profiles);
    if (FAILED(hr) || !profiles) {
        result.hr = hr;
        return result;
    }

    if (plan.action == RegistrationAction::Register) {
        hr = profiles->Register(VoiceTypeTextServiceClsid());
    } else {
        hr = profiles->Unregister(VoiceTypeTextServiceClsid());
    }
    ReleaseIfSet(profiles);
    result.hr = hr;
    result.changedSystemState = SUCCEEDED(hr);
    return result;
}

ScopedThreadMgrActivation::ScopedThreadMgrActivation() noexcept = default;

ScopedThreadMgrActivation::~ScopedThreadMgrActivation() noexcept {
    Deactivate();
}

HRESULT ScopedThreadMgrActivation::Activate(ITfThreadMgr* threadMgr) noexcept {
    if (!threadMgr || active_) {
        return E_INVALIDARG;
    }
    TfClientId clientId = 0;
    HRESULT hr = threadMgr->Activate(&clientId);
    if (FAILED(hr)) {
        return hr;
    }
    threadMgr_ = threadMgr;
    threadMgr_->AddRef();
    clientId_ = clientId;
    active_ = true;
    g_activeThreadMgrActivations.fetch_add(1, std::memory_order_acq_rel);
    return S_OK;
}

void ScopedThreadMgrActivation::Deactivate() noexcept {
    if (!active_) {
        return;
    }
    ITfThreadMgr* threadMgr = std::exchange(threadMgr_, nullptr);
    active_ = false;
    clientId_ = 0;
    if (threadMgr) {
        threadMgr->Deactivate();
        threadMgr->Release();
    }
    g_activeThreadMgrActivations.fetch_sub(1, std::memory_order_acq_rel);
}

bool ScopedThreadMgrActivation::IsActive() const noexcept {
    return active_;
}

TfClientId ScopedThreadMgrActivation::ClientId() const noexcept {
    return clientId_;
}

ScopedFocusAssociation::ScopedFocusAssociation() noexcept = default;

ScopedFocusAssociation::~ScopedFocusAssociation() noexcept {
    Restore();
}

HRESULT ScopedFocusAssociation::Associate(ITfThreadMgr* threadMgr, HWND hwnd, ITfDocumentMgr* documentMgr) noexcept {
    if (!threadMgr || !hwnd || !documentMgr || associated_) {
        return E_INVALIDARG;
    }
    ITfDocumentMgr* previous = nullptr;
    HRESULT hr = threadMgr->AssociateFocus(hwnd, documentMgr, &previous);
    if (FAILED(hr)) {
        ReleaseIfSet(previous);
        return hr;
    }
    threadMgr_ = threadMgr;
    threadMgr_->AddRef();
    hwnd_ = hwnd;
    previousDocumentMgr_ = previous;
    associated_ = true;
    g_activeFocusAssociations.fetch_add(1, std::memory_order_acq_rel);
    return S_OK;
}

void ScopedFocusAssociation::Restore() noexcept {
    if (!associated_) {
        return;
    }
    ITfThreadMgr* threadMgr = std::exchange(threadMgr_, nullptr);
    HWND hwnd = std::exchange(hwnd_, nullptr);
    ITfDocumentMgr* previous = std::exchange(previousDocumentMgr_, nullptr);
    associated_ = false;

    if (threadMgr && hwnd) {
        ITfDocumentMgr* replaced = nullptr;
        threadMgr->AssociateFocus(hwnd, previous, &replaced);
        ReleaseIfSet(replaced);
        threadMgr->Release();
    }
    ReleaseIfSet(previous);
    g_activeFocusAssociations.fetch_sub(1, std::memory_order_acq_rel);
}

bool ScopedFocusAssociation::IsAssociated() const noexcept {
    return associated_;
}

bool FocusIsolationGate::Attach(const FocusSnapshot& snapshot) noexcept {
    if (!snapshot.hwnd || snapshot.processId == 0 || snapshot.threadId == 0) {
        return false;
    }
    AcquireSRWLockExclusive(&lock_);
    snapshot_ = snapshot;
    attached_ = true;
    ReleaseSRWLockExclusive(&lock_);
    return true;
}

bool FocusIsolationGate::Accepts(const FocusSnapshot& snapshot) const noexcept {
    AcquireSRWLockShared(&lock_);
    const bool ok = attached_ && snapshot_.hwnd == snapshot.hwnd && snapshot_.processId == snapshot.processId &&
                    snapshot_.threadId == snapshot.threadId && snapshot_.generation == snapshot.generation;
    ReleaseSRWLockShared(&lock_);
    return ok;
}

void FocusIsolationGate::Detach() noexcept {
    AcquireSRWLockExclusive(&lock_);
    snapshot_ = {};
    attached_ = false;
    ReleaseSRWLockExclusive(&lock_);
}

long ActiveThreadMgrActivations() noexcept {
    return g_activeThreadMgrActivations.load(std::memory_order_acquire);
}

long ActiveFocusAssociations() noexcept {
    return g_activeFocusAssociations.load(std::memory_order_acquire);
}

}  // namespace voicetype::tsf
