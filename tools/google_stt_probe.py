#!/usr/bin/env python
"""Dev-only Google Speech-to-Text V2 probe for HebrewLiveDictation.

This tool is intentionally not wired into the app UI. It sends a known WAV file
to Google STT V2 using the same streaming request shape as the app and prints raw
response details without printing credential contents.

Exit codes:
  0 = non-empty transcript
  2 = connected but empty transcription
  3 = Google API error
  4 = local config/audio error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech


EXIT_TRANSCRIPT = 0
EXIT_EMPTY = 2
EXIT_GOOGLE_API = 3
EXIT_LOCAL = 4
MAX_AUDIO_BYTES = 12000


@dataclass(frozen=True)
class ProbeCase:
    location: str
    model: str
    language: str
    recognizer: str


def _basename(path: str) -> str:
    return Path(path).name if path else ""


def _infer_project_from_credentials(creds_path: str) -> str:
    if not creds_path:
        return ""
    with open(creds_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return str(data.get("project_id", "") or "").strip()


def _load_wav(path: str) -> tuple[bytes, int]:
    wav_path = Path(path)
    if not wav_path.exists():
        raise ValueError(f"WAV file not found: {wav_path}")
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.getnframes()
        if channels != 1:
            raise ValueError(f"WAV must be mono; got {channels} channels")
        if sample_width != 2:
            raise ValueError(f"WAV must be 16-bit PCM; got sample width {sample_width} bytes")
        audio = wf.readframes(frames)
    if not audio:
        raise ValueError("WAV contains no audio frames")
    return audio, sample_rate


def _chunks(audio: bytes, max_bytes: int = MAX_AUDIO_BYTES) -> Iterable[bytes]:
    for start in range(0, len(audio), max_bytes):
        yield audio[start : start + max_bytes]


def _client(location: str) -> SpeechClient:
    if location and location not in ("global", "_"):
        return SpeechClient(client_options=ClientOptions(api_endpoint=f"{location}-speech.googleapis.com"))
    return SpeechClient()


def _recognizer(project: str, case: ProbeCase) -> str:
    rid = case.recognizer or "_"
    return f"projects/{project}/locations/{case.location}/recognizers/{rid}"


def _recognition_config(case: ProbeCase, sample_rate: int) -> cloud_speech.RecognitionConfig:
    features_kwargs = {}
    if "chirp" in case.model.lower():
        features_kwargs["enable_automatic_punctuation"] = True
    return cloud_speech.RecognitionConfig(
        explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            audio_channel_count=1,
        ),
        language_codes=[case.language],
        model=case.model,
        features=cloud_speech.RecognitionFeatures(**features_kwargs),
    )


def _display_text(text: str) -> str:
    try:
        return text.encode("unicode_escape").decode("ascii")
    except Exception:
        return repr(text)


def _response_error(response) -> str:
    try:
        pb = getattr(response, "_pb", None)
        if pb is not None:
            try:
                if not pb.HasField("error"):
                    return ""
            except Exception:
                return ""
        error = getattr(response, "error", None)
        code = getattr(error, "code", 0) if error is not None else 0
        message = getattr(error, "message", "") if error is not None else ""
        details = getattr(error, "details", None) if error is not None else None
        if not code and not message and not details:
            return ""
        parts = [f"code={code}"]
        if message:
            parts.append(f"message={message}")
        if details:
            parts.append(f"details={details}")
        return " ".join(parts)
    except Exception:
        return ""


def _google_exception_text(exc: Exception) -> str:
    parts = [type(exc).__name__]
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            parts.append(f"code={code()}")
        except Exception:
            pass
    message = getattr(exc, "message", None) or str(exc)
    if message:
        parts.append(f"message={message}")
    details = getattr(exc, "details", None)
    if details:
        parts.append(f"details={details}")
    return " ".join(parts)


def run_streaming_case(project: str, case: ProbeCase, audio: bytes, sample_rate: int, timeout: float) -> int:
    recognizer_path = _recognizer(project, case)
    print()
    print("=== STREAMING CASE ===")
    print(f"recognizer={recognizer_path}")
    print(f"model={case.model}")
    print(f"location={case.location}")
    print(f"language={case.language}")
    print("encoding=LINEAR16")
    print(f"sample_rate={sample_rate}")
    print(f"audio_bytes={len(audio)}")
    print(f"chunk_limit={MAX_AUDIO_BYTES}")

    client = _client(case.location)
    config = _recognition_config(case, sample_rate)

    def requests():
        yield cloud_speech.StreamingRecognizeRequest(
            recognizer=recognizer_path,
            streaming_config=cloud_speech.StreamingRecognitionConfig(
                config=config,
                streaming_features=cloud_speech.StreamingRecognitionFeatures(
                    interim_results=True,
                    enable_voice_activity_events=True,
                ),
            ),
        )
        for chunk in _chunks(audio):
            yield cloud_speech.StreamingRecognizeRequest(audio=chunk)

    transcripts: list[str] = []
    response_count = 0
    result_count = 0
    final_count = 0
    interim_count = 0
    try:
        for response in client.streaming_recognize(requests=requests(), timeout=timeout):
            response_count += 1
            error = _response_error(response)
            speech_event = getattr(response, "speech_event_type", None)
            event_name = getattr(speech_event, "name", str(speech_event)) if speech_event else ""
            print(f"response #{response_count}: results={len(response.results)} speech_event_type={event_name}")
            if error:
                print(f"  response.error: {error}")
                return EXIT_GOOGLE_API
            for result_index, result in enumerate(response.results, start=1):
                result_count += 1
                stability = getattr(result, "stability", 0.0)
                print(
                    f"  result #{result_index}: final={bool(result.is_final)} "
                    f"stability={stability} alternatives={len(result.alternatives)}"
                )
                if result.is_final:
                    final_count += 1
                else:
                    interim_count += 1
                for alt_index, alt in enumerate(result.alternatives, start=1):
                    transcript = alt.transcript or ""
                    confidence = getattr(alt, "confidence", 0.0)
                    print(
                        f"    alt #{alt_index}: transcript={transcript!r} "
                        f"transcript_escaped={_display_text(transcript)!r} confidence={confidence}"
                    )
                    if transcript.strip():
                        transcripts.append(transcript.strip())
    except GoogleAPICallError as exc:
        print(f"Google API exception: {_google_exception_text(exc)}")
        return EXIT_GOOGLE_API
    except Exception as exc:
        print(f"Google/local exception: {_google_exception_text(exc)}")
        return EXIT_GOOGLE_API

    print(
        "stream summary: "
        f"responses={response_count} results={result_count} finals={final_count} "
        f"interims={interim_count} non_empty_transcripts={len(transcripts)}"
    )
    if transcripts:
        print("PASS transcript:")
        print(" ".join(transcripts))
        print("PASS transcript escaped:")
        print(_display_text(" ".join(transcripts)))
        return EXIT_TRANSCRIPT
    print("FAIL connected but empty transcription")
    return EXIT_EMPTY


def run_sync_compare(project: str, case: ProbeCase, audio: bytes, sample_rate: int, timeout: float) -> int:
    recognizer_path = _recognizer(project, case)
    print()
    print("=== SYNC RECOGNIZE COMPARE ===")
    print(f"recognizer={recognizer_path}")
    client = _client(case.location)
    try:
        response = client.recognize(
            request=cloud_speech.RecognizeRequest(
                recognizer=recognizer_path,
                config=_recognition_config(case, sample_rate),
                content=audio,
            ),
            timeout=timeout,
        )
    except GoogleAPICallError as exc:
        print(f"sync Google API exception: {_google_exception_text(exc)}")
        return EXIT_GOOGLE_API
    except Exception as exc:
        print(f"sync Google/local exception: {_google_exception_text(exc)}")
        return EXIT_GOOGLE_API

    transcripts = []
    final_count = 0
    interim_count = 0
    print(f"sync results={len(response.results)}")
    for result_index, result in enumerate(response.results, start=1):
        if getattr(result, "is_final", True):
            final_count += 1
        else:
            interim_count += 1
        print(f"  result #{result_index}: alternatives={len(result.alternatives)}")
        for alt_index, alt in enumerate(result.alternatives, start=1):
            transcript = alt.transcript or ""
            confidence = getattr(alt, "confidence", 0.0)
            print(
                f"    alt #{alt_index}: transcript={transcript!r} "
                f"transcript_escaped={_display_text(transcript)!r} confidence={confidence}"
            )
            if transcript.strip():
                transcripts.append(transcript.strip())
    print(f"sync summary: results={len(response.results)} finals={final_count} interims={interim_count}")
    if transcripts:
        print("SYNC PASS transcript:")
        print(" ".join(transcripts))
        print("SYNC PASS transcript escaped:")
        print(_display_text(" ".join(transcripts)))
        return EXIT_TRANSCRIPT
    print("SYNC FAIL connected but empty transcription")
    return EXIT_EMPTY


def _matrix_cases(recognizer: str) -> list[ProbeCase]:
    return [
        ProbeCase("eu", "chirp_3", "iw-IL", recognizer),
        ProbeCase("us", "chirp_3", "iw-IL", recognizer),
        ProbeCase("eu", "latest_long", "iw-IL", recognizer),
        ProbeCase("us", "latest_long", "iw-IL", recognizer),
        ProbeCase("eu", "latest_long", "he-IL", recognizer),
        ProbeCase("us", "latest_long", "he-IL", recognizer),
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Google STT V2 streaming with a known WAV.")
    parser.add_argument("--creds", help="Service account JSON path. Contents are never printed.")
    parser.add_argument("--adc", action="store_true", help="Use Application Default Credentials instead of --creds.")
    parser.add_argument("--project", help="Google Cloud project ID. Defaults to project_id from --creds.")
    parser.add_argument("--location", default="eu")
    parser.add_argument("--model", default="chirp_3")
    parser.add_argument("--language", default="iw-IL")
    parser.add_argument("--recognizer", default="_")
    parser.add_argument("--wav", required=True, help="Known WAV file, mono 16-bit PCM.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--matrix", action="store_true", help="Run the required R3 rescue model/location/language matrix.")
    parser.add_argument("--sync-compare", action="store_true", help="Also run V2 Recognize for each case.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.adc and args.creds:
        print("Use either --adc or --creds, not both.")
        return EXIT_LOCAL
    if args.creds:
        creds_path = args.creds.strip("\"'")
        if not os.path.exists(creds_path):
            print(f"Credentials file not found: <redacted>/{_basename(creds_path)}")
            return EXIT_LOCAL
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        print(f"credential_mode=service_account_json file=<redacted>/{_basename(creds_path)}")
    elif args.adc:
        print("credential_mode=adc")
    else:
        print("No --creds or --adc supplied. Relying on existing Google environment credentials.")

    try:
        project = (args.project or _infer_project_from_credentials(args.creds or "")).strip()
        if not project:
            print("Project ID missing. Pass --project or use a service account JSON with project_id.")
            return EXIT_LOCAL
        audio, sample_rate = _load_wav(args.wav)
    except Exception as exc:
        print(f"Local config/audio error: {exc}")
        return EXIT_LOCAL

    cases = _matrix_cases(args.recognizer) if args.matrix else [
        ProbeCase(args.location, args.model, args.language, args.recognizer)
    ]
    print(f"project={project}")
    print(f"wav={Path(args.wav).name}")
    print(f"cases={len(cases)}")

    results = []
    for case in cases:
        code = run_streaming_case(project, case, audio, sample_rate, args.timeout)
        if args.sync_compare:
            sync_code = run_sync_compare(project, case, audio, sample_rate, args.timeout)
            if code != EXIT_TRANSCRIPT and sync_code == EXIT_TRANSCRIPT:
                code = sync_code
        results.append((case, code))

    print()
    print("=== MATRIX SUMMARY ===")
    for case, code in results:
        print(f"{case.location}/{case.model}/{case.language}/{case.recognizer}: exit={code}")

    if any(code == EXIT_TRANSCRIPT for _, code in results):
        return EXIT_TRANSCRIPT
    if any(code == EXIT_GOOGLE_API for _, code in results):
        return EXIT_GOOGLE_API
    if all(code == EXIT_LOCAL for _, code in results):
        return EXIT_LOCAL
    return EXIT_EMPTY


if __name__ == "__main__":
    raise SystemExit(main())
