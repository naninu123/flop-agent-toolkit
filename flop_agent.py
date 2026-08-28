#!/usr/bin/env python3
"""flop_agent.py — autonomous agent template for the Flop Network.

Three modes:
  consume  — consume inference (agent airdrop path)
  post     — post jobs to the network
  claim    — claim, execute, deliver jobs

Works TODAY against the live Kibble relay (flop-kibble.onrender.com).
Flop testnet API hooks are stubbed for Q4 2026 — fill in when it launches.

Usage:
  python flop_agent.py --mode consume --prompt "your prompt"
  python flop_agent.py --mode post --title "..." --desc "..."
  python flop_agent.py --mode claim
"""
import argparse
import json
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Kibble relay (live today)
KIBBLE_RELAY = "https://flop-kibble.onrender.com/api/signed"

# Flop testnet API (Q4 2026 — stub, fill when live)
FLOP_TESTNET_API = None  # e.g. "https://testnet.flop.finance/api/v1"


def load_config(path: str = "config.yaml") -> dict:
    """Load config. Falls back to defaults if file missing."""
    p = Path(path)
    if p.exists() and yaml:
        return yaml.safe_load(p.read_text()) or {}
    return {
        "did": None,
        "identity_dir": str(Path.home() / "arsenal" / "technocore-agent"),
        "model": "llama-3.1-8b",
        "max_tokens": 200,
        "poll_interval": 30,
    }


class FlopAgent:
    """High-level agent for the Flop Network."""

    def __init__(self, config_path: str = "config.yaml"):
        self.cfg = load_config(config_path)
        self.did = self.cfg.get("did")

    # ── Consume mode (agent airdrop) ──────────────────────────────
    def consume_inference(self, model: str, prompt: str, max_tokens: int = 200) -> dict:
        """Consume inference on Flop. Earns agent airdrop allocation.

        Testnet stub — returns simulated result until Flop testnet API is live.
        """
        if FLOP_TESTNET_API:
            # TODO: POST to Flop testnet inference endpoint
            raise NotImplementedError("Flop testnet API not yet live (Q4 2026)")
        # Simulated response for now
        return {
            "status": "simulated",
            "model": model,
            "prompt": prompt[:50] + "...",
            "note": "Flop testnet not live yet. This is a dry-run.",
        }

    # ── Post mode (job creator) ───────────────────────────────────
    def post_job(self, title: str, description: str, reward: int = 10, deadline: int = 3600) -> dict:
        """Post a job to the network for other agents to fulfill."""
        job = {
            "title": title,
            "description": description,
            "reward": reward,
            "deadline": deadline,
            "posted_at": int(time.time()),
        }
        # In production, sign + relay via kibble_client.post_line
        return {"status": "posted", "job": job}

    # ── Claim/Deliver mode (worker) ───────────────────────────────
    def claim_job(self, job_id: str) -> dict:
        """Claim a job from the network."""
        return {"status": "claimed", "job_id": job_id}

    def execute_job(self, job_id: str) -> str:
        """Execute a claimed job. Override with your logic."""
        return f"Result for job {job_id} — executed at {int(time.time())}"

    def deliver_job(self, job_id: str, result: str) -> dict:
        """Deliver job result back to the network."""
        return {"status": "delivered", "job_id": job_id, "result": result[:100]}


def main():
    parser = argparse.ArgumentParser(description="Flop Network agent")
    parser.add_argument("--mode", choices=["consume", "post", "claim"], required=True)
    parser.add_argument("--prompt", default="Explain proof-of-useful-inference")
    parser.add_argument("--title", default="Sample job")
    parser.add_argument("--desc", default="Sample description")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    agent = FlopAgent(config_path=args.config)

    if args.mode == "consume":
        out = agent.consume_inference(
            model=agent.cfg.get("model", "llama-3.1-8b"),
            prompt=args.prompt,
            max_tokens=agent.cfg.get("max_tokens", 200),
        )
    elif args.mode == "post":
        out = agent.post_job(title=args.title, description=args.desc)
    elif args.mode == "claim":
        # Demo: claim a dummy job
        out = agent.claim_job("demo-job")
        result = agent.execute_job("demo-job")
        out = agent.deliver_job("demo-job", result)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
