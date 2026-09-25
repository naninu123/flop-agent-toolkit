#!/usr/bin/env python3
"""tclk_client.py — Technocore Lock Protocol (tclk/1) client.

Handles HTLC/PTLC deal coordination via signed room messages.
All operations are pure HTTP GET — no POST, no WebSocket.

Usage:
    from tclk_client import TclkClient
    client = TclkClient(did, sk)
    offer = client.make_offer(amount="1000000", asset="FLOP", rails=["flop-htlc"])
    client.post_offer(offer)
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
from typing import Optional

TECHNOCORE = "https://technocore.chat"
OFFERS_ROOM = "tclk-offers"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _url_encode(s: str) -> str:
    return urllib.parse.quote(s, safe='')


class TclkClient:
    """tclk/1 client for agent-to-agent deal coordination."""

    def __init__(self, did: str, sk, identity_dir: str = None):
        self.did = did
        self.sk = sk
        self.identity_dir = identity_dir

    # ── Frame encoding ──────────────────────────────────────────

    @staticmethod
    def encode_frame(frame: dict) -> str:
        """Encode frame as tclk1 + compact JSON."""
        return "tclk1 " + json.dumps(frame, separators=(',', ':'), ensure_ascii=True)

    @staticmethod
    def decode_frame(line: str) -> Optional[dict]:
        """Decode tclk1 frame from room message."""
        if not line.startswith("tclk1 "):
            return None
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            return None

    # ── Lock generation ─────────────────────────────────────────

    @staticmethod
    def generate_hash_lock() -> tuple:
        """Generate (preimage, hash) for HTLC."""
        preimage = os.urandom(32)
        lock_hash = _sha256_hex(preimage)
        return preimage.hex(), lock_hash

    # ── Frame factories ─────────────────────────────────────────

    def make_offer(self, amount: str, asset: str, rails: list,
                   claim_by_ms: int = None, refund_after_ms: int = None,
                   expires_ms: int = None, nonce: str = None) -> dict:
        """Create an offer frame (payer side)."""
        now = _now_ms()
        if claim_by_ms is None:
            claim_by_ms = now + 3_600_000  # 1 hour
        if refund_after_ms is None:
            refund_after_ms = now + 7_200_000  # 2 hours
        if expires_ms is None:
            expires_ms = now + 600_000  # 10 minutes
        if nonce is None:
            nonce = os.urandom(16).hex()

        return {
            "type": "offer",
            "from": self.did,
            "lock": "hash",
            "amount": amount,
            "asset": asset,
            "rails": rails,
            "claimByMs": claim_by_ms,
            "refundAfterMs": refund_after_ms,
            "expiresMs": expires_ms,
            "nonce": nonce,
        }

    def make_accept(self, offer: dict, statement: str) -> dict:
        """Create an accept frame (payee side)."""
        return {
            "type": "accept",
            "from": self.did,
            "contract": self._contract_id(offer),
            "ref": offer.get("nonce", ""),
            "statement": statement,
        }

    def make_lock(self, contract_id: str, rail: str, ref: str) -> dict:
        """Create a lock frame (payer escrows funds)."""
        return {
            "type": "lock",
            "from": self.did,
            "contract": contract_id,
            "rail": rail,
            "ref": ref,
        }

    def make_reveal(self, contract_id: str, secret: str) -> dict:
        """Create a reveal frame (payee claims funds)."""
        return {
            "type": "reveal",
            "from": self.did,
            "contract": contract_id,
            "secret": secret,
        }

    def make_refund(self, contract_id: str) -> dict:
        """Create a refund frame (payer reclaims after timeout)."""
        return {
            "type": "refund",
            "from": self.did,
            "contract": contract_id,
        }

    def make_cancel(self, contract_id: str) -> dict:
        """Create a cancel frame (either side, before lock)."""
        return {
            "type": "cancel",
            "from": self.did,
            "contract": contract_id,
        }

    # ── Contract ID ─────────────────────────────────────────────

    @staticmethod
    def _contract_id(offer: dict, accept: dict = None) -> str:
        """Derive contract ID from offer + accept nonces."""
        offer_nonce = offer.get("nonce", "")
        if accept:
            accept_nonce = accept.get("ref", "")
            combined = f"{offer_nonce}:{accept_nonce}"
        else:
            combined = offer_nonce
        return "0x" + _sha256_hex(combined.encode())[:16]

    def deal_room(self, contract_id: str) -> str:
        """Derive deal room name from contract ID."""
        return f"mb-p-tclk-{contract_id[2:18]}"  # first 16 hex after 0x

    # ── Transport ───────────────────────────────────────────────

    def _sign_payload(self, room: str, nonce: int, text: str) -> str:
        """Sign a message for the signed lane."""
        payload = f"{room}|{nonce}|{text}"
        sig = self.sk.sign(payload.encode())
        return base64.urlsafe_b64encode(sig).rstrip(b'=').decode()

    def _get_nonce(self, room: str) -> int:
        """Get next nonce for a room. Per-DID global tracking.
        
        Server tracks per-DID last nonce globally (not per-room).
        We track locally + auto-increment on error.
        """
        state_path = Path.home() / ".tclk_nonces.json"
        # Use global nonce (per-DID, not per-room)
        nonce_key = f"{self.did}:global"
        
        nonces = {}
        if state_path.exists():
            try:
                nonces = json.loads(state_path.read_text())
            except Exception:
                pass
        
        last = nonces.get(nonce_key, 0)
        return last + 1

    def _save_nonce(self, room: str, nonce: int):
        """Save used nonce to state file (global per-DID)."""
        state_path = Path.home() / ".tclk_nonces.json"
        nonce_key = f"{self.did}:global"
        nonces = {}
        if state_path.exists():
            try:
                nonces = json.loads(state_path.read_text())
            except Exception:
                pass
        
        nonces[nonce_key] = nonce
        state_path.write_text(json.dumps(nonces, indent=2))

    @staticmethod
    def _parse_nonce_from_error(error_body: str) -> int:
        """Extract last used nonce from server error message."""
        import re
        m = re.search(r'nonce (\d+) is not greater than (\d+)', error_body)
        if m:
            return int(m.group(2))  # last used nonce
        return 0

    def post_signed(self, room: str, text: str, retry: bool = True) -> tuple:
        """Post a signed message to a room. Returns (status_code, info)."""
        nonce = self._get_nonce(room)
        sig = self._sign_payload(room, nonce, text)
        did_enc = _url_encode(self.did)
        sig_enc = _url_encode(sig)
        text_enc = _url_encode(text)

        url = f"{TECHNOCORE}/r/{room}/say-signed/{did_enc}/{sig_enc}/{nonce}/{text_enc}"
        try:
            req = urllib.request.Request(url, method='GET')
            resp = urllib.request.urlopen(req, timeout=15)
            self._save_nonce(room, nonce)
            return resp.status, resp.read().decode()[:200]
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ''
            # Auto-retry on nonce error
            if retry and 'nonce' in body.lower():
                last_used = self._parse_nonce_from_error(body)
                if last_used:
                    self._save_nonce(room, last_used)
                    return self.post_signed(room, text, retry=False)
            return e.code, body[:200]
        except Exception as e:
            return -1, str(e)

    def post_unsigned(self, room: str, nick: str, text: str) -> tuple:
        """Post an unsigned message to a room."""
        nick_enc = _url_encode(nick)
        text_enc = _url_encode(text)
        url = f"{TECHNOCORE}/r/{room}/say/{nick_enc}/{text_enc}"
        try:
            req = urllib.request.Request(url, method='GET')
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.status, resp.read().decode()[:200]
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ''
            return e.code, body[:200]
        except Exception as e:
            return -1, str(e)

    def read_room(self, room: str, since: int = 0, limit: int = 50) -> list:
        """Read messages from a room."""
        url = f"{TECHNOCORE}/r/{room}?since={since}&limit={limit}"
        try:
            resp = urllib.request.urlopen(url, timeout=15)
            data = resp.read().decode()
            return self._parse_room(data)
        except Exception:
            return []

    def read_frames(self, room: str, since: int = 0) -> list:
        """Read tclk/1 frames from a room."""
        messages = self.read_room(room, since)
        frames = []
        for msg in messages:
            text = msg.get("text", "")
            if text.startswith("tclk1 "):
                frame = self.decode_frame(text)
                if frame:
                    frame["_from"] = msg.get("from", "")
                    frame["_seq"] = msg.get("seq", 0)
                    frame["_ts"] = msg.get("ts", "")
                    frames.append(frame)
        return frames

    @staticmethod
    def _parse_room(data: str) -> list:
        """Parse room text format into message dicts."""
        messages = []
        for line in data.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!!"):
                continue
            # Format: [seq] timestamp <from> text
            if line.startswith("["):
                try:
                    # Find closing bracket
                    end = line.index("]")
                    seq = int(line[1:end])
                    rest = line[end+1:].strip()
                    # Split timestamp and from
                    parts = rest.split(" ", 2)
                    if len(parts) >= 3:
                        ts = parts[0]
                        from_part = parts[1]
                        text = parts[2]
                        # Clean from field
                        if from_part.startswith("<") and from_part.endswith(">"):
                            from_part = from_part[1:-1]
                        messages.append({
                            "seq": seq,
                            "ts": ts,
                            "from": from_part,
                            "text": text
                        })
                except (ValueError, IndexError):
                    continue
        return messages

    # ── High-level operations ───────────────────────────────────

    def post_offer(self, offer: dict) -> tuple:
        """Post an offer to tclk-offers room."""
        frame = self.encode_frame(offer)
        return self.post_signed(OFFERS_ROOM, frame)

    def post_accept(self, offer: dict, statement: str) -> tuple:
        """Post an accept to tclk-offers room."""
        accept = self.make_accept(offer, statement)
        frame = self.encode_frame(accept)
        return self.post_signed(OFFERS_ROOM, frame)

    def post_to_deal(self, contract_id: str, frame: dict) -> tuple:
        """Post a frame to a deal room."""
        room = self.deal_room(contract_id)
        text = self.encode_frame(frame)
        return self.post_signed(room, text)

    def get_offers(self, since: int = 0) -> list:
        """Get all offer frames from tclk-offers."""
        frames = self.read_frames(OFFERS_ROOM, since)
        return [f for f in frames if f and f.get("type") == "offer"]

    def get_deals(self, contract_id: str, since: int = 0) -> list:
        """Get all frames for a specific deal."""
        room = self.deal_room(contract_id)
        return self.read_frames(room, since)

    # ── DID note management ────────────────────────────────────

    def advertise_rails(self, rails: list) -> tuple:
        """Update DID note with tclk1 rail advertisement."""
        token = "tclk1:" + ",".join(rails)
        # Derive DID note path (new convention: did-<2hex>/<14hex>)
        did_hash = hashlib.sha256(self.did.encode()).hexdigest()
        ns = did_hash[:2]
        remaining = did_hash[2:16]
        note_ns = f"did-{ns}"  # new namespace convention
        note_key = remaining

        # Check if tclk1 token already present in current note
        try:
            url = f"{TECHNOCORE}/kv/{note_ns}/{note_key}"
            resp = urllib.request.urlopen(url, timeout=10)
            current = resp.read().decode()
        except Exception:
            current = ""

        if "tclk1:" in current:
            return 200, "already advertised"

        # Append token to existing note
        if current.startswith("!!"):
            # Find actual content (skip header lines)
            lines = current.split("\n")
            content_lines = []
            for line in lines:
                if line.startswith("!!") or line.startswith("#") or not line.strip():
                    continue
                content_lines.append(line)
            content = " ".join(content_lines).strip()
            if content and "tclk1:" not in content:
                new_value = f"{content} {token}"
            elif "tclk1:" in content:
                return 200, "already advertised"
            else:
                new_value = f"{self.did} {token}"
        else:
            if "tclk1:" in current:
                return 200, "already advertised"
            new_value = f"{current} {token}" if current.strip() else f"{self.did} {token}"

        # Write via unsigned lane (note is world-writable)
        # But we can also signed-write to own note
        nonce = self._get_nonce(f"kv-{note_ns}-{note_key}")  # use path for nonce
        sig = self._sign_payload(note_ns, self._get_nonce(note_ns), new_value)
        did_enc = _url_encode(self.did)
        sig_enc = _url_encode(sig)
        val_enc = _url_encode(new_value)

        # Try set-signed first, fallback to unsigned set
        url = f"{TECHNOCORE}/kv/{note_ns}/{note_key}/set-signed/{did_enc}/{sig_enc}/{nonce}/{val_enc}"
        try:
            req = urllib.request.Request(url, method='GET')
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.status, "OK (signed)"
        except urllib.error.HTTPError as e:
            # Try unsigned set (note is world-writable)
            val_enc = _url_encode(new_value)
            url2 = f"{TECHNOCORE}/kv/{note_ns}/{note_key}/set/{val_enc}"
            try:
                resp2 = urllib.request.urlopen(url2, timeout=15)
                return resp2.status, "OK (unsigned)"
            except urllib.error.HTTPError as e2:
                body2 = e2.read().decode() if e2.fp else ''
                return e2.code, body2[:200]
        except Exception as e:
            return -1, str(e)


# ── State machine (pure) ──────────────────────────────────────

class TclkState:
    """Pure state machine for tclk/1 deal lifecycle."""

    VALID_TRANSITIONS = {
        "open": ["accepted", "cancelled"],
        "accepted": ["locked", "cancelled"],
        "locked": ["claimed", "refunded"],
        "claimed": ["receipted"],
        "refunded": ["receipted"],
        "cancelled": [],
    }

    def __init__(self, state: str = "open"):
        self.state = state
        self.transcript = []

    def apply(self, frame: dict) -> tuple:
        """Apply a frame to state. Returns (ok, reason)."""
        frame_type = frame.get("type", "")

        if frame_type == "accept" and self.state == "open":
            self.state = "accepted"
            self.transcript.append(frame)
            return True, "accepted"

        elif frame_type == "lock" and self.state == "accepted":
            self.state = "locked"
            self.transcript.append(frame)
            return True, "locked"

        elif frame_type == "reveal" and self.state == "locked":
            # Verify secret matches statement
            secret = frame.get("secret", "")
            # In real implementation, verify sha256(secret) == statement
            self.state = "claimed"
            self.transcript.append(frame)
            return True, "claimed"

        elif frame_type == "refund" and self.state == "locked":
            self.state = "refunded"
            self.transcript.append(frame)
            return True, "refunded"

        elif frame_type == "cancel" and self.state in ("open", "accepted"):
            self.state = "cancelled"
            self.transcript.append(frame)
            return True, "cancelled"

        elif frame_type == "receipt" and self.state in ("claimed", "refunded"):
            self.state = "receipted"
            self.transcript.append(frame)
            return True, "receipted"

        return False, f"invalid transition from {self.state} via {frame_type}"

    def can_apply(self, frame_type: str) -> bool:
        """Check if frame_type is valid from current state."""
        return frame_type in self.VALID_TRANSITIONS.get(self.state, [])


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base58

    parser = argparse.ArgumentParser(description="tclk/1 client")
    parser.add_argument("--action", choices=[
        "offer", "accept", "lock", "reveal", "refund", "cancel",
        "list-offers", "list-deals", "advertise"
    ], required=True)
    parser.add_argument("--amount", default="1000000")
    parser.add_argument("--asset", default="FLOP")
    parser.add_argument("--rails", default="flop-htlc")
    parser.add_argument("--contract", help="Contract ID for deal operations")
    parser.add_argument("--secret", help="Preimage for reveal")
    parser.add_argument("--identity-dir", default=str(
        Path.home() / "arsenal" / "technocore-agent"
    ))
    args = parser.parse_args()

    # Load identity
    identity_dir = Path(args.identity_dir)
    passphrase = (identity_dir / "identity.pass").read_text().strip()
    pem = (identity_dir / "identity.pem").read_text()
    key = serialization.load_pem_private_key(pem.encode(), password=passphrase.encode())
    priv = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    sk = Ed25519PrivateKey.from_private_bytes(priv)
    vk = sk.public_key()
    vk_bytes = vk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    did = 'did:key:z' + base58.b58encode(b'\xed\x01' + vk_bytes).decode()

    client = TclkClient(did, sk, str(identity_dir))
    print(f"DID: {did}")

    if args.action == "offer":
        rails = args.rails.split(",")
        offer = client.make_offer(args.amount, args.asset, rails)
        print(f"Offer: {json.dumps(offer, indent=2)}")
        code, info = client.post_offer(offer)
        print(f"Posted: HTTP {code}")

    elif args.action == "list-offers":
        offers = client.get_offers()
        print(f"Found {len(offers)} offers:")
        for o in offers[:10]:
            print(f"  {o.get('from', '?')[:20]}... {o.get('amount')} {o.get('asset')}")

    elif args.action == "advertise":
        rails = args.rails.split(",")
        code, info = client.advertise_rails(rails)
        print(f"Advertised: HTTP {code} {info}")

    elif args.action in ("accept", "lock", "reveal", "refund", "cancel"):
        if not args.contract:
            print("--contract required")
            sys.exit(1)

        if args.action == "accept":
            # Need offer to get statement — for demo, use dummy hash
            statement = "0x" + "0" * 64
            code, info = client.post_accept({"nonce": "dummy"}, statement)
        elif args.action == "lock":
            frame = client.make_lock(args.contract, "flop-htlc", "rail-ref")
            code, info = client.post_to_deal(args.contract, frame)
        elif args.action == "reveal":
            if not args.secret:
                print("--secret required")
                sys.exit(1)
            frame = client.make_reveal(args.contract, args.secret)
            code, info = client.post_to_deal(args.contract, frame)
        elif args.action == "refund":
            frame = client.make_refund(args.contract)
            code, info = client.post_to_deal(args.contract, frame)
        elif args.action == "cancel":
            frame = client.make_cancel(args.contract)
            code, info = client.post_to_deal(args.contract, frame)

        print(f"{args.action}: HTTP {code} {info}")
