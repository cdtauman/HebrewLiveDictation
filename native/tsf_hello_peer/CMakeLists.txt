cmake_minimum_required(VERSION 3.21)

project(VoiceTypeTsfHelloPeer LANGUAGES CXX)

add_executable(VoiceTypeTsfHelloPeer
    src/main.cpp
    src/voice_type_tsf_composition.cpp
    src/voice_type_tsf_composition.h
    src/voice_type_tsf_hello_peer.cpp
    src/voice_type_tsf_hello_peer.h
    src/voice_type_tsf_protocol.cpp
    src/voice_type_tsf_protocol.h
    src/voice_type_tsf_registration.cpp
    src/voice_type_tsf_registration.h
    src/voice_type_tsf_runtime.cpp
    src/voice_type_tsf_runtime.h
)

target_compile_features(VoiceTypeTsfHelloPeer PRIVATE cxx_std_17)
target_compile_definitions(VoiceTypeTsfHelloPeer PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)

if(MSVC)
    target_compile_options(VoiceTypeTsfHelloPeer PRIVATE /W4 /permissive- /EHsc)
endif()

target_link_libraries(VoiceTypeTsfHelloPeer PRIVATE msctf ole32 oleaut32)

add_library(VoiceTypeTsfTextService SHARED
    src/dllmain.cpp
    src/voice_type_tsf_composition.cpp
    src/voice_type_tsf_composition.h
    src/voice_type_tsf_hello_peer.cpp
    src/voice_type_tsf_hello_peer.h
    src/voice_type_tsf_protocol.cpp
    src/voice_type_tsf_protocol.h
    src/voice_type_tsf_registration.cpp
    src/voice_type_tsf_registration.h
    src/voice_type_tsf_runtime.cpp
    src/voice_type_tsf_runtime.h
    src/voice_type_tsf_text_service.cpp
    src/voice_type_tsf_text_service.h
)

target_compile_features(VoiceTypeTsfTextService PRIVATE cxx_std_17)
target_compile_definitions(VoiceTypeTsfTextService PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX VOICETYPE_TSF_DLL)

if(MSVC)
    target_compile_options(VoiceTypeTsfTextService PRIVATE /W4 /permissive- /EHsc)
endif()

target_link_libraries(VoiceTypeTsfTextService PRIVATE msctf ole32 oleaut32 advapi32 shell32)
