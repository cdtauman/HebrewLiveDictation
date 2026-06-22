import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from hebrew_live_dictation.bridge import sidecar
from hebrew_live_dictation.bridge.sidecar import (
    _clear_history,
    command_reference,
    compute_health,
    engine_label,
    friendly_app_name,
    full_history,
    injection_target_label,
    list_microphones,
    make_callbacks,
    offline_is_primary_engine,
    offline_model_required,
    recent_history,
)


def _join_threads(name_prefix, timeout=2.0):
    """Wait for the manager's daemon worker thread(s) to finish, so event assertions are
    deterministic without sleeps."""
    import threading
    for t in threading.enumerate():
        if t.name.startswith(name_prefix) and t.is_alive():
            t.join(timeout)


def _write_history(tmp, rows):
    with open(os.path.join(tmp, "history.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class _FakeHotkeys:
    def __init__(self):
        self.listening = None

    def set_listening_state(self, on):
        self.listening = on


class _RecordingServer:
    def __init__(self):
        self.events = []

    def send_event(self, event):
        self.events.append(event)


class _FakeConfig:
    def __init__(self, d, config_dir=None):
        self.d = d
        if config_dir is not None:
            self.config_dir = config_dir

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value
        return True


class CloudRecoveryTests(unittest.TestCase):
    """recover_unconfigured_cloud: route an UNUSABLE cloud engine to offline. Per Codex MF1, Google is
    'usable' ONLY after a passing Test connection (the verified marker) for the current config —
    credentials merely existing is not enough."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _cfg(self, d):
        return _FakeConfig(dict(d), config_dir=self.dir)   # isolate the verify marker per test

    def _no_adc(self):
        return mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                            if k != "GOOGLE_APPLICATION_CREDENTIALS"}, clear=True)

    def test_unconfigured_google_routes_to_offline(self):
        cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "api",
                         "google.credential_mode": "service_account_json", "google.credentials_path": ""})
        with self._no_adc():
            self.assertTrue(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.provider"), "whisper_local")
        self.assertEqual(cfg.get("stt.mode"), "local")
        self.assertTrue(cfg.get("providers.whisper.enabled"))

    def test_credentials_present_but_unverified_routes_to_offline(self):
        # MF1: a real credentials file that has NOT been Test-connected is NOT usable -> offline.
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "api",
                             "google.credential_mode": "service_account_json", "google.credentials_path": path})
            with self._no_adc():
                self.assertTrue(sidecar.recover_unconfigured_cloud(cfg))
            self.assertEqual(cfg.get("stt.provider"), "whisper_local")
        finally:
            os.unlink(path)

    def test_verified_google_left_untouched(self):
        # A passing Test connection (verified marker for the current config) -> Google usable -> no change.
        cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "api", "google.project_id": "proj",
                         "google.location": "eu", "google.recognizer_id": "_", "google.credential_mode": "adc"})
        sidecar._set_google_verified(cfg)
        self.assertFalse(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.provider"), "google_v2")

    def test_verification_invalidated_by_config_change(self):
        cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "api",
                         "google.project_id": "proj-a", "google.credential_mode": "adc"})
        sidecar._set_google_verified(cfg)
        cfg.set("google.project_id", "proj-b")   # signature changes -> marker no longer matches
        with self._no_adc():
            self.assertTrue(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.provider"), "whisper_local")

    def test_offline_is_noop(self):
        cfg = self._cfg({"stt.provider": "whisper_local", "stt.mode": "local"})
        self.assertFalse(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.provider"), "whisper_local")

    def test_smart_auto_whisper_enabled_is_noop(self):
        # smart_auto resolves to whisper_local (not google) -> left to the factory.
        cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "smart_auto",
                         "google.credentials_path": "", "providers.whisper.enabled": True})
        with self._no_adc():
            self.assertFalse(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.mode"), "smart_auto")

    def test_smart_auto_unverified_google_routes_to_offline(self):
        # smart_auto whose effective pick is unverified Google must not start a dead cloud session.
        cfg = self._cfg({"stt.provider": "google_v2", "stt.mode": "smart_auto",
                         "google.credentials_path": "", "providers.whisper.enabled": False})
        with self._no_adc():
            self.assertTrue(sidecar.recover_unconfigured_cloud(cfg))
        self.assertEqual(cfg.get("stt.provider"), "whisper_local")


class ShellSelfTargetBlockTests(unittest.TestCase):
    """The WinUI shell (VoiceType.exe) runs in a SEPARATE process from the engine, so the injector's
    own-pid guard no longer covers it. The sidecar adds 'voicetype.exe' to the injector denylist so a
    shell-owned window (different pid) can never be chosen as an insertion target."""

    def test_voicetype_target_is_blocked_even_with_foreign_pid(self):
        from hebrew_live_dictation import editing_backend
        editing_backend.BLOCKED_TARGET_PROCESSES.add("voicetype.exe")   # what the sidecar does at startup
        t = editing_backend.WindowTarget(hwnd=1, process_id=999999, process_name="VoiceType.exe", title="VoiceType")
        # Isolate the denylist effect from window-validity/own-pid checks:
        t.is_valid = lambda: True
        t.is_current_process = lambda: False   # different pid than the engine
        self.assertTrue(t.is_blocked_system_target())
        self.assertFalse(t.is_usable_external())   # blocked purely by the shell denylist


class HealthTests(unittest.TestCase):
    def test_engine_label_google_pretty(self):
        c = _FakeConfig({"stt.provider": "google_v2", "stt.mode": "api", "google.model": "chirp_3"})
        self.assertEqual(engine_label(c), "Google · Chirp 3")

    def test_engine_label_offline(self):
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.mode": "local"})))
        self.assertIn("Whisper", engine_label(_FakeConfig({"stt.provider": "whisper_local"})))

    def test_engine_label_other_providers(self):
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "deepgram"})), "Deepgram")
        self.assertEqual(engine_label(_FakeConfig({"stt.provider": "groq"})), "Groq")

    def test_health_offline_ready(self):
        # Ready requires fallback configured AND Whisper enabled AND the model on disk.
        with mock.patch.object(sidecar, "model_downloaded", return_value=True):
            self.assertTrue(compute_health(
                _FakeConfig({"stt.mode": "auto_fallback", "providers.whisper.enabled": True}))["offline"]["ready"])
            self.assertTrue(compute_health(
                _FakeConfig({"stt.mode": "local", "providers.whisper.enabled": True}))["offline"]["ready"])
            # Configured + enabled but no fallback mode = not configured.
            notcfg = compute_health(_FakeConfig({"providers.whisper.enabled": True}))
            self.assertFalse(notcfg["offline"]["ready"])
            self.assertFalse(notcfg["offline"]["configured"])
        with mock.patch.object(sidecar, "model_downloaded", return_value=False):
            # Configured + enabled but model NOT downloaded = configured but NOT ready.
            cfg = compute_health(_FakeConfig({"stt.mode": "local", "providers.whisper.enabled": True}))
            self.assertFalse(cfg["offline"]["ready"])
            self.assertTrue(cfg["offline"]["configured"])
            self.assertFalse(cfg["offline"]["model_ready"])
            # auto_fallback WITHOUT Whisper = configured but NOT ready (the overclaim fix).
            cfg2 = compute_health(_FakeConfig({"stt.mode": "auto_fallback"}))
            self.assertFalse(cfg2["offline"]["ready"])
            self.assertTrue(cfg2["offline"]["configured"])
            # Nothing set = not ready.
            self.assertFalse(compute_health(_FakeConfig({}))["offline"]["ready"])

    def test_health_shape(self):
        with mock.patch.object(sidecar, "model_downloaded", return_value=False):
            h = compute_health(_FakeConfig({"stt.provider": "google_v2", "google.model": "chirp_2"}))
        self.assertEqual(h["engine"]["label"], "Google · Chirp 2")
        self.assertIn("ok", h["microphone"])
        self.assertIn("ready", h["offline"])
        self.assertIn("configured", h["offline"])
        self.assertIn("model_ready", h["offline"])

    def test_model_status_passthrough_and_safe(self):
        fake = {"name": "small", "downloaded": True, "path": "/models"}
        with mock.patch("hebrew_live_dictation.models.model_status", return_value=fake):
            self.assertEqual(sidecar.model_status(_FakeConfig({})), fake)
        # Any failure degrades to a safe not-downloaded shape, never raises.
        with mock.patch("hebrew_live_dictation.models.model_status", side_effect=RuntimeError("x")):
            s = sidecar.model_status(_FakeConfig({}))
            self.assertFalse(s["downloaded"])
            self.assertEqual(set(s.keys()), {"name", "downloaded", "path"})

    def test_engine_capabilities_shape_and_bools(self):
        caps = sidecar.engine_capabilities()
        self.assertIn("insertion", caps)
        self.assertEqual(set(caps["insertion"]), {"comtypes", "comtypes_client", "uiautomation"})
        for v in caps["insertion"].values():
            self.assertIsInstance(v, bool)

    def test_engine_capabilities_import_failure_degrades_to_false(self):
        import builtins
        real = builtins.__import__

        def boom(name, *a, **k):
            if name in ("comtypes", "comtypes.client", "uiautomation"):
                raise ImportError("simulated missing freeze dep")
            return real(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=boom):
            caps = sidecar.engine_capabilities()
        # A missing backend reports False (never raises) — the packaged smoke check then fails.
        self.assertFalse(any(caps["insertion"].values()))

    def test_engine_capabilities_reports_comtypes_client_independently(self):
        # The Word COM path needs comtypes.client specifically; a freeze can bundle the base
        # comtypes package but miss the submodule. The probe must report it independently so the
        # packaged gate (which requires comtypes_client) catches a missing Word backend.
        import builtins
        real = builtins.__import__

        def only_client_missing(name, *a, **k):
            if name == "comtypes.client":
                raise ImportError("submodule not frozen")
            return real(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=only_client_missing):
            ins = sidecar.engine_capabilities()["insertion"]
        self.assertFalse(ins["comtypes_client"])   # the Word COM submodule -> reported False
        self.assertTrue(ins["comtypes"])            # base package still importable, independently

    def test_model_downloaded_reflects_real_presence(self):
        with mock.patch("hebrew_live_dictation.models.model_status", return_value={"downloaded": True}):
            self.assertTrue(sidecar.model_downloaded(_FakeConfig({})))
        with mock.patch("hebrew_live_dictation.models.model_status", return_value={"downloaded": False}):
            self.assertFalse(sidecar.model_downloaded(_FakeConfig({})))
        with mock.patch("hebrew_live_dictation.models.model_status", side_effect=RuntimeError("x")):
            self.assertFalse(sidecar.model_downloaded(_FakeConfig({})))   # unknown -> not ready


class OfflineGateTests(unittest.TestCase):
    """Option A: starting dictation must never silently trigger faster-whisper's first-use
    auto-download. These helpers encode the start-refusal decision the sidecar's start paths
    (hotkey_start / startDictation / idle toggleDictation) gate on."""

    def test_offline_is_primary_only_when_local_engine_actually_runs(self):
        # mode=local with Whisper enabled -> the factory forces whisper_local: primary offline.
        self.assertTrue(offline_is_primary_engine(
            _FakeConfig({"stt.mode": "local", "providers.whisper.enabled": True})))
        # explicit whisper_local provider + enabled -> primary offline.
        self.assertTrue(offline_is_primary_engine(
            _FakeConfig({"stt.provider": "whisper_local", "providers.whisper.enabled": True})))
        # local selected but Whisper NOT enabled -> the factory falls back to the cloud default,
        # so no local download happens: NOT primary offline.
        self.assertFalse(offline_is_primary_engine(
            _FakeConfig({"stt.mode": "local", "providers.whisper.enabled": False})))
        # auto_fallback's live path is the cloud provider (local is only a mid-session backup).
        self.assertFalse(offline_is_primary_engine(
            _FakeConfig({"stt.mode": "auto_fallback", "providers.whisper.enabled": True})))
        # plain cloud config.
        self.assertFalse(offline_is_primary_engine(
            _FakeConfig({"stt.provider": "google_v2", "stt.mode": "api"})))

    def test_offline_model_required_only_when_primary_and_no_model(self):
        primary = {"stt.mode": "local", "providers.whisper.enabled": True}
        with mock.patch.object(sidecar, "model_downloaded", return_value=False):
            self.assertTrue(offline_model_required(_FakeConfig(dict(primary))))   # refuse + route
        with mock.patch.object(sidecar, "model_downloaded", return_value=True):
            self.assertFalse(offline_model_required(_FakeConfig(dict(primary))))  # model present -> start
        with mock.patch.object(sidecar, "model_downloaded", return_value=False):
            # Cloud engine missing a model is irrelevant: never blocks a cloud start.
            self.assertFalse(offline_model_required(_FakeConfig({"stt.provider": "google_v2"})))

    def test_offline_model_required_safe_on_error(self):
        # A failure deciding readiness must not raise into the start path (fail-open, never block
        # a start spuriously) — the helper swallows and returns False.
        with mock.patch.object(sidecar, "model_downloaded", side_effect=RuntimeError("x")):
            self.assertFalse(offline_model_required(
                _FakeConfig({"stt.mode": "local", "providers.whisper.enabled": True})))

    def test_smart_auto_counts_as_primary_only_when_it_resolves_to_whisper(self):
        cfg = _FakeConfig({"stt.mode": "smart_auto", "providers.whisper.enabled": True})
        with mock.patch("hebrew_live_dictation.stt.auto_select.select_provider", return_value="whisper_local"):
            self.assertTrue(offline_is_primary_engine(cfg))   # only Whisper available -> offline live
        with mock.patch("hebrew_live_dictation.stt.auto_select.select_provider", return_value="google_v2"):
            self.assertFalse(offline_is_primary_engine(cfg))  # resolves to cloud -> not offline live
        # Whisper disabled short-circuits before resolution (the factory would use the cloud default).
        with mock.patch("hebrew_live_dictation.stt.auto_select.select_provider",
                        return_value="whisper_local") as m:
            self.assertFalse(offline_is_primary_engine(_FakeConfig({"stt.mode": "smart_auto"})))
            m.assert_not_called()

    def test_smart_auto_missing_model_is_refused(self):
        # Must-Fix #1: smart_auto that would land on whisper_local with no model must be refused
        # at the start boundary (needsModel), never enter Whisper (which would auto-download).
        cfg = _FakeConfig({"stt.mode": "smart_auto", "providers.whisper.enabled": True})
        with mock.patch("hebrew_live_dictation.stt.auto_select.select_provider", return_value="whisper_local"):
            with mock.patch.object(sidecar, "model_downloaded", return_value=False):
                self.assertTrue(offline_model_required(cfg))
            with mock.patch.object(sidecar, "model_downloaded", return_value=True):
                self.assertFalse(offline_model_required(cfg))

    def test_offline_model_missing_marker_matches_whisper_refusal(self):
        # Mirrors WhisperLocalStream.OFFLINE_MODEL_MISSING_MESSAGE so the auto_fallback mid-session
        # refusal can be detected and routed.
        from hebrew_live_dictation.stt.whisper_local import OFFLINE_MODEL_MISSING_MESSAGE
        self.assertTrue(sidecar.is_offline_model_missing_status(OFFLINE_MODEL_MISSING_MESSAGE))
        self.assertTrue(sidecar.is_offline_model_missing_status("OFFLINE MODEL NOT INSTALLED now"))
        self.assertFalse(sidecar.is_offline_model_missing_status("Local transcription error: boom"))
        self.assertFalse(sidecar.is_offline_model_missing_status(""))
        self.assertFalse(sidecar.is_offline_model_missing_status(None))

    def test_on_error_flags_needs_model_for_missing_offline_model(self):
        # Must-Fix #2: when auto_fallback's switch to local refuses for a missing model, the error
        # surfaces mid-session; the sidecar tags it needsModel so the shell routes to download.
        server = _RecordingServer()
        from hebrew_live_dictation.stt.whisper_local import OFFLINE_MODEL_MISSING_MESSAGE
        _, _, on_error, _ = make_callbacks(_FakeHotkeys(), lambda: server)
        on_error(OFFLINE_MODEL_MISSING_MESSAGE)
        on_error("Some other engine error")
        self.assertTrue(server.events[0].get("needsModel"))
        self.assertNotIn("needsModel", server.events[1])


class ModelDownloadTests(unittest.TestCase):
    def test_successful_download_emits_running_then_done_when_validated(self):
        events = []
        seen = []

        def downloader(config, name):
            seen.append(name)
            return "/models/" + name

        mgr = sidecar.ModelDownloadManager(events.append, downloader=downloader)
        # done is emitted only because the post-download validation says the model is complete.
        with mock.patch("hebrew_live_dictation.models.model_status", return_value={"downloaded": True}):
            res = mgr.start(_FakeConfig({"providers.whisper.model": "small"}))
            self.assertEqual(res, {"started": True, "name": "small"})
            _join_threads("ModelDownload")
        self.assertEqual(seen, ["small"])
        states = [(e["state"], e.get("downloaded")) for e in events]
        self.assertEqual(states, [("running", None), ("done", True)])
        self.assertIsNone(mgr.active)

    def test_download_returning_but_incomplete_emits_error_not_done(self):
        # Must-Fix: do NOT trust the downloader returning. If post-download validation says the
        # model is not actually usable, emit error/not-ready, never done.
        events = []

        def downloader(config, name):
            return "/models/" + name   # "succeeds" but produced an incomplete/corrupt cache

        mgr = sidecar.ModelDownloadManager(events.append, downloader=downloader)
        with mock.patch("hebrew_live_dictation.models.model_status", return_value={"downloaded": False}):
            mgr.start(_FakeConfig({}), name="small")
            _join_threads("ModelDownload")
        self.assertEqual(events[0]["state"], "running")
        self.assertEqual(events[-1]["state"], "error")
        self.assertNotIn("done", [e["state"] for e in events])
        self.assertIsNone(mgr.active)

    def test_failed_download_emits_error_and_clears_active(self):
        events = []

        def downloader(config, name):
            raise RuntimeError("network down")

        mgr = sidecar.ModelDownloadManager(events.append, downloader=downloader)
        mgr.start(_FakeConfig({}), name="base")
        _join_threads("ModelDownload")
        self.assertEqual(events[0]["state"], "running")
        self.assertEqual(events[-1]["state"], "error")
        self.assertIn("network down", events[-1]["message"])
        self.assertIsNone(mgr.active)   # cleared even on failure

    def test_delete_model_passthrough_and_safe(self):
        with mock.patch("hebrew_live_dictation.models.delete_model", return_value=True):
            self.assertEqual(sidecar.delete_model(_FakeConfig({"providers.whisper.model": "small"})),
                             {"deleted": True, "name": "small"})
        with mock.patch("hebrew_live_dictation.models.delete_model", return_value=False):
            self.assertEqual(sidecar.delete_model(_FakeConfig({}), name="base"),
                             {"deleted": False, "name": "base"})
        with mock.patch("hebrew_live_dictation.models.delete_model", side_effect=RuntimeError("x")):
            self.assertFalse(sidecar.delete_model(_FakeConfig({"providers.whisper.model": "small"}))["deleted"])

    def test_second_download_while_busy_is_refused_not_queued(self):
        import threading
        release = threading.Event()
        started = threading.Event()

        def downloader(config, name):
            started.set()
            release.wait(2.0)

        mgr = sidecar.ModelDownloadManager(lambda e: None, downloader=downloader)
        first = mgr.start(_FakeConfig({}), name="small")
        self.assertTrue(first["started"])
        self.assertTrue(started.wait(2.0))
        self.assertEqual(mgr.active, "small")
        busy = mgr.start(_FakeConfig({}), name="small")     # still running
        self.assertEqual(busy, {"started": False, "busy": True, "name": "small"})
        release.set()
        _join_threads("ModelDownload")
        self.assertIsNone(mgr.active)

    def test_recent_history_empty_and_safe(self):
        # Empty config dir -> no history file -> empty list, never raises.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(recent_history(_FakeConfig({}, config_dir=tmp), 5), [])

    def test_recent_history_sanitized_and_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            long_text = "א" * 200
            _write_history(tmp, [
                {"ts": 1000, "target": "winword.exe", "text": "ראשון"},
                {"ts": 2000, "target": "secret-app.exe", "text": long_text},
            ])
            items = recent_history(_FakeConfig({}, config_dir=tmp), 5)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["ts"], 2000)               # newest first
            self.assertEqual(set(items[0].keys()), {"ts", "text"})  # target dropped
            self.assertTrue(items[0]["text"].endswith("…"))         # truncated
            self.assertLessEqual(len(items[0]["text"]), 81)

    def test_recent_history_count_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(100)])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertLessEqual(len(recent_history(c, 9999)), 50)   # upper clamp
            self.assertGreaterEqual(len(recent_history(c, "bad")), 1)  # bad -> default

    def test_recent_history_skips_blank_and_nondict(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": 1, "text": "  "}, {"ts": 2, "text": "ok"}])
            items = recent_history(_FakeConfig({}, config_dir=tmp), 5)
            self.assertEqual([i["text"] for i in items], ["ok"])

    def test_full_history_untruncated_newest_first_with_target(self):
        # The History room shows the user's complete record: full text + target, newest first.
        with tempfile.TemporaryDirectory() as tmp:
            long_text = "א" * 200
            _write_history(tmp, [
                {"ts": 1000, "target": "winword.exe", "text": "ראשון"},
                {"ts": 2000, "target": "chrome.exe", "text": long_text},
            ])
            items = full_history(_FakeConfig({}, config_dir=tmp), 200)
            self.assertEqual(items[0]["ts"], 2000)                      # newest first
            self.assertEqual(items[0]["text"], long_text)              # NOT truncated
            self.assertEqual(items[0]["target"], "chrome.exe")        # target preserved
            self.assertEqual(set(items[0].keys()), {"ts", "text", "target"})

    def test_full_history_count_clamped_to_store_cap(self):
        # >500 rows on disk: the default cap (history.max_entries=500) bounds the result,
        # and the NEWEST rows are returned (tail read, not a whole-file slice).
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(620)])
            c = _FakeConfig({}, config_dir=tmp)
            items = full_history(c, 9999)
            self.assertEqual(len(items), 500)               # clamped to default cap
            self.assertEqual(items[0]["text"], "t619")      # newest first
            self.assertEqual(items[-1]["text"], "t120")     # only the last 500 kept
            self.assertGreaterEqual(len(full_history(c, "bad")), 1)   # bad count -> default

    def test_full_history_honors_higher_max_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": i, "text": f"t{i}"} for i in range(620)])
            c = _FakeConfig({"history.max_entries": 1000}, config_dir=tmp)
            self.assertEqual(len(full_history(c, 9999)), 620)   # cap above count -> all rows

    def test_clear_history_removes_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_history(tmp, [{"ts": 1, "text": "a"}, {"ts": 2, "text": "b"}])
            c = _FakeConfig({}, config_dir=tmp)
            self.assertTrue(_clear_history(c))
            self.assertEqual(full_history(c, 200), [])


    def test_command_reference_he_deduped_and_friendly(self):
        ref = command_reference(_FakeConfig({"languages.primary": "iw-IL", "languages.command_pack": "he"}))
        says = [p["say"] for p in ref["punctuation"]]
        # The many newline alternates collapse to a single entry (first phrase kept,
        # deduped by inserted symbol — "שורה הבאה"/"רד שורה" share "\n" with "שורה חדשה").
        self.assertEqual(says.count("שורה חדשה"), 1)
        self.assertNotIn("שורה הבאה", says)
        self.assertNotIn("רד שורה", says)
        self.assertIn("נקודה", says)
        # Actions: one row per action, with a friendly Hebrew label; first phrase kept.
        self.assertEqual(len(ref["actions"]), 9)
        stop = next(a for a in ref["actions"] if a["does"] == "עצירת הכתבה")
        self.assertEqual(stop["say"], "עצור")

    def test_command_reference_safe_on_bad_pack(self):
        ref = command_reference(_FakeConfig({"languages.primary": "zz-ZZ"}))
        self.assertIn("punctuation", ref)
        self.assertIn("actions", ref)

    def test_list_microphones_shapes_devices(self):
        # Prefers display_name, falls back to name, drops blank/invalid, keeps the index.
        fake = [
            {"index": 3, "display_name": "USB Mic", "name": "USB Mic (2- USB Audio)"},
            {"index": 1, "name": "Internal"},
            {"index": 9, "display_name": "  "},  # no usable name -> dropped
        ]
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            items = list_microphones()["items"]
        self.assertEqual([i["index"] for i in items], [3, 1])
        self.assertEqual(items[0]["name"], "USB Mic")   # display_name preferred
        self.assertEqual(items[1]["name"], "Internal")  # falls back to raw name

    def test_list_microphones_safe_on_error(self):
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices",
                        side_effect=RuntimeError("no audio")):
            self.assertEqual(list_microphones(), {"items": []})

    def test_list_microphones_clears_stale_saved_index(self):
        # Saved device index 7 is gone -> normalized to null so the engine uses the
        # Windows default instead of opening a stale device.
        fake = [{"index": 3, "name": "USB Mic"}, {"index": 1, "name": "Internal"}]
        cfg = _FakeConfig({"audio.microphone_device": 7})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            list_microphones(cfg)
        self.assertIsNone(cfg.get("audio.microphone_device"))

    def test_list_microphones_keeps_valid_saved_index(self):
        fake = [{"index": 3, "name": "USB Mic"}, {"index": 1, "name": "Internal"}]
        cfg = _FakeConfig({"audio.microphone_device": 3})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=fake):
            list_microphones(cfg)
        self.assertEqual(cfg.get("audio.microphone_device"), 3)  # present -> untouched

    def test_list_microphones_does_not_clear_when_enumeration_empty(self):
        # No devices enumerated (transient/failure) must NOT clobber a saved selection.
        cfg = _FakeConfig({"audio.microphone_device": 5})
        with mock.patch("hebrew_live_dictation.audio_stream.AudioStream.list_devices", return_value=[]):
            list_microphones(cfg)
        self.assertEqual(cfg.get("audio.microphone_device"), 5)

    def test_friendly_app_name_maps_known_and_falls_back(self):
        self.assertEqual(friendly_app_name("WINWORD.EXE"), "Word")    # case-insensitive map
        self.assertEqual(friendly_app_name("chrome.exe"), "Chrome")
        self.assertEqual(friendly_app_name("MyEditor.exe"), "Myeditor")  # fallback: strip .exe, cap
        self.assertEqual(friendly_app_name(""), "")
        self.assertEqual(friendly_app_name("VoiceType.exe"), "")     # our own shell suppressed


class HudTargetTests(unittest.TestCase):
    def _status_cb(self, server):
        on_status, _, _, _ = make_callbacks(_FakeHotkeys(), lambda: server)
        return on_status

    def test_target_captured_once_and_preserved_across_listening_refreshes(self):
        # If the target were recomputed per status, this iterator would hand out a new
        # app each call; captured-once must pin the FIRST value for the whole session.
        server = _RecordingServer()
        on_status = self._status_cb(server)
        changing = iter(["Word", "Chrome", "Excel"])
        with mock.patch.object(sidecar, "injection_target_label", lambda: next(changing)):
            on_status("listening", "", "external")   # captures "Word"
            on_status("listening", "", "external")   # refresh — must NOT recompute
            on_status("listening", "", "external")   # refresh — must NOT recompute
        self.assertEqual([e.get("target") for e in server.events], ["Word", "Word", "Word"])

    def test_target_reset_and_recaptured_for_next_session(self):
        server = _RecordingServer()
        on_status = self._status_cb(server)
        changing = iter(["Word", "Chrome"])
        with mock.patch.object(sidecar, "injection_target_label", lambda: next(changing)):
            on_status("listening", "", "external")   # session 1 -> "Word"
            on_status("idle", "", "external")         # session ends
            on_status("listening", "", "external")   # session 2 -> fresh capture "Chrome"
        self.assertEqual(server.events[0].get("target"), "Word")
        self.assertNotIn("target", server.events[1])  # non-listening carries no target claim
        self.assertEqual(server.events[2].get("target"), "Chrome")

    def test_unknown_target_carries_empty_safe_state_while_listening(self):
        server = _RecordingServer()
        on_status = self._status_cb(server)
        with mock.patch.object(sidecar, "injection_target_label", lambda: ""):
            on_status("listening", "", "external")
        # Listening always carries the field; "" tells the HUD to show its safe state
        # rather than name a window the injector might not actually write to.
        self.assertIn("target", server.events[0])
        self.assertEqual(server.events[0]["target"], "")

    def test_fallback_latches_and_persists_then_resets_next_session(self):
        # The engine emits the offline-fallback notice ONCE mid-session; the sidecar must
        # latch it so every later listening status carries fallback=True, then drop it when
        # listening ends so the next session doesn't inherit a stale notice.
        server = _RecordingServer()
        on_status = self._status_cb(server)
        with mock.patch.object(sidecar, "injection_target_label", lambda: "Word"):
            on_status("listening", "recording", "external")                  # no fallback yet
            on_status("listening", "switching to offline local mode.", "external")  # fallback fires
            on_status("listening", "recording", "external")                  # later refresh keeps it
            on_status("idle", "", "external")                                 # session ends
            on_status("listening", "recording", "external")                  # new session: clean
        self.assertNotIn("fallback", server.events[0])
        self.assertTrue(server.events[1].get("fallback"))
        self.assertTrue(server.events[2].get("fallback"))   # latched across refreshes
        self.assertNotIn("fallback", server.events[3])      # not listening -> no flag
        self.assertNotIn("fallback", server.events[4])      # fresh session reset

    def test_is_fallback_status_matches_engine_notice_only(self):
        self.assertTrue(sidecar.is_fallback_status("Cloud transcription unavailable; switching to offline local mode."))
        self.assertTrue(sidecar.is_fallback_status("SWITCHING TO OFFLINE now"))
        self.assertFalse(sidecar.is_fallback_status("recording"))
        self.assertFalse(sidecar.is_fallback_status(""))
        self.assertFalse(sidecar.is_fallback_status(None))

    def test_target_changed_is_transient_set_on_detach_cleared_next_status(self):
        # The detached-preview status sets targetChanged for THAT event only; the next
        # normal status clears it (the target may have been re-pointed). Not sticky.
        server = _RecordingServer()
        on_status = self._status_cb(server)
        with mock.patch.object(sidecar, "injection_target_label", lambda: "Word"):
            on_status("listening", "recording", "external")                          # normal
            on_status("listening", "יעד הכתיבה השתנה. הטקסט נשמר בתצוגה ולא נכתב לחלון.", "external")  # detached
            on_status("listening", "recording", "external")                          # recovered
            on_status("idle", "", "external")
        self.assertNotIn("targetChanged", server.events[0])
        self.assertTrue(server.events[1].get("targetChanged"))
        self.assertNotIn("targetChanged", server.events[2])   # transient: cleared next status
        self.assertNotIn("targetChanged", server.events[3])   # not listening

    def test_is_target_changed_status_matches_both_locales(self):
        self.assertTrue(sidecar.is_target_changed_status("Target changed. Text is kept in preview and was not written."))
        self.assertTrue(sidecar.is_target_changed_status("יעד הכתיבה השתנה. הטקסט נשמר בתצוגה ולא נכתב לחלון."))
        self.assertFalse(sidecar.is_target_changed_status("recording"))
        self.assertFalse(sidecar.is_target_changed_status(""))
        self.assertFalse(sidecar.is_target_changed_status(None))

    @unittest.skipUnless(sys.platform == "win32", "Win32 target selection")
    def test_injection_target_label_uses_injector_selection_and_safety_gate(self):
        class _T:
            def __init__(self, name, usable):
                self.process_name = name
                self._usable = usable

            def is_usable_external(self):
                return self._usable

        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        return_value=_T("winword.exe", True)):
            self.assertEqual(injection_target_label(), "Word")
        # Unsafe / blocked / our-own target -> no confident claim.
        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        return_value=_T("winword.exe", False)):
            self.assertEqual(injection_target_label(), "")
        # Failure in the lookup is safe-empty, never raised.
        with mock.patch("hebrew_live_dictation.editing_backend.WindowTarget.capture_best_target",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(injection_target_label(), "")


if __name__ == "__main__":
    unittest.main()
