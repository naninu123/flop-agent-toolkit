#!/usr/bin/env python3
"""tclk_scanner.py — scan tclk-offers room, accept deals, track state.

Daemon that:
1. Polls tclk-offers for new offers
2. Auto-accepts offers with rails we support
3. Tracks deal state in ~/.tclk_scanner.json
4. Posts accept frames via signed lane

Run: python3 tclk_scanner.py [--once] [--interval 60]
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

sys.path.insert(0, str(Path(__file__).parent))
from tclk_client import TclkClient, TclkState

IDENTITY_DIR = Path.home() / "arsenal" / "technocore-agent"
IDENTITY_PEM = IDENTITY_DIR / "identity.pem"
IDENTITY_PASS = IDENTITY_DIR / "identity.pass"
STATE_FILE = Path.home() / ".tclk_scanner.json"

# Rails we accept (must match DID note advertisement)
SUPPORTED_RAILS = ["flop-htlc", "x402", "paper"]
MAX_ACCEPT_PER_HOUR = 10


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
    did = 'did:key:z' + base58.b58encode(b'\xed\x01' + vk_bytes).decode()
    return sk, did


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "accepted": [],
        "last_seq": 0,
        "accepts_this_hour": 0,
        "hour_start": time.time(),
        "deals": {}
    }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def scan_offers(client: TclkClient, since: int = 0) -> list:
    """Scan tclk-offers room for new offer frames."""
    offers = client.get_offers(since=since)
    return offers


def accept_offer(client: TclkClient, offer: dict) -> tuple:
    """Accept an offer. Returns (success, contract_id, message)."""
    # Generate hash lock
    preimage_hex, statement = TclkClient.generate_hash_lock()
    
    # Create accept frame
    accept = client.make_accept(offer, statement)
    contract_id = client._contract_id(offer, accept)
    
    # Post accept to tclk-offers
    frame = client.encode_frame(accept)
    code, info = client.post_signed("tclk-offers", frame)
    
    if code == 200:
        return True, contract_id, preimage_hex
    return False, contract_id, info


def run_once(client: TclkClient, state: dict) -> dict:
    """Single scan cycle."""
    now = time.time()
    
    # Reset hourly counter
    if now - state.get("hour_start", 0) > 3600:
        state["accepts_this_hour"] = 0
        state["hour_start"] = now
    
    # Check rate limit
    if state["accepts_this_hour"] >= MAX_ACCEPT_PER_HOUR:
        return state
    
    # Scan for new offers
    last_seq = state.get("last_seq", 0)
    offers = scan_offers(client, since=last_seq)
    
    if not offers:
        # Fallback: scan all offers if since=0 returns nothing
        offers = scan_offers(client, since=0)
        # Filter to recent
        import time as _t
        now_ms = int(_t.time() * 1000)
        recent = []
        for o in offers:
            ts = o.get("_ts", "")
            if ts:
                # Parse ISO timestamp
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_ms = now_ms - int(dt.timestamp() * 1000)
                    if age_ms < 3_600_000:  # 1 hour
                        recent.append(o)
                except Exception:
                    recent.append(o)
        offers = recent
    
    if not offers:
        return state
    
    new_accepted = 0
    for offer in offers:
        # Skip our own offers
        if offer.get("from") == client.did:
            continue
        
        # Check if already accepted by us (by nonce in accepted list)
        offer_nonce = offer.get("nonce", "")
        if offer_nonce in state.get("accepted", []):
            continue
        
        # Check rail compatibility
        offer_rails = offer.get("rails", [])
        supported = [r for r in offer_rails if r in SUPPORTED_RAILS]
        if not supported:
            continue
        
        # Check expiry (if expiresMs field exists)
        expires_ms = offer.get("expiresMs", 0)
        if expires_ms and expires_ms < int(time.time() * 1000):
            continue
        
        # Accept the offer
        success, contract_id, preimage = accept_offer(client, offer)
        
        if success:
            state.setdefault("accepted", []).append(offer_nonce)
            state.setdefault("deals", {})[contract_id] = {
                "preimage": preimage,
                "offer": offer,
                "state": "accepted",
                "accepted_at": int(time.time())
            }
            state["accepts_this_hour"] = state.get("accepts_this_hour", 0) + 1
            new_accepted += 1
            
            print(f"  Accepted offer {offer_nonce[:8]}... → {contract_id}, preimage saved")
        
        # Rate limit check
        if state["accepts_this_hour"] >= MAX_ACCEPT_PER_HOUR:
            break
    
    # Update last_seq
    seqs = [o["_seq"] for o in offers if "_seq" in o]
    if seqs:
        state["last_seq"] = max(state.get("last_seq", 0), max(seqs))
    
    if new_accepted:
        save_state(state)
    
    return state


def run_daemon(client: TclkClient, interval: int = 60):
    """Continuous scanning loop."""
    state = load_state()
    print(f"Scanner started — interval {interval}s, max {MAX_ACCEPT_PER_HOUR}/hour")
    print(f"DID: {client.did}")
    print(f"Supported rails: {SUPPORTED_RAILS}")
    
    while True:
        try:
            state = run_once(client, state)
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(interval)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="tclk/1 offer scanner")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Scan interval in seconds")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    args = parser.parse_args()
    
    sk, did = load_keys()
    client = TclkClient(did, sk)
    
    if args.once:
        state = load_state()
        state = run_once(client, state)
        print(f"Accepted this hour: {state.get('accepts_this_hour', 0)}/{MAX_ACCEPT_PER_HOUR}")
    elif args.daemon:
        run_daemon(client, args.interval)
    else:
        state = load_state()
        state = run_once(client, state)
        print(f"Accepted this hour: {state.get('accepts_this_hour', 0)}/{MAX_ACCEPT_PER_HOUR}")


if __name__ == "__main__":
    main()
