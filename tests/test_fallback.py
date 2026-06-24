import queue
import tempfile
import threading
import time
import unittest

from hebrew_live_dictation.config import Config
from hebrew_live_dictation.stt.fallback import FallbackSpeechClient
from hebrew_live_dictation.stt_factory import create_stt_stream


class FakeProvider:
    """Duck-typed SpeechClient for tests."""

    def __init__(self, name, on_event, fail_after=None):
        self.name = name
        self.on_event = on_event
        self.fail_after = fail_after
        self.queue = None
        self.started = False
        self.stopped = False
        self.received = []
        self.thread = None

    def start(self, q):
        self.queue = q
        self.started = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        count = 0
        while True:
            chunk = self.queue.get()
            if chunk is None:
                break
            count += 1
            self.received.append(chunk)
            if self.fail_after is not None and count >= self.fail_after:
                self.on_event({"type": "error", "message": "primary boom"})
                break  # self-terminate like the real provider does on error

    def stop(self):
        self.stopped = True
        if self.queue is not None:
            try:
                self.queue.put(None)
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def restart_stream(self):
        pass


class _FinalThenFailProvider:
    """Primary that emits a committed final after `final_after` chunks, then a terminal
    error after `fail_after` chunks (final_after < fail_after)."""

    def __init__(self, name, on_event, final_after=1, fail_after=2):
        self.name = name
        self.on_event = on_event
        self.final_after = final_after
        self.fail_after = fail_after
        self.queue = None
        self.received = []
        self.thread = None
        self.stopped = False

    def start(self, q):
        self.queue = q
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        count = 0
        while True:
            chunk = self.queue.get()
            if chunk is None:
                break
            count += 1
            self.received.append(chunk)
            if count == self.final_after:
                self.on_event({"type": "final", "text": "שלום עולם"})
            if count >= self.fail_after:
                self.on_event({"type": "error", "message": "primary boom"})
                break

    def stop(self):
        self.stopped = True
        if self.queue is not None:
            try:
                self.queue.put(None)
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def restart_stream(self):
        pass


