#pragma once

#include <Windows.h>
#include <msctf.h>

#include <atomic>

namespace voicetype::tsf {

enum class RegistrationAction {
    Register,
    Unregister,
};

struct RegistrationPlan {
    RegistrationAction action = RegistrationAction::Register;
    bool dryRun = true;
    bool explicitExperimentalConsent = false;
    bool registerLanguageProfile = false;
};

struct RegistrationResult {
    HRESULT hr = S_FALSE;
    bool changedSystemState = false;
};

const GUID& VoiceTypeTextServiceClsid() noexcept;
const GUID& VoiceTypeLanguageProfileGuid() noexcept;

RegistrationResult ApplyRegistrationPlan(const RegistrationPlan& plan) noexcept;

class ScopedThreadMgrActivation final {
public:
    ScopedThreadMgrActivation() noexcept;
    ~ScopedThreadMgrActivation() noexcept;

    ScopedThreadMgrActivation(const ScopedThreadMgrActivation&) = delete;
    ScopedThreadMgrActivation& operator=(const ScopedThreadMgrActivation&) = delete;

    HRESULT Activate(ITfThreadMgr* threadMgr) noexcept;
    void Deactivate() noexcept;
    bool IsActive() const noexcept;
    TfClientId ClientId() const noexcept;

private:
    ITfThreadMgr* threadMgr_ = nullptr;
    TfClientId clientId_ = 0;
    bool active_ = false;
};

class ScopedFocusAssociation final {
public:
    ScopedFocusAssociation() noexcept;
    ~ScopedFocusAssociation() noexcept;

    ScopedFocusAssociation(const ScopedFocusAssociation&) = delete;
    ScopedFocusAssociation& operator=(const ScopedFocusAssociation&) = delete;

    HRESULT Associate(ITfThreadMgr* threadMgr, HWND hwnd, ITfDocumentMgr* documentMgr) noexcept;
    void Restore() noexcept;
    bool IsAssociated() const noexcept;

private:
    ITfThreadMgr* threadMgr_ = nullptr;
    HWND hwnd_ = nullptr;
    ITfDocumentMgr* previousDocumentMgr_ = nullptr;
    bool associated_ = false;
};

struct FocusSnapshot {
    HWND hwnd = nullptr;
    DWORD processId = 0;
    DWORD threadId = 0;
    uint64_t generation = 0;
};

class FocusIsolationGate final {
public:
    bool Attach(const FocusSnapshot& snapshot) noexcept;
    bool Accepts(const FocusSnapshot& snapshot) const noexcept;
    void Detach() noexcept;

private:
    mutable SRWLOCK lock_ = SRWLOCK_INIT;
    FocusSnapshot snapshot_{};
    bool attached_ = false;
};

long ActiveThreadMgrActivations() noexcept;
long ActiveFocusAssociations() noexcept;

}  // namespace voicetype::tsf
