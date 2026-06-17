#include "voice_type_tsf_text_service.h"

#include "voice_type_tsf_registration.h"

#include <ShlObj.h>
#include <strsafe.h>

#include <string>
#include <string_view>
#include <new>
#include <utility>

namespace voicetype::tsf {
namespace {

std::atomic<long> g_comObjects{0};
std::atomic<long> g_serverLocks{0};

void ReleaseIfSet(IUnknown* value) noexcept {
    if (value) {
        value->Release();
    }
}

std::wstring GuidToString(REFGUID guid) {
    wchar_t buffer[64] = {};
    StringFromGUID2(guid, buffer, 64);
    return buffer;
}

bool ReadWholeFile(const std::wstring& path, std::string* output) noexcept {
    if (!output) {
        return false;
    }
    output->clear();
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return false;
    }
    LARGE_INTEGER size = {};
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 0 || size.QuadPart > 64 * 1024) {
        CloseHandle(file);
        return false;
    }
    output->resize(static_cast<size_t>(size.QuadPart));
    DWORD read = 0;
    const BOOL ok = ReadFile(file, output->data(), static_cast<DWORD>(output->size()), &read, nullptr);
    CloseHandle(file);
    if (!ok || read != output->size()) {
        output->clear();
        return false;
    }
    return true;
}

std::wstring SessionAdvertisementPath() {
    wchar_t appData[MAX_PATH] = {};
    if (FAILED(SHGetFolderPathW(nullptr, CSIDL_APPDATA, nullptr, SHGFP_TYPE_CURRENT, appData))) {
        return {};
    }
    std::wstring path(appData);
    path += L"\\VoiceType\\tsf_session.json";
    return path;
}

HRESULT SetStringValue(HKEY key, const wchar_t* name, const std::wstring& value) noexcept {
    return RegSetValueExW(
               key,
               name,
               0,
               REG_SZ,
               reinterpret_cast<const BYTE*>(value.c_str()),
               static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t))) == ERROR_SUCCESS
               ? S_OK
               : E_FAIL;
}

}  // namespace

VoiceTypeTextService::VoiceTypeTextService() noexcept {
    g_comObjects.fetch_add(1, std::memory_order_acq_rel);
}

VoiceTypeTextService::~VoiceTypeTextService() noexcept {
    Deactivate();
    g_comObjects.fetch_sub(1, std::memory_order_acq_rel);
}

HRESULT VoiceTypeTextService::QueryInterface(REFIID riid, void** object) noexcept {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == IID_ITfTextInputProcessor || riid == IID_ITfTextInputProcessorEx) {
        *object = static_cast<ITfTextInputProcessorEx*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}

ULONG VoiceTypeTextService::AddRef() noexcept {
    return refCount_.fetch_add(1, std::memory_order_relaxed) + 1;
}

ULONG VoiceTypeTextService::Release() noexcept {
    const ULONG count = refCount_.fetch_sub(1, std::memory_order_acq_rel) - 1;
    if (count == 0) {
        delete this;
    }
    return count;
}

HRESULT VoiceTypeTextService::Activate(ITfThreadMgr* threadMgr, TfClientId clientId) noexcept {
    return ActivateEx(threadMgr, clientId, 0);
}

HRESULT VoiceTypeTextService::ActivateEx(ITfThreadMgr* threadMgr, TfClientId clientId, DWORD) noexcept {
    if (!threadMgr) {
        return E_INVALIDARG;
    }
    Deactivate();
    threadMgr_ = threadMgr;
    threadMgr_->AddRef();
    clientId_ = clientId;

    HandshakeConfig config;
    if (LoadAdvertisedHandshake(&config)) {
        peer_.StartAsync(config, &VoiceTypeTextService::OnNativeMessage, this);
    }
    return S_OK;
}

HRESULT VoiceTypeTextService::Deactivate() noexcept {
    peer_.Deactivate();
    runtime_.Detach();
    ReleaseIfSet(std::exchange(threadMgr_, nullptr));
    clientId_ = 0;
    return S_OK;
}

void VoiceTypeTextService::OnNativeMessage(const WireMessage& message, void* context) noexcept {
    if (context) {
        static_cast<VoiceTypeTextService*>(context)->HandleNativeMessage(message);
    }
}

void VoiceTypeTextService::HandleNativeMessage(const WireMessage& message) noexcept {
    if (!AttachFocusedContext()) {
        return;
    }
    runtime_.Enqueue(message);
}

bool VoiceTypeTextService::AttachFocusedContext() noexcept {
    if (!threadMgr_ || clientId_ == 0) {
        return false;
    }
    ITfDocumentMgr* documentMgr = nullptr;
    if (FAILED(threadMgr_->GetFocus(&documentMgr)) || !documentMgr) {
        return false;
    }
    ITfContext* context = nullptr;
    const HRESULT hr = documentMgr->GetTop(&context);
    documentMgr->Release();
    if (FAILED(hr) || !context) {
        return false;
    }
    runtime_.Attach(context, clientId_, TF_INVALID_GUIDATOM);
    context->Release();
    return true;
}

