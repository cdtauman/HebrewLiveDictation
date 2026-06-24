import queue
import logging
import re
import audioop

from .vad import VoiceActivityGate

logger = logging.getLogger("AudioStream")


def _sounddevice():
    import sounddevice as sd

    return sd

class AudioStream:
    def __init__(
        self,
        device_id=None,
        sample_rate=16000,
        block_size=1600,
        vad_enabled=False,
        vad_threshold=0.5,
        vad_padding_ms=240,
        vad_min_silence_ms=500,
    ):
        self.device_id = device_id
        self.sample_rate = int(sample_rate or 16000)
        self.block_size = int(block_size or 1600)
        self.stream_sample_rate = self.sample_rate
        self.stream_block_size = self.block_size
        self.queue = queue.Queue()
        self.stream = None
        self._ratecv_state = None
        self._logged_input_chunks = 0
        self._resolved_device = self._resolve_device(device_id)
        frame_ms = int(round((self.block_size / self.sample_rate) * 1000)) if self.sample_rate else 100
        self.vad_gate = (
            VoiceActivityGate(
                frame_ms=frame_ms,
                threshold=vad_threshold,
                padding_ms=vad_padding_ms,
                min_silence_ms=vad_min_silence_ms,
            )
            if vad_enabled
            else None
        )

    def _resolve_device(self, device_id):
        if device_id is None:
            preferred = self._preferred_input_device()
            if preferred is not None:
                logger.info("Resolved Windows default microphone to preferred input index %s.", preferred)
            return preferred
        
        try:
            sd = _sounddevice()
            # If it's already an index
            if isinstance(device_id, int):
                return device_id
            
            # If it's a string, look it up in the device list
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    if device_id.lower() in dev['name'].lower():
                        logger.info(f"Resolved microphone device '{device_id}' to index {i} ({dev['name']})")
                        return i
            logger.warning(f"Could not find microphone device matching '{device_id}'. Using default.")
        except Exception as e:
            logger.error(f"Error resolving microphone device: {e}. Using default.")
        return None

    def start(self):
        # Clear existing items in the queue to start fresh
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self._ratecv_state = None
        if self._start_raw_stream(self.sample_rate, self.block_size):
            self._after_stream_started()
            return True

        fallback_rate = self._device_default_sample_rate()
        if fallback_rate and int(fallback_rate) != self.sample_rate:
            fallback_block_size = max(1, int(int(fallback_rate) * self._frame_ms() / 1000))
            logger.warning(
                "Retrying microphone with device default sample rate. requested=%s fallback=%s",
                self.sample_rate,
                int(fallback_rate),
            )
            if self._start_raw_stream(int(fallback_rate), fallback_block_size):
                self._after_stream_started()
                return True

        return False

    def _start_raw_stream(self, stream_sample_rate: int, stream_block_size: int) -> bool:
        try:
            sd = _sounddevice()
            self.stream_sample_rate = int(stream_sample_rate)
            self.stream_block_size = int(stream_block_size)
            self.stream = sd.RawInputStream(
                samplerate=self.stream_sample_rate,
                blocksize=self.stream_block_size,
                device=self._resolved_device,
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
            )
            self.stream.start()
            return True
        except Exception as e:
            logger.error(
                "Failed to start audio stream at sample_rate=%s block_size=%s: %s",
                stream_sample_rate,
                stream_block_size,
                e,
            )
            self.stream = None
            return False

    def _after_stream_started(self):
        self._logged_input_chunks = 0
        if self.vad_gate:
            self.vad_gate.reset()
        logger.info(
            "Audio stream started. target_sample_rate=%s stream_sample_rate=%s target_block_size=%s stream_block_size=%s vad=%s",
            self.sample_rate,
            self.stream_sample_rate,
            self.block_size,
            self.stream_block_size,
            bool(self.vad_gate),
        )

    def stop(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
                logger.info("Audio stream stopped.")
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")
            finally:
                self.stream = None

    def _audio_callback(self, indata, frames, time, status):
        if status:
            logger.warning(f"Audio stream status warning: {status}")
        chunk = self._convert_to_target_rate(bytes(indata))
        if not chunk:
            return
        self._log_input_level(chunk)
        if self.vad_gate:
            for gated_chunk in self.vad_gate.process(chunk):
                self.queue.put(gated_chunk)
            return
        self.queue.put(chunk)

    def get_queue(self):
        return self.queue

    def _convert_to_target_rate(self, chunk: bytes) -> bytes:
        if self.stream_sample_rate == self.sample_rate:
            return chunk
        try:
            converted, self._ratecv_state = audioop.ratecv(
                chunk,
                2,
                1,
                int(self.stream_sample_rate),
                int(self.sample_rate),
                self._ratecv_state,
            )
            return converted
        except audioop.error as e:
            logger.error("Audio resampling failed: %s", e)
            return b""

    def _frame_ms(self) -> int:
        if not self.sample_rate:
            return 100
        return max(1, int(round((self.block_size / self.sample_rate) * 1000)))

    def _device_default_sample_rate(self) -> int | None:
        try:
            sd = _sounddevice()
            device = sd.query_devices(self._resolved_device, "input")
            rate = int(float(device.get("default_samplerate") or 0))
            return rate if rate > 0 else None
        except Exception as e:
            logger.warning("Could not read microphone default sample rate: %s", e)
            return None
        
    @staticmethod
    def list_devices():
        try:
            sd = _sounddevice()
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_input = AudioStream._preferred_input_device()

            raw_devices = []
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    name = str(dev["name"]).strip()
                    if AudioStream._is_virtual_or_mapper(name):
                        continue

                    hostapi = hostapis[dev.get("hostapi", 0)]["name"] if hostapis else ""
                    raw_devices.append((i, dev, name, hostapi))

            has_wasapi = any("wasapi" in hostapi.lower() for _, _, _, hostapi in raw_devices)
            if has_wasapi:
                raw_devices = [item for item in raw_devices if "wasapi" in item[3].lower()]

            grouped = {}
            for i, dev, name, hostapi in raw_devices:
                normalized = AudioStream._normalize_device_name(name)
                score = AudioStream._device_score(i, hostapi, default_input)
                item = {
                    "index": i,
                    "name": name,
                    "display_name": AudioStream._display_device_name(name, hostapi, i == default_input),
                    "hostapi": hostapi,
                    "default_samplerate": dev['default_samplerate'],
                    "score": score,
                }

                current = grouped.get(normalized)
                if current is None or item["score"] > current["score"]:
                    grouped[normalized] = item

            input_devices = sorted(grouped.values(), key=lambda item: (-item["score"], item["display_name"].lower()))
            for item in input_devices:
                item.pop("score", None)
            return input_devices
        except Exception as e:
            logger.error(f"Error querying audio devices: {e}")
            return []

    @staticmethod
    def _preferred_input_device() -> int | None:
        """Pick the concrete input device for the UI's "Windows default" option.

        PortAudio's bare default can be the legacy MME mapper even when the device list
        exposes a better WASAPI default. Prefer the host API default that matches the
        devices we show to users, then fall back to PortAudio's process default.
        """
        try:
            sd = _sounddevice()
            devices = sd.query_devices()
        except Exception as e:
            logger.warning("Could not resolve preferred input device: %s", e)
            return None
        try:
            hostapis = sd.query_hostapis()
        except Exception:
            hostapis = []

        def system_default() -> int | None:
            try:
                value = sd.default.device[0]
                return int(value) if value is not None and int(value) >= 0 else None
            except Exception:
                return None

        def valid_input(index) -> bool:
            try:
                i = int(index)
                if i < 0 or i >= len(devices):
                    return False
                dev = devices[i]
                return (
                    dev.get("max_input_channels", 0) > 0
                    and not AudioStream._is_virtual_or_mapper(str(dev.get("name", "")))
                )
            except Exception:
                return False

        default_input = system_default()
        candidates = []
        try:
            for hostapi_index, hostapi in enumerate(hostapis or []):
                index = hostapi.get("default_input_device", -1)
                if not valid_input(index):
                    continue
                name = str(hostapi.get("name", "") or "")
                score = 0
                lowered = name.lower()
                if "wasapi" in lowered:
                    score += 1000
                elif "wdm" in lowered:
                    score += 400
                elif "directsound" in lowered:
                    score += 300
                elif "mme" in lowered:
                    score += 100
                if int(index) == default_input:
                    score += 50
                candidates.append((score, int(index), hostapi_index))
        except Exception:
            candidates = []

        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return candidates[0][1]
        if valid_input(default_input):
            return default_input
        try:
            for i, dev in enumerate(devices):
                if valid_input(i):
                    return i
        except Exception:
            pass
        return None

    def _log_input_level(self, chunk: bytes) -> None:
        if self._logged_input_chunks >= 5:
            return
        self._logged_input_chunks += 1
        try:
            rms = audioop.rms(chunk, 2)
            peak = audioop.max(chunk, 2)
        except audioop.error:
            rms = peak = 0
        logger.info(
            "Audio input chunk #%s: %s bytes rms=%s peak=%s",
            self._logged_input_chunks,
            len(chunk),
            rms,
            peak,
        )

    @staticmethod
    def _is_virtual_or_mapper(name: str) -> bool:
        lowered = name.lower()
        blocked = (
            "@system32",
            "mapper",
            "primary sound",
            "stereo mix",
            "what u hear",
            "loopback",
            "output",
            "microphone array 1",
            "microphone array 2",
        )
        return any(token in lowered for token in blocked)

    @staticmethod
    def _normalize_device_name(name: str) -> str:
        cleaned = name.lower()
        cleaned = re.sub(r"\s*\([^)]+\)\s*$", "", cleaned)
        cleaned = re.sub(r"^(microphone|mic|array|headset)\s*[-:]*\s*", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip() or name.lower().strip()

    @staticmethod
    def _display_device_name(name: str, hostapi: str, is_default: bool) -> str:
        suffix = "Windows default" if is_default else hostapi
        return f"{name} ({suffix})" if suffix else name

    @staticmethod
    def _device_score(index: int, hostapi: str, default_input) -> int:
        score = 0
        if index == default_input:
            score += 1000
        hostapi_lower = (hostapi or "").lower()
        if "wasapi" in hostapi_lower:
            score += 100
        elif "wdm" in hostapi_lower:
            score += 70
        elif "directsound" in hostapi_lower:
            score += 40
        elif "mme" in hostapi_lower:
            score += 20
        return score