class FallbackSwitchTests(unittest.TestCase):
    def _config(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Config(tmp.name)

    def test_switches_to_local_and_replays_buffer_on_primary_error(self):
        config = self._config()
        events = []
        created = {}

        client = FallbackSpeechClient(config, on_event_callback=events.append)

        def fake_create(name):
            if name == client._primary_name:
                p = FakeProvider(name, client._on_provider_event, fail_after=2)
            else:
                p = FakeProvider(name, client._on_provider_event)
            created[name] = p
            return p

        client._create = fake_create

        # Model a live mic stream: feed enough to trigger the primary failure,
        # but keep the source OPEN (no None) so the switch is observed live.
        source = queue.Queue()
        source.put(b"c1")
        source.put(b"c2")

        client.start(source)

        # Wait for the fallback switch to take effect.
        deadline = time.time() + 5.0
        while not client._switched and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(client._switched, "fallback did not switch to local")

        # Post-switch audio flows to the local provider.
        for c in (b"c3", b"c4", b"c5"):
            source.put(c)
        source.put(None)
        client._pump_thread.join(timeout=5.0)

        local = created.get("whisper_local")
        self.assertIsNotNone(local)
        deadline = time.time() + 3.0
        while len(local.received) < 5 and time.time() < deadline:
            time.sleep(0.02)
        client.stop()

        # Primary saw only the first two chunks before failing.
        self.assertEqual(created[client._primary_name].received, [b"c1", b"c2"])
        # Local received the replayed buffer (c1,c2) then the live remainder.
        self.assertEqual(local.received, [b"c1", b"c2", b"c3", b"c4", b"c5"])
        # The primary error was swallowed; a switch status was surfaced.
        self.assertFalse(any(e.get("type") == "error" for e in events))
        self.assertTrue(any("offline local mode" in e.get("message", "") for e in events))

    def test_primary_final_then_error_does_not_replay_buffer_to_local(self):
        # MF2: if the primary committed a final before its terminal error, the fallback
        # must NOT replay the already-transcribed buffer into local (that would duplicate
        # the content). Local only handles subsequent audio.
        config = self._config()
        events = []
        created = {}

        client = FallbackSpeechClient(config, on_event_callback=events.append)

        def fake_create(name):
            if name == client._primary_name:
                p = _FinalThenFailProvider(name, client._on_provider_event, final_after=1, fail_after=2)
            else:
                p = FakeProvider(name, client._on_provider_event)
            created[name] = p
            return p

        client._create = fake_create

        source = queue.Queue()
        source.put(b"c1")
        source.put(b"c2")
        client.start(source)

        deadline = time.time() + 5.0
        while not client._switched and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(client._switched, "fallback did not switch to local")

        for c in (b"c3", b"c4"):
            source.put(c)
        source.put(None)
        client._pump_thread.join(timeout=5.0)

        local = created.get("whisper_local")
        self.assertIsNotNone(local)
        deadline = time.time() + 3.0
        while len(local.received) < 2 and time.time() < deadline:
            time.sleep(0.02)
        client.stop()

        # The primary's committed final passed through exactly once.
        finals = [e for e in events if e.get("type") == "final"]
        self.assertEqual(finals, [{"type": "final", "text": "שלום עולם"}])
        # Local did NOT receive the replayed buffer (c1,c2); only the post-switch audio.
        self.assertNotIn(b"c1", local.received)
        self.assertNotIn(b"c2", local.received)
        self.assertEqual(local.received, [b"c3", b"c4"])
        # No primary error leaked through.
        self.assertFalse(any(e.get("type") == "error" for e in events))

    def test_local_failure_after_switch_surfaces_error(self):
        # MF2: no false success — once switched, a local-provider failure is surfaced
        # (only the PRIMARY's pre-switch error is swallowed).
        config = self._config()
        events = []
        created = {}

        client = FallbackSpeechClient(config, on_event_callback=events.append)

        def fake_create(name):
            # Primary fails with no final (rescue path). Local also fails on its first
            # (replayed) chunk -> that error must reach the controller.
            p = FakeProvider(name, client._on_provider_event, fail_after=1)
            created[name] = p
            return p

        client._create = fake_create

        source = queue.Queue()
        source.put(b"c1")
        client.start(source)

        deadline = time.time() + 5.0
        while not client._switched and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(client._switched, "fallback did not switch to local")

        deadline = time.time() + 3.0
        while not any(e.get("type") == "error" for e in events) and time.time() < deadline:
            time.sleep(0.02)
        source.put(None)
        client._pump_thread.join(timeout=5.0)
        client.stop()

        self.assertTrue(
            any(e.get("type") == "error" for e in events),
            "local provider failure after switch must surface as an error (no false success)",
        )

    def test_non_error_events_pass_through(self):
        config = self._config()
        events = []
        client = FallbackSpeechClient(config, on_event_callback=events.append)
        client._on_provider_event({"type": "final", "text": "hi"})
        client._on_provider_event({"type": "interim", "text": "h"})
        self.assertEqual([e["type"] for e in events], ["final", "interim"])


class FactoryModeTests(unittest.TestCase):
    def test_auto_fallback_wraps_when_whisper_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "auto_fallback", "providers.whisper.enabled": True})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, FallbackSpeechClient)
            self.assertEqual(stream._primary_name, "google_v2")
            self.assertEqual(stream._local_name, "whisper_local")

    def test_auto_fallback_without_whisper_uses_plain_primary(self):
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "auto_fallback"})  # whisper disabled by default
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, GoogleSTTV2Stream)

    def test_mode_local_selects_whisper_when_enabled(self):
        from hebrew_live_dictation.stt.whisper_local import WhisperLocalStream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "local", "providers.whisper.enabled": True})
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, WhisperLocalStream)

    def test_mode_local_without_whisper_falls_back_to_google(self):
        from hebrew_live_dictation.google_stt_v2_stream import GoogleSTTV2Stream

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(tmp)
            config.update({"stt.mode": "local"})  # whisper disabled
            stream = create_stt_stream(config, lambda e: None)
            self.assertIsInstance(stream, GoogleSTTV2Stream)


if __name__ == "__main__":
    unittest.main()