HRESULT VoiceTypeClassFactory::QueryInterface(REFIID riid, void** object) noexcept {
    if (!object) {
        return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == IID_IClassFactory) {
        *object = static_cast<IClassFactory*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}

ULONG VoiceTypeClassFactory::AddRef() noexcept {
    return refCount_.fetch_add(1, std::memory_order_relaxed) + 1;
}

ULONG VoiceTypeClassFactory::Release() noexcept {
    const ULONG count = refCount_.fetch_sub(1, std::memory_order_acq_rel) - 1;
    if (count == 0) {
        delete this;
    }
    return count;
}

HRESULT VoiceTypeClassFactory::CreateInstance(IUnknown* outer, REFIID riid, void** object) noexcept {
    if (outer) {
        return CLASS_E_NOAGGREGATION;
    }
    auto* service = new (std::nothrow) VoiceTypeTextService();
    if (!service) {
        return E_OUTOFMEMORY;
    }
    const HRESULT hr = service->QueryInterface(riid, object);
    service->Release();
    return hr;
}

HRESULT VoiceTypeClassFactory::LockServer(BOOL lock) noexcept {
    g_serverLocks.fetch_add(lock ? 1 : -1, std::memory_order_acq_rel);
    return S_OK;
}

HRESULT RegisterComServer(HMODULE module) noexcept {
    wchar_t modulePath[MAX_PATH] = {};
    if (!GetModuleFileNameW(module, modulePath, MAX_PATH)) {
        return E_FAIL;
    }
    const std::wstring clsid = GuidToString(VoiceTypeTextServiceClsid());
    const std::wstring base = L"Software\\Classes\\CLSID\\" + clsid;
    HKEY key = nullptr;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, base.c_str(), 0, nullptr, 0, KEY_WRITE, nullptr, &key, nullptr) != ERROR_SUCCESS) {
        return E_FAIL;
    }
    SetStringValue(key, nullptr, L"VoiceType TSF Text Service");
    HKEY inproc = nullptr;
    HRESULT hr = S_OK;
    if (RegCreateKeyExW(key, L"InprocServer32", 0, nullptr, 0, KEY_WRITE, nullptr, &inproc, nullptr) == ERROR_SUCCESS) {
        hr = SetStringValue(inproc, nullptr, modulePath);
        if (SUCCEEDED(hr)) {
            hr = SetStringValue(inproc, L"ThreadingModel", L"Apartment");
        }
        RegCloseKey(inproc);
    } else {
        hr = E_FAIL;
    }
    RegCloseKey(key);
    if (FAILED(hr)) {
        return hr;
    }
    RegistrationPlan plan;
    plan.dryRun = false;
    plan.explicitExperimentalConsent = true;
    return ApplyRegistrationPlan(plan).hr;
}

HRESULT UnregisterComServer() noexcept {
    RegistrationPlan plan;
    plan.action = RegistrationAction::Unregister;
    plan.dryRun = false;
    plan.explicitExperimentalConsent = true;
    ApplyRegistrationPlan(plan);
    const std::wstring clsid = GuidToString(VoiceTypeTextServiceClsid());
    const std::wstring base = L"Software\\Classes\\CLSID\\" + clsid;
    RegDeleteTreeW(HKEY_CURRENT_USER, base.c_str());
    return S_OK;
}

bool LoadAdvertisedHandshake(HandshakeConfig* config) noexcept {
    if (!config) {
        return false;
    }
    std::string json;
    if (!ReadWholeFile(SessionAdvertisementPath(), &json)) {
        return false;
    }
    std::string pipeUtf8;
    std::string sessionId;
    std::string nonce;
    uint64_t timeoutMs = 100;
    if (!TryGetJsonString(json, "pipe_name", &pipeUtf8) || !TryGetJsonString(json, "session_id", &sessionId) ||
        !TryGetJsonString(json, "nonce", &nonce)) {
        return false;
    }
    TryGetJsonUInt64(json, "timeout_ms", &timeoutMs);
    std::wstring pipeName;
    if (!Utf8ToWideStrict(pipeUtf8, &pipeName)) {
        return false;
    }
    config->pipeName = pipeName;
    config->sessionId = sessionId;
    config->nonce = nonce;
    config->timeoutMs = static_cast<DWORD>(timeoutMs);
    return true;
}

long ActiveComObjects() noexcept {
    return g_comObjects.load(std::memory_order_acquire);
}

long ServerLocks() noexcept {
    return g_serverLocks.load(std::memory_order_acquire);
}

}  // namespace voicetype::tsf
