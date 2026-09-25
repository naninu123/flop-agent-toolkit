#!/usr/bin/env python3
"""flop_keepalive.py — keep-alive DID agent for Flop airdrop.

Signs + posts periodic messages to Technocore rooms to maintain
on-chain activity for FLOP testnet airdrop allocation.

Run: python3 flop_keepalive.py [--once] [--room faucet] [--interval 1800]
"""
import base64
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base58
except ImportError:
    print("pip install cryptography base58")
    sys.exit(1)

TECHNOCORE = "https://technocore.chat"
IDENTITY_DIR = Path.home() / "arsenal" / "technocore-agent"
IDENTITY_PEM = IDENTITY_DIR / "identity.pem"
IDENTITY_PASS = IDENTITY_DIR / "identity.pass"

# Rooms to maintain presence
ROOMS = ["faucet", "lobby", "flop", "flop-testnet"]
MESSAGES = [
    "FLOP testnet faucet claim",
    "Maintaining DID presence for FLOP airdrop",
    "Agent active — proof of useful inference",
    "FLOP testnet participant — DID verified",
]


def load_keys():
    passphrase = IDENTITY_PASS.read_text().strip()
    pem = IDENTITY_PEM.read_text()
    key = serialization.load_pem_private_key(pem.encode(), password=passphrase.encode())
    priv = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    sk = Ed25519PrivateKey.from_private_bytes(priv)
    vk = sk.public_key()
    vk_bytes = vk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    pub_multi = b'\xed\x01' + vk_bytes
    did = 'did:key:z' + base58.b58encode(pub_multi).decode()
    return sk, did


def sign_payload(sk, room, nonce, text):
    payload = f"{room}|{nonce}|{text}"
    sig = sk.sign(payload.encode())
    return base64.urlsafe_b64encode(sig).rstrip(b'=').decode(), payload


def post_signed(sk, did, room, nonce, text):
    sig, payload = sign_payload(sk, room, nonce, text)
    did_enc = urllib.parse.quote(did, safe='')
    sig_enc = urllib.parse.quote(sig, safe='')
    text_enc = urllib.parse.quote(text, safe='')
    url = f"{TECHNOCORE}/r/{room}/say-signed/{did_enc}/{sig_enc}/{nonce}/{text_enc}"
    try:
        req = urllib.request.Request(url, method='GET')
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, payload
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ''
        return e.code, body[:200]
    except Exception as e:
        return -1, str(e)


def post_unsigned(room, nick, text):
    nick_enc = urllib.parse.quote(nick, safe='')
    text_enc = urllib.parse.quote(text, safe='')
    url = f"{TECHNOCORE}/r/{room}/say/{nick_enc}/{text_enc}"
    try:
        req = urllib.request.Request(url, method='GET')
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


def get_room_seq(room):
    """Get current high seq in room to compute our nonce."""
    try:
        url = f"{TECHNOCORE}/r/{room}"
        resp = urllib.request.urlopen(url, timeout=10)
        first_line = resp.read().decode().split('\n')[0]
        # Parse "range X..Y" → Y is last seq
        import re
        m = re.search(r'range\s+(\d+)\.\.(\d+)', first_line)
        if m:
            return int(m.group(2))
    except Exception:
        pass
    return 0


def get_nonce(room):
    """Get nonce for signed posts: must be > last nonce we used in that room."""
    # Check room-nonce KV (preferred per spec)
    try:
        url = f"{TECHNOCORE}/kv/room-nonce/{room}"
        resp = urllib.request.urlopen(url, timeout=10)
        return int(resp.read().decode().strip()) + 1
    except Exception:
        # Fallback: use current seq + 1
        return get_room_seq(room) + 1


def update_did_note(sk, did):
    """Update DID note to keep it fresh (7-day reaper protection)."""
    did_hash = hashlib.sha256(did.encode()).hexdigest()
    ns = did_hash[:2]
    remaining = did_hash[2:16]
    path = f"did-{ns}/{remaining}"
    
    value = json.dumps({
        "did": did,
        "github": "naninu123",
        "updated": int(time.time()),
        "agent": "flop_keepalive"
    })
    
    nonce = get_nonce(f"kv-{path}")
    sig, payload = sign_payload(sk, path, nonce, value)
    did_enc = urllib.parse.quote(did, safe='')
    sig_enc = urllib.parse.quote(sig, safe='')
    val_enc = urllib.parse.quote(value, safe='')
    
    url = f"{TECHNOCORE}/kv/{path}/set-signed/{did_enc}/{sig_enc}/{nonce}/{val_enc}"
    try:
        req = urllib.request.Request(url, method='GET')
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def run_once(sk, did, room="faucet"):
    """Single keep-alive cycle."""
    nonce = get_nonce(room)
    text = MESSAGES[nonce % len(MESSAGES)]
    code, info = post_signed(sk, did, room, nonce, text)
    return code, room, text


def run_daemon(sk, did, interval=1800):
    """Continuous keep-alive loop."""
    state_path = Path.home() / ".flop_keepalive.json"
    count = 0
    errors = 0
    
    # Load state
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            count = state.get("count", 0)
            errors = state.get("errors", 0)
        except Exception:
            pass
    
    while True:
        try:
            for room in ROOMS:
                code, r, text = run_once(sk, did, room)
                if code == 200:
                    count += 1
                    print(f"[{count}] {r}: OK — {text[:40]}")
                else:
                    errors += 1
                    print(f"[{room}] HTTP {code}: {text[:60]}")
                time.sleep(2)  # Rate limit between rooms
            
            # Update DID note every ~10 cycles
            if count % 10 == 0:
                ok = update_did_note(sk, did)
                print(f"DID note update: {'OK' if ok else 'FAIL'}")
            
            # Save state
            state_path.write_text(json.dumps({
                "count": count,
                "errors": errors,
                "last_run": int(time.time())
            }))
            
        except Exception as e:
            errors += 1
            print(f"Cycle error: {e}")
        
        time.sleep(interval)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FLOP keep-alive agent")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--room", default="faucet", help="Target room")
    parser.add_argument("--interval", type=int, default=1800, help="Seconds between cycles")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    args = parser.parse_args()
    
    sk, did = load_keys()
    print(f"DID: {did}")
    
    if args.once:
        code, room, text = run_once(sk, did, args.room)
        print(f"Result: HTTP {code} in {room}")
    elif args.daemon:
        print(f"Daemon mode — interval {args.interval}s")
        run_daemon(sk, did, args.interval)
    else:
        # Default: run once
        code, room, text = run_once(sk, did, args.room)
        print(f"Result: HTTP {code} in {room}")


if __name__ == "__main__":
    main()
