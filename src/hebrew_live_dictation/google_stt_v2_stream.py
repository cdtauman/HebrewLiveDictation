import logging
import json
import os
import queue
import threading
import time

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError
from google.protobuf.duration_pb2 import Duration

from .language_packs import merge_transcript_segments
from .stt.base import ProviderCapabilities, SpeechClientBase


logger = logging.getLogger("GoogleSTTV2Stream")


def safe_path_for_log(path: str) -> str:
    if not path:
        return ""
    return f"<redacted>/{os.path.basename(path)}"


def infer_project_id_from_credentials(config):
    project_id = (config.get("google.project_id", "") or "").strip()
    if project_id:
        return project_id

    credential_mode = config.get("google.credential_mode", "service_account_json")
    if credential_mode == "adc":
        try:
            import google.auth

            _, adc_project_id = google.auth.default()
            return adc_project_id or ""
        except Exception as e:
            logger.warning("Could not infer Google project ID from ADC: %s", e)
            return ""

    creds_path = config.get("google.credentials_path", "") or config.get("google_credentials_path", "")
    if not creds_path:
        return ""

    creds_path = creds_path.strip('"\'')
    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("project_id", "") or "").strip()
    except Exception as e:
        logger.warning("Could not infer Google project ID from credentials JSON: %s", e)
        return ""


