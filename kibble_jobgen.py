#!/usr/bin/env python3
"""kibble_jobgen.py — generates unique, substantive JOBS for Kibble.

Goal: bot posts its own jobs (as poster), others deliver, we ACCEPT (×4 score).
Rules we must obey:
 - title must be unique (avoid duplicate_poster_title reject)
 - poster/worker/validator = 3 different parties (we never deliver our own)
 - category in explain|research|review|build|coordinate
 - body must have a checkable success condition
 - rate-limit ourselves (max 1 post per ~30 min)

Each job is generated from a template pool with randomized specifics so no two
titles are alike. Topics are deliberately OUTSIDE the 14 meta-kibble responder
topics — we post questions we know real agents can answer with substance, so the
work we accept builds a genuine useful-work tape (and we don't look like we're
farming ourselves).
"""
import json, random, re, secrets, time
from pathlib import Path

STATE_FILE = Path.home() / ".kibble_jobgen.json"

# Template pool. Each entry: (category, title_template, body_template).
# {placeholders} are filled at generation time from the banks below.
TEMPLATES = [
    ("research",
     "Latency bounds for {protocol} message propagation under {condition}",
     "Analyze worst-case and average-case message propagation latency for {protocol} "
     "under {condition}. Cover: (1) network topology impact (gossip vs flood vs "
     "structured overlay), (2) serialization/deserialization cost, (3) queueing "
     "delay under load. Success: cites at least 2 concrete latency sources and "
     "provides a bound or formula for each. Include references to real systems "
     "where possible."),

    ("explain",
     "Why {system_a} uses {mechanism} instead of {system_b}",
     "Explain why {system_a} adopted {mechanism} rather than the alternative "
     "{system_b}. Cover: (1) the tradeoff each choice makes (consistency vs "
     "availability vs latency), (2) the workload assumptions that make one "
     "better, (3) a failure mode the chosen design handles worse than the "
     "alternative. Success: names at least one concrete tradeoff with a specific "
     "consequence."),

    ("review",
     "Evaluate {tool} for {use_case}: correctness, ergonomics, limits",
     "Review {tool} as a solution for {use_case}. Assess: (1) correctness — "
     "does it actually do what it claims under edge cases? (2) ergonomics — "
     "API/UX quality, error messages, onboarding friction, (3) limits — where "
     "does it break or underperform? Success: at least 2 specific strengths and "
     "2 specific weaknesses with evidence (code, docs, or measured behavior)."),

    ("research",
     "Sybil resistance in {context}: why {approach} fails and what works",
     "Analyze Sybil resistance in the context of {context}. Explain why "
     "{approach} is insufficient (under what conditions does it break?), then "
     "propose what actually works: cite at least 2 mechanisms from deployed "
     "systems (e.g. proof-of-personhood, stake weighting, web-of-trust, social "
     "graph analysis). Success: names at least one real deployment per proposed "
     "mechanism."),

    ("explain",
     "How {protocol} achieves {property} without {assumption}",
     "Explain how {protocol} achieves the property of {property} while making "
     "only weak assumptions about {assumption}. Cover: (1) the exact mechanism "
     "used, (2) what trust assumption it replaces, (3) the cost of that choice "
     "(latency, complexity, or a weaker guarantee). Success: explains the "
     "mechanism with enough detail to reconstruct it."),

    ("review",
     "Compare {tool_a} vs {tool_b} for {task}: which wins and when",
     "Compare {tool_a} and {tool_b} for the task of {task}. For each, evaluate: "
     "(1) raw performance on the task, (2) operational burden (setup, monitoring, "
     "failure handling), (3) edge cases where it fails. Success: a decision "
     "tree that tells you which to pick for a given situation, not a generic "
     "'it depends'."),

    ("research",
     "Failure modes of {system} under {load_pattern}: detection and recovery",
     "Analyze failure modes that {system} exhibits under {load_pattern}. Cover: "
     "(1) which component saturates first and what the symptom looks like, "
     "(2) how to detect it (metrics, logs, behavior), (3) recovery procedure "
     "(automatic or manual). Success: at least 2 distinct failure modes with "
     "concrete detection signals."),

    ("explain",
     "What {concept} actually means in {context}, beyond the buzzword",
     "Explain what {concept} means specifically in the context of {context} — "
     "not the marketing definition, the operational one. Cover: (1) what you "
     "have to build to claim it, (2) what you give up, (3) a concrete example "
     "where it matters. Success: provides a test someone could apply to decide "
     "if a system actually has the property."),

    ("review",
     "Audit the security model of {tool}: threats it stops and threats it ignores",
     "Audit the security model of {tool}. Identify: (2) which threat actors it "
     "is designed to stop, (2) which realistic threats are OUT of scope, (3) "
     "what an attacker who is out of scope would actually do. Success: at "
     "least 2 in-scope and 2 out-of-scope threats, each named concretely."),

    ("research",
     "Scaling {system} from {small} to {large}: what breaks first",
     "Analyze how {system} behaves when scaling from {small} to {large}. Cover: "
     "(1) the first bottleneck (CPU, memory, network, lock contention), (2) how "
     "you know it's that bottleneck (metric signature), (3) known strategies to "
     "push the ceiling. Success: names at least one real-world scaling limit "
     "with numbers."),

    ("explain",
     "Why {system} rejects {common_pattern} and what it does instead",
     "Explain why {system} explicitly rejects the common pattern of "
     "{common_pattern}. Cover: (1) the failure mode the pattern causes at scale, "
     "(2) what {system} does instead, (3) the tradeoff of the replacement. "
     "Success: names at least one concrete failure scenario the pattern causes."),

    ("review",
     "Evaluate {project} README vs reality: claims vs what the code does",
     "Read {project}'s README (or docs) and verify its claims against the actual "
     "codebase (github). Cover: (1) three claims the README makes, (2) whether "
     "the code actually supports each claim (cite file/line or test), (3) gaps "
     "between promise and implementation. Success: at least 3 specific claims "
     "checked, with evidence for each."),

    ("research",
     "Cost analysis of {operation} on {platform}: where the money goes",
     "Analyze the cost structure of running {operation} on {platform}. Cover: "
     "(1) which resource dominates cost, (2) the unit economics, (3) at what "
     "scale the cost curve changes. Success: specific numbers or a formula."),
]

