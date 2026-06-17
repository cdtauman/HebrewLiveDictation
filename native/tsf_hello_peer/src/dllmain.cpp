#include <Windows.h>

#include <new>

#include "voice_type_tsf_hello_peer.h"
#include "voice_type_tsf_registration.h"
#include "voice_type_tsf_text_service.h"

HMODULE g_module = nullptr;

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

extern "C" HRESULT __stdcall DllCanUnloadNow() {
    return voicetype::tsf::ActiveComObjects() == 0 && voicetype::tsf::ServerLocks() == 0 &&
                   voicetype::tsf::ActiveWorkerCount() == 0
               ? S_OK
               : S_FALSE;
}

extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID clsid, REFIID riid, void** object) {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (clsid != voicetype::tsf::VoiceTypeTextServiceClsid()) {
        return CLASS_E_CLASSNOTAVAILABLE;
    }
    auto* factory = new (std::nothrow) voicetype::tsf::VoiceTypeClassFactory();
    if (!factory) {
        return E_OUTOFMEMORY;
    }
    const HRESULT hr = factory->QueryInterface(riid, object);
    factory->Release();
    return hr;
}

extern "C" HRESULT __stdcall DllRegisterServer() {
    return voicetype::tsf::RegisterComServer(g_module);
}

extern "C" HRESULT __stdcall DllUnregisterServer() {
    return voicetype::tsf::UnregisterComServer();
}