class GoogleSTTV2Stream(SpeechClientBase):
    capabilities = ProviderCapabilities(
        name="google_v2",
        streaming=True,
        batch=False,
        interim=True,
        offline=False,
        fallback_target=False,
        needs_credentials=True,
    )

    def __init__(self, config, on_event_callback=None):
        super().__init__(config, on_event_callback)
        self.client = None
        self.thread = None
        self.audio_queue = None
        self._using_fallback = False
        self._active_location = None
        self._active_model = None
        self._response_count = 0
        self._final_count = 0
        self._interim_event_count = 0
        self._interim_segment_count = 0
        self._force_restart_flag = False

    def restart_stream(self):
        """Forces the current streaming connection to close and immediately open a new one."""
        self._force_restart_flag = True
        if self.audio_queue:
            self.audio_queue.put(b"") # wake up generator

    def _setup_credentials(self):
        credential_mode = self.config.get("google.credential_mode", "service_account_json")
        creds_path = self.config.get("google.credentials_path", "") or self.config.get("google_credentials_path", "")

        if credential_mode == "adc":
            logger.info("Using Google Application Default Credentials.")
            return

        if creds_path:
            creds_path = creds_path.strip('"\'')
            if os.path.exists(creds_path):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
                logger.info("Using Google credentials from config: %s", safe_path_for_log(creds_path))
                return
            raise FileNotFoundError(f"Google credentials file not found: {safe_path_for_log(creds_path)}")

        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            logger.info(
                "Using Google credentials from environment variable: %s",
                safe_path_for_log(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]),
            )
            return

        raise ValueError("Google credentials are not configured. Use a Service Account JSON path or ADC.")

    def start(self, audio_queue):
        self._setup_credentials()

        location = self.config.get("google.location", "eu")
        self._active_location = location
        self._active_model = self.config.get("google.model", "chirp_3")
        self._using_fallback = False
        self._response_count = 0
        self._final_count = 0
        self._interim_event_count = 0
        self._interim_segment_count = 0
        self.client = self._create_client(location)
        self.audio_queue = audio_queue
        self.active = True
        self.thread = threading.Thread(target=self._run_stream, daemon=True)
        self.thread.start()
        logger.info("Google STT V2 streaming thread started.")

    def stop(self):
        self.active = False
        if self.audio_queue:
            self.audio_queue.put(None)
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        logger.info("Google STT V2 streaming thread stopped.")

    def _recognizer_name(self):
        project_id = infer_project_id_from_credentials(self.config)
        location = self._active_location or self.config.get("google.location", "eu")
        recognizer_id = self.config.get("google.recognizer_id", "_") or "_"
        if not project_id:
            raise ValueError(
                "Google project ID is required for Speech-to-Text V2. "
                "Enter it in Google settings or use a service account JSON that contains project_id."
            )
        return f"projects/{project_id}/locations/{location}/recognizers/{recognizer_id}"

    def _create_client(self, location):
        from google.cloud.speech_v2 import SpeechClient

        client_options = None
        if location and location not in ("global", "_"):
            client_options = ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
        return SpeechClient(client_options=client_options)

    def _recognition_config(self):
        from google.cloud.speech_v2.types import cloud_speech

        raw_language_codes = [self.config.get("languages.primary", "iw-IL")]
        for code in self.config.get("languages.alternatives", []) or []:
            if code: raw_language_codes.append(code)

        custom_code = self.config.get("languages.custom_code", "")
        if custom_code: raw_language_codes.append(custom_code)

        language_codes = []
        normalized_seen = set()
        for code in raw_language_codes:
            norm = code.replace("he-IL", "iw-IL").replace("he-", "iw-").lower()
            if norm not in normalized_seen:
                normalized_seen.add(norm)
                language_codes.append(code)

        location = self._active_location or self.config.get("google.location", "eu")
        if location not in ("eu", "us", "global") and len(language_codes) > 1:
            logger.warning("Location '%s' does not support multiple languages. Truncating language codes.", location)
            language_codes = language_codes[:1]

        active_model = self._active_model or self.config.get("google.model", "chirp_3")
        is_chirp = "chirp" in active_model.lower()

        features_kwargs = {
            "enable_automatic_punctuation": self.config.get("google.automatic_punctuation", True),
            "profanity_filter": False,
        }

        if not is_chirp:
            features_kwargs["enable_spoken_punctuation"] = self.config.get("google.enable_spoken_punctuation", False)
            features_kwargs["enable_spoken_emojis"] = self.config.get("google.enable_spoken_emoji", False)

        features = cloud_speech.RecognitionFeatures(**features_kwargs)

        adaptation = self._adaptation_config(cloud_speech)
        kwargs = {
            "explicit_decoding_config": cloud_speech.ExplicitDecodingConfig(
                encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.config.get("audio.sample_rate", 16000),
                audio_channel_count=1,
            ),
            "language_codes": language_codes,
            "model": self._active_model or self.config.get("google.model", "chirp_3"),
            "features": features,
        }
        if adaptation:
            kwargs["adaptation"] = adaptation

        logger.info(
            "Google STT V2 config: model=%s, location=%s, languages=%s",
            kwargs["model"],
            self._active_location or self.config.get("google.location", "eu"),
            language_codes,
        )
        return cloud_speech.RecognitionConfig(**kwargs)

    def _streaming_features(self):
        from google.cloud.speech_v2.types import cloud_speech

        kwargs = {
            "interim_results": self.config.get("google.interim_results", True),
        }

        if self.config.get("speech.endpointing", True):
            kwargs["enable_voice_activity_events"] = True

            if self.config.get("speech.auto_stop_on_silence", False):
                start_timeout = self._duration_from_seconds(
                    float(self.config.get("speech.speech_start_timeout_seconds", 5.0))
                )
                end_timeout = self._duration_from_seconds(
                    float(self.config.get("speech.speech_end_timeout_seconds", 1.0))
                )
                kwargs["voice_activity_timeout"] = cloud_speech.StreamingRecognitionFeatures.VoiceActivityTimeout(
                    speech_start_timeout=start_timeout,
                    speech_end_timeout=end_timeout,
                )

        return cloud_speech.StreamingRecognitionFeatures(**kwargs)

    def _switch_to_fallback(self):
        if self._using_fallback:
            return False

        fallback_location = self.config.get("google.fallback_location", "")
        fallback_model = self.config.get("google.fallback_model", "")
        current_location = self._active_location or self.config.get("google.location", "eu")
        current_model = self._active_model or self.config.get("google.model", "chirp_3")

        if not fallback_location or not fallback_model:
            return False
        if fallback_location == current_location and fallback_model == current_model:
            return False

        logger.warning(
            "Switching Google STT V2 to fallback location/model: %s / %s",
            fallback_location,
            fallback_model,
        )
        self._active_location = fallback_location
        self._active_model = fallback_model
        self._using_fallback = True
        self.client = self._create_client(fallback_location)
        self._emit_event(
            {
                "type": "status",
                "message": f"Using Google fallback: {fallback_location} / {fallback_model}",
            }
        )
        return True

    def _adaptation_config(self, cloud_speech):
        phrases = self.config.get("languages.custom_phrases", []) or []
        phrases = [str(phrase).strip() for phrase in phrases if str(phrase).strip()]
        if not phrases:
            return None

        boost = float(self.config.get("google.phrase_boost", 15.0))
        phrase_set = cloud_speech.PhraseSet(
            phrases=[cloud_speech.PhraseSet.Phrase(value=phrase, boost=boost) for phrase in phrases],
            boost=boost,
        )
        return cloud_speech.SpeechAdaptation(
            phrase_sets=[cloud_speech.SpeechAdaptation.AdaptationPhraseSet(inline_phrase_set=phrase_set)]
        )

    def _request_generator(self):
        from google.cloud.speech_v2.types import cloud_speech

        recognizer = self._recognizer_name()
        streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=self._recognition_config(),
            streaming_features=self._streaming_features(),
        )

        yield cloud_speech.StreamingRecognizeRequest(
            recognizer=recognizer,
            streaming_config=streaming_config,
        )

        chunk_count = 0
        stream_started_at = time.monotonic()
        max_stream_seconds = int(self.config.get("speech.max_stream_seconds", 285))
        while self.active and not getattr(self, "_force_restart_flag", False):
            if time.monotonic() - stream_started_at >= max_stream_seconds:
                logger.info("V2 stream reached max_stream_seconds=%s; rotating stream.", max_stream_seconds)
                break
            try:
                chunk = self.audio_queue.get(timeout=0.5)
                if chunk is None:
                    break
                if chunk == b"":
                    continue # wakeup signal

                chunk_count += 1
                if chunk_count <= 5:
                    logger.info("V2 audio chunk #%s: %s bytes", chunk_count, len(chunk))

                for audio_chunk in self._bounded_audio_chunks(chunk):
                    yield cloud_speech.StreamingRecognizeRequest(audio=audio_chunk)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in V2 audio request generator: {e}")
                break

    def _stream_once(self):
        responses = self.client.streaming_recognize(requests=self._request_generator())
        response_count = 0
        for response in responses:
            if not self.active:
                break

            response_count += 1
            logger.info("Received V2 response #%s, results count: %s", response_count, len(response.results))
            self._emit_speech_activity_event(response)

            interim_texts = []
            for result in response.results:
                if not result.alternatives:
                    continue

                alt = result.alternatives[0]
                transcript = alt.transcript
                confidence = getattr(alt, "confidence", 0.0)

                if result.is_final:
                    self._final_count += 1
                    self._emit_event({"type": "final", "text": transcript, "confidence": confidence})
                else:
                    interim_texts.append(transcript)

            if interim_texts:
                self._interim_segment_count += len(interim_texts)
                self._emit_event(
                    {
                        "type": "interim",
                        "text": merge_transcript_segments(
                            interim_texts,
                            self.config.get("languages.primary", "iw-IL"),
                            self.config.get("languages.command_pack", "he"),
                        ),
                        "confidence": 0.0,
                    }
                )
                self._interim_event_count += 1
            self._response_count += 1
        return response_count

    @staticmethod
    def _bounded_audio_chunks(chunk: bytes, limit: int = 24000):
        if len(chunk) <= limit:
            yield chunk
            return
        for start in range(0, len(chunk), limit):
            yield chunk[start : start + limit]

    @staticmethod
    def _duration_from_seconds(value: float) -> Duration:
        duration = Duration()
        whole_seconds = int(value)
        duration.seconds = whole_seconds
        duration.nanos = int((value - whole_seconds) * 1_000_000_000)
        return duration

    def _emit_speech_activity_event(self, response):
        event_type = getattr(response, "speech_event_type", None)
        if not event_type:
            return

        name = getattr(event_type, "name", str(event_type))
        if "BEGIN" in name or "START" in name:
            self._emit_event({"type": "speech_start", "message": "Speech activity started."})
        elif "END" in name:
            self._emit_event({"type": "speech_end", "message": "Speech activity ended."})

    def _run_stream(self):
        total_response_count = 0
        restart_count = 0
        try:
            while self.active:
                try:
                    self._force_restart_flag = False
                    stream_response_count = self._stream_once()
                    total_response_count += stream_response_count
                    if not self.active:
                        break
                    if stream_response_count == 0:
                        restart_count += 1
                        if not self.config.get("speech.auto_stop_on_silence", False) and restart_count <= 3:
                            logger.warning(
                                "Google STT V2 stream returned no responses while auto-stop is disabled; "
                                "restarting stream #%s.",
                                restart_count,
                            )
                            self._emit_event({"type": "status", "message": "Google stream restarted."})
                            time.sleep(0.2)
                            continue
                        logger.warning("No Google STT V2 responses were received during this session.")
                        self._emit_event(
                            {
                                "type": "error",
                                "message": (
                                    "Google Speech-to-Text V2 connected but returned no recognition responses. "
                                    "Check the selected model, region, recognizer, microphone audio, and project permissions."
                                ),
                            }
                        )
                        break
                    restart_count += 1
                    logger.warning(
                        "Google STT V2 stream ended while dictation is still active; restarting stream #%s.",
                        restart_count,
                    )
                    self._emit_event({"type": "status", "message": "Google stream restarted."})
                    time.sleep(0.2)
                except GoogleAPICallError as e:
                    if self._switch_to_fallback():
                        continue
                    logger.error(f"Google STT V2 API error: {e}")
                    self._emit_event({"type": "error", "message": f"Google STT V2 API error: {e.message}"})
                    break
        except Exception as e:
            logger.error(f"Google STT V2 unexpected error: {e}")
            self._emit_event({"type": "error", "message": f"Unexpected V2 error: {str(e)}"})
        finally:
            self.active = False
            logger.info(
                "Google STT V2 stream summary: responses=%s finals=%s interim_events=%s interim_segments=%s model=%s location=%s fallback=%s.",
                self._response_count,
                self._final_count,
                self._interim_event_count,
                self._interim_segment_count,
                self._active_model,
                self._active_location,
                self._using_fallback,
            )
            logger.info("Google STT V2 streaming thread exiting.")