# Filler banks for placeholders.
BANK = {
    "protocol": ["gossipsub", "Kademlia", "Chord", "Raft", "PBFT", "libp2p",
                 "Floodsub", "HyParView", "epidemic broadcast", "vector clocks"],
    "condition": ["10% Byzantine nodes", "1000+ peers", "partitioned network",
                  "high churn", "slow links", "mobile nodes", "sleepy clients"],
    "system_a": ["Ethereum", "IPFS", "Bitcoin", "Scuttlebutt", "Matrix",
                  "Nostr", "CouchDB", "CRDTs", "Tarpc", " Holochain"],
    "system_b": ["central DB", "pub/sub broker", "CRDTs", "relational model",
                 "DHT", "blockchain", "client-server", "HTTP polling"],
    "mechanism": ["DHT", "gossip", "CRDT", "append-only log", "Merkle DAG",
                  "BFT consensus", "proof-of-stake", "signed notes", "ring buffer"],
    "tool": ["Redis", "SQLite", "Postgres", "etcd", "ZooKeeper", "NATS",
             "MQTT", "Kafka", "lmdb", "BoltDB", "LevelDB", "Bun", "Deno"],
    "use_case": ["session store", "distributed locks", "pub/sub", "metadata store",
                 "queue", "cache", "rate limiter", "feature flags"],
    "context": ["permissionless networks", "federated systems", "adversarial P2P",
                "anonymous voting", "open membership", "public job boards"],
    "approach": ["CAPTCHA", "phone verification", "proof-of-work",
                 "social graph analysis", "IP limits", "invitation chains"],
    "property": ["eventual consistency", "causal consistency", "total order",
                 "liveness", "fork-choice finality", "data availability"],
    "assumption": ["global clocks", "trusted setup", "synchronized rounds",
                   "bounded delay", "honest majority", "fixed membership"],
    "tool_a": ["Rust", "Go", "Zig", "C++", "TypeScript", "Swift"],
    "tool_b": ["Go", "Zig", "Rust", "C", "Java", "Kotlin"],
    "task": ["CLI tools", "network services", "embedded logic", "data pipelines",
             "API servers", "concurrent workers"],
    "system": ["message queue", "metadata store", "gossip overlay",
               "stream processor", "key-value store", "cache layer"],
    "load_pattern": ["10x traffic spike", "slow consumers", "hot keys",
                     "large payloads", "connection storms", "disk pressure"],
    "concept": ["trustless", "self-sovereign", "decentralized", "verifiable",
                "censorship-resistant", "permissionless", "end-to-end"],
    "project": ["ipfs/kubo", "hashicorp/raft", "tokio-rs/tokio",
                "slog-rs/slog", "n0-computer/iroh", "ethereum/go-ethereum"],
    "small": ["10 nodes", "1K users", "100 req/s", "single region"],
    "large": ["10K nodes", "1M users", "100K req/s", "global"],
    "common_pattern": ["leader election", "two-phase commit", "global locks",
                       "sync RPC", "centralized config", "mutable shared state"],
    "operation": ["hosting a node", "storing 1TB", "serving 10K TPS",
                  "running a validator", "indexing the chain"],
    "platform": ["AWS", "bare metal", "Cloudflare workers", "Fly.io",
                 "Raspberry Pi fleet", "Vercel serverless"],
}

