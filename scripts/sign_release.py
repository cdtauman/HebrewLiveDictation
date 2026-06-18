"""Local release-signing helper for the signed-manifest auto-updater.

No CI required: generate a keypair once (keep the private key OFFLINE), bake the
printed public key into updater.EMBEDDED_PUBLIC_KEY_B64, then sign each release's
latest.json and upload latest.json + latest.json.sig + the installer to the
GitHub release.

Examples (run from the repo root):
    python scripts/sign_release.py keygen --out-dir .keys
    python scripts/sign_release.py pubkey --key .keys/updater_private.pem
    python scripts/sign_release.py sign --key .keys/updater_private.pem \
        --manifest latest.json --out latest.json.sig
"""

import argparse
import base64
import os


def _load_private_key(path):
    from cryptography.hazmat.primitives import serialization

    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def keygen(out_dir):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    os.makedirs(out_dir, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    priv_path = os.path.join(out_dir, "updater_private.pem")
    with open(priv_path, "wb") as f:
        f.write(pem)
    pub_b64 = _public_b64(priv)
    return priv_path, pub_b64


def _public_b64(priv):
    from cryptography.hazmat.primitives import serialization

    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def sign(key_path, manifest_path, out_path):
    priv = _load_private_key(key_path)
    with open(manifest_path, "rb") as f:
        data = f.read()
    signature = priv.sign(data)
    with open(out_path, "wb") as f:
        f.write(signature)
    return out_path


def pubkey(key_path):
    return _public_b64(_load_private_key(key_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Auto-updater release signing helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen")
    g.add_argument("--out-dir", default=".keys")
    s = sub.add_parser("sign")
    s.add_argument("--key", required=True)
    s.add_argument("--manifest", required=True)
    s.add_argument("--out", required=True)
    k = sub.add_parser("pubkey")
    k.add_argument("--key", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "keygen":
        priv_path, pub_b64 = keygen(args.out_dir)
        print(f"Private key written to {priv_path} — KEEP SECRET / OFFLINE.")
        print("Public key (bake into updater.EMBEDDED_PUBLIC_KEY_B64):")
        print(pub_b64)
    elif args.cmd == "sign":
        out = sign(args.key, args.manifest, args.out)
        print(f"Signature written to {out}.")
    elif args.cmd == "pubkey":
        print(pubkey(args.key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
