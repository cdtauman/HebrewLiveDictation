#pragma once

#include <Windows.h>
#include <msctf.h>

#include <atomic>

#include "voice_type_tsf_hello_peer.h"
#include "voice_type_tsf_runtime.h"

namespace voicetype::tsf {

class VoiceTypeTextService final : public ITfTextInputProcessorEx {
public:
    VoiceTypeTextService() noexcept;

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** object) noexcept override;
    ULONG STDMETHODCALLTYPE AddRef() noexcept override;
    ULONG STDMETHODCALLTYPE Release() noexcept override;
    HRESULT STDMETHODCALLTYPE Activate(ITfThreadMgr* threadMgr, TfClientId clientId) noexcept override;
    HRESULT STDMETHODCALLTYPE Deactivate() noexcept override;
    HRESULT STDMETHODCALLTYPE ActivateEx(ITfThreadMgr* threadMgr, TfClientId clientId, DWORD flags) noexcept override;

private:
    ~VoiceTypeTextService() noexcept;

    static void OnNativeMessage(const WireMessage& message, void* context) noexcept;
    void HandleNativeMessage(const WireMessage& message) noexcept;
    bool AttachFocusedContext() noexcept;

    std::atomic<ULONG> refCount_{1};
    ITfThreadMgr* threadMgr_ = nullptr;
    TfClientId clientId_ = 0;
    HelloPeer peer_;
    TsfCompositionRuntime runtime_;
};

class VoiceTypeClassFactory final : public IClassFactory {
public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** object) noexcept override;
    ULONG STDMETHODCALLTYPE AddRef() noexcept override;
    ULONG STDMETHODCALLTYPE Release() noexcept override;
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID riid, void** object) noexcept override;
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) noexcept override;

private:
    std::atomic<ULONG> refCount_{1};
};

HRESULT RegisterComServer(HMODULE module) noexcept;
HRESULT UnregisterComServer() noexcept;
bool LoadAdvertisedHandshake(HandshakeConfig* config) noexcept;
long ActiveComObjects() noexcept;
long ServerLocks() noexcept;

}  // namespace voicetype::tsf