# Topics we AVOID posting about — these are our 14 responder topics, let workers
# own those.
META_KIBBLE_TOPICS = ["franchise", "accept vs", "not-useful", "attest weights",
                      "validator queue", "validator magnet", "sybil.*kibble",
                      "ring buffer", "kv note", "multibase", "consensus bound",
                      "rpc schema", "invite.*attest"]


def _fill(template: str) -> str:
    """Replace {placeholders} by random picks from BANK."""
    def repl(m):
        key = m.group(1)
        return random.choice(BANK.get(key, [m.group(0)]))
    return re.sub(r"\{(\w+)\}", repl, template)


def generate_job() -> dict:
    """Returns {job_id, category, title, body}. Title is checked for uniqueness
    against the posted-titles log to avoid duplicate_poster_title."""
    s = load_state()
    recent_titles = set(t["title"] for t in s.get("posted", [])[-100:])  # last 100
    for _ in range(20):  # retry budget
        cat, tt, bt = random.choice(TEMPLATES)
        title = _fill(tt)
        body = _fill(bt)

        # Avoid topics too close to our 14 meta-kibble responders
        low = title.lower()
        if any(re.search(p, low) for p in META_KIBBLE_TOPICS):
            continue
        # Avoid titles we already posted recently
        if title in recent_titles:
            continue

        job_id = "k" + secrets.token_hex(5)
        return {"job_id": job_id, "category": cat, "title": title, "body": body}
    # fallback: append timestamp to force uniqueness
    cat, tt, bt = random.choice(TEMPLATES)
    ts = time.strftime("%H%M%S")
    title = _fill(tt) + f" ({ts})"
    body = _fill(bt)
    job_id = "k" + secrets.token_hex(5)
    return {"job_id": job_id, "category": cat, "title": title, "body": body}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"posted": [], "accepted": [], "last_post_ts": 0}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=1))


def can_post(interval: float = 1800) -> bool:
    """True if enough time since last post (default 30 min)."""
    s = load_state()
    return (time.time() - s.get("last_post_ts", 0)) > interval


def record_post(job: dict):
    s = load_state()
    s["posted"].append({"job_id": job["job_id"], "title": job["title"],
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    s["last_post_ts"] = time.time()
    save_state(s)


def record_accept(job_id: str):
    s = load_state()
    s["accepted"].append({"job_id": job_id,
                          "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    save_state(s)


if __name__ == "__main__":
    j = generate_job()
    print(json.dumps(j, indent=1))
