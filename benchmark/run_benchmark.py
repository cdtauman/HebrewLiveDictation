"""CLI: compare STT providers by Word Error Rate on Hebrew samples.

Usage (from the repo root, with PYTHONPATH=src):

    python benchmark/run_benchmark.py --samples benchmark/samples \
        --providers google_v2 deepgram groq whisper_local

Each sample is a pair <name>.wav (16-bit mono PCM) + <name>.txt (reference
transcript). Cloud providers need credentials configured in the app settings /
keyring; whisper_local needs providers.whisper.enabled and a model available.
Providers that error (e.g. missing credentials) are reported as skipped.

Results feed provider defaults and Smart Auto ordering (auto_select.py); wiring a
result back into the ordering is a manual, reviewed decision.
"""

import argparse
import os
import sys


def _ensure_src_on_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)


def _collect_samples(samples_dir):
    samples = []
    for entry in sorted(os.listdir(samples_dir)):
        if not entry.lower().endswith(".wav"):
            continue
        wav = os.path.join(samples_dir, entry)
        ref = os.path.splitext(wav)[0] + ".txt"
        if not os.path.exists(ref):
            print(f"! skipping {entry}: no matching .txt reference")
            continue
        with open(ref, "r", encoding="utf-8") as f:
            samples.append((wav, f.read()))
    return samples


def main(argv=None):
    _ensure_src_on_path()
    from hebrew_live_dictation.benchmark import evaluate
    from hebrew_live_dictation.config import Config

    parser = argparse.ArgumentParser(description="STT provider WER benchmark")
    parser.add_argument("--samples", default=os.path.join(os.path.dirname(__file__), "samples"))
    parser.add_argument(
        "--providers", nargs="+", default=["google_v2", "deepgram", "groq", "whisper_local"]
    )
    parser.add_argument(
        "--config-dir",
        default=os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "VoiceType"),
        help="App config dir (for credentials/settings). Defaults to %%APPDATA%%/VoiceType.",
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.samples):
        print(f"Samples directory not found: {args.samples}")
        return 1
    samples = _collect_samples(args.samples)
    if not samples:
        print("No samples found (need <name>.wav + <name>.txt pairs).")
        return 1

    config = Config(args.config_dir)
    print(f"Benchmarking {len(samples)} sample(s) across: {', '.join(args.providers)}\n")

    results = []
    for provider in args.providers:
        result = evaluate(config, provider, samples)
        results.append(result)
        if result["mean_wer"] is None:
            errs = {r["error"] for r in result["rows"] if r["error"]}
            print(f"  {provider:14s}  SKIPPED ({'; '.join(sorted(errs)) or 'no results'})")
        else:
            print(f"  {provider:14s}  mean WER = {result['mean_wer']:.3f}")

    ranked = sorted(
        (r for r in results if r["mean_wer"] is not None), key=lambda r: r["mean_wer"]
    )
    print("\nRanking (lower is better):")
    for r in ranked:
        print(f"  {r['mean_wer']:.3f}  {r['provider']}")
    if ranked:
        print(f"\nRecommended default for these samples: {ranked[0]['provider']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
