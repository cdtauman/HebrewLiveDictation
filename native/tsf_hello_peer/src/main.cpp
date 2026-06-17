#include "voice_type_tsf_hello_peer.h"
#include "voice_type_tsf_registration.h"

#include <Windows.h>

#include <cstdlib>
#include <cwchar>
#include <iostream>
#include <string>

using voicetype::tsf::HandshakeConfig;
using voicetype::tsf::HelloPeer;
using voicetype::tsf::HelloStatus;
using voicetype::tsf::RegistrationAction;
using voicetype::tsf::RegistrationPlan;
using voicetype::tsf::ToString;
using voicetype::tsf::ApplyRegistrationPlan;

namespace {

std::string WideToUtf8(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }
    const int size = WideCharToMultiByte(CP_UTF8, 0, value.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) {
        return {};
    }
    std::string output(static_cast<size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.c_str(), -1, output.data(), size, nullptr, nullptr);
    return output;
}

bool ArgEquals(const wchar_t* arg, const wchar_t* expected) {
    return arg && expected && wcscmp(arg, expected) == 0;
}

void PrintUsage() {
    std::wcerr << L"Usage: VoiceTypeTsfHelloPeer.exe --pipe <pipe> --session <id> --nonce <nonce> "
                  L"[--timeout-ms 150]\n"
                  L"       VoiceTypeTsfHelloPeer.exe --register-tsf [--commit-registration "
                  L"--i-understand-experimental-tsf-registration]\n"
                  L"       VoiceTypeTsfHelloPeer.exe --unregister-tsf [--commit-registration "
                  L"--i-understand-experimental-tsf-registration]\n";
}

enum class CommandMode {
    Handshake,
    RegisterTsf,
    UnregisterTsf,
};

struct ParsedArgs {
    CommandMode mode = CommandMode::Handshake;
    HandshakeConfig handshake;
    RegistrationPlan registration;
};

bool ParseArgs(int argc, wchar_t** argv, ParsedArgs* args) {
    for (int i = 1; i < argc; ++i) {
        if (ArgEquals(argv[i], L"--pipe") && i + 1 < argc) {
            args->handshake.pipeName = argv[++i];
        } else if (ArgEquals(argv[i], L"--session") && i + 1 < argc) {
            args->handshake.sessionId = WideToUtf8(argv[++i]);
        } else if (ArgEquals(argv[i], L"--nonce") && i + 1 < argc) {
            args->handshake.nonce = WideToUtf8(argv[++i]);
        } else if (ArgEquals(argv[i], L"--timeout-ms") && i + 1 < argc) {
            args->handshake.timeoutMs = static_cast<DWORD>(std::wcstoul(argv[++i], nullptr, 10));
        } else if (ArgEquals(argv[i], L"--register-tsf")) {
            args->mode = CommandMode::RegisterTsf;
            args->registration.action = RegistrationAction::Register;
        } else if (ArgEquals(argv[i], L"--unregister-tsf")) {
            args->mode = CommandMode::UnregisterTsf;
            args->registration.action = RegistrationAction::Unregister;
        } else if (ArgEquals(argv[i], L"--commit-registration")) {
            args->registration.dryRun = false;
        } else if (ArgEquals(argv[i], L"--i-understand-experimental-tsf-registration")) {
            args->registration.explicitExperimentalConsent = true;
        } else {
            return false;
        }
    }
    if (args->mode == CommandMode::RegisterTsf || args->mode == CommandMode::UnregisterTsf) {
        return true;
    }
    return !args->handshake.pipeName.empty() && !args->handshake.sessionId.empty() && !args->handshake.nonce.empty();
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    ParsedArgs args;
    if (!ParseArgs(argc, argv, &args)) {
        PrintUsage();
        return 2;
    }

    if (args.mode == CommandMode::RegisterTsf || args.mode == CommandMode::UnregisterTsf) {
        const auto result = ApplyRegistrationPlan(args.registration);
        const bool ok = SUCCEEDED(result.hr);
        std::wcout << L"{\"ok\":" << (ok ? L"true" : L"false") << L",\"dry_run\":"
                   << (args.registration.dryRun ? L"true" : L"false") << L",\"changed_system_state\":"
                   << (result.changedSystemState ? L"true" : L"false") << L",\"hr\":" << result.hr << L"}\n";
        return ok ? 0 : 1;
    }

    const HandshakeConfig& config = args.handshake;
    HelloPeer peer;
    if (!peer.StartAsync(config)) {
        std::wcerr << L"{\"ok\":false,\"status\":\"start_failed\"}\n";
        return 3;
    }

    const DWORD waitBudgetMs = config.timeoutMs + 500;
    peer.WaitForCompletionForTest(waitBudgetMs);
    const auto result = peer.LastResult();
    const bool ok = result.status == HelloStatus::Connected;
    std::wcout << L"{\"ok\":" << (ok ? L"true" : L"false") << L",\"status\":\"" << ToString(result.status)
               << L"\",\"win32_error\":" << result.win32Error << L"}\n";
    return ok ? 0 : 1;
}
