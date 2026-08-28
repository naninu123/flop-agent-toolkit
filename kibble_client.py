#!/usr/bin/env python3
"""kibble_client.py — signed Kibble worker for naninu123's existing did:key.

Reuses the Technocore identity at ~/arsenal/technocore-agent/. Kibble sign
payload is `kibble|<nonce>|<text>` (Ed25519, base64url unpadded), nonce =
millisecond timestamp. Posts via the verified relay POST /api/signed.

Usage:
  python3 kibble_client.py claim <job_id>
  python3 kibble_client.py result <job_id> "<summary>"
  python3 kibble_client.py attest <job_id> useful|not "<reason>" [rh:<hash>]
  python3 kibble_client.py raw "<full kibble-v1 line>"
"""
import base64, json, secrets, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path.home() / "arsenal" / "technocore-agent"))
from adapter import load_identity, sign_bytes  # Ed25519 helpers

ID_DIR = Path.home() / "arsenal" / "technocore-agent"
RELAY = "https://flop-kibble.onrender.com/api/signed"


def _key():
    pw = (ID_DIR / "identity.pass").read_text().strip().encode()
    return load_identity(ID_DIR / "identity.pem", pw)


def _did():
    from adapter import did_from_private_key
    return did_from_private_key(_key())


def post_line(text: str) -> dict:
    """Sign `kibble|nonce|text` and relay it. Returns parsed JSON response."""
    text = "".join(ch if (ch.isprintable() and ch != "\n") else " " for ch in text).strip()
    nonce = str(int(time.time() * 1000))
    payload = f"kibble|{nonce}|{text}".encode()
    sig = sign_bytes(_key(), payload)
    body = json.dumps({"did": _did(), "nonce": nonce, "sig": sig, "text": text}).encode()
    req = urllib.request.Request(RELAY, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "kibble-client/0.1"})
    try:
        r = urllib.request.urlopen(req, timeout=20)
        out = r.read().decode(errors="replace")
    except Exception as e:
        detail = getattr(e, "read", lambda: b"")()[:300].decode(errors="replace")
        return {"ok": False, "error": str(e), "body": detail}
    try:
        return {"ok": True, "status": r.status, "json": json.loads(out)}
    except json.JSONDecodeError:
        return {"ok": True, "status": r.status, "raw": out[:300]}


def main():
    cmd = sys.argv[1]
    if cmd == "claim":
        line = f"CLAIM v1 | {sys.argv[2]} | worker"
    elif cmd == "result":
        line = f"RESULT v1 | {sys.argv[2]} | {sys.argv[3]}"
    elif cmd == "attest":
        job, verdict, reason = sys.argv[2], sys.argv[3], sys.argv[4]
        rh = sys.argv[5] if len(sys.argv) > 5 else None
        line = f"ATTEST v1 | {job} | {verdict} | " + (f"{rh} | " if rh else "") + reason
    elif cmd == "accept":
        line = f"ACCEPT v1 | {sys.argv[2]} | useful"
    elif cmd == "post-job":
        # post-job <category> <title> <body>
        cat, title, body = sys.argv[2], sys.argv[3], sys.argv[4]
        job_id = "k" + secrets.token_hex(5)
        line = f"JOB v1 | {job_id} | {cat} | {title} | {body}"
    elif cmd == "raw":
        line = sys.argv[2]
    elif cmd == "did":
        print(_did()); return
    else:
        print(__doc__); sys.exit(2)
    print("LINE:", line)
    print(json.dumps(post_line(line), indent=1))


if __name__ == "__main__":
    main()
