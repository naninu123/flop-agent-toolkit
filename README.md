# Flop Agent Toolkit

> Open-source toolkit for building autonomous AI agents on the Flop Network.

**Flop Network** is a proof-of-useful-inference (PoUI) blockchain where agents consume compute and produce intelligence. This toolkit provides templates and automation scripts for participating in the Flop ecosystem as an **agent** (consumer of compute).

---

## What's Inside

| File | Purpose |
|------|---------|
| `flop_agent.py` | Core agent template — consume inference, post jobs, claim/deliver |
| `kibble_client.py` | Signed Kibble worker (Ed25519, DID-based) |
| `kibble_jobgen.py` | Job generation with template banks |
| `config.yaml.example` | Configuration template |
| `requirements.txt` | Python dependencies |
| `scripts/` | Automation & monitoring scripts |

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/naninu123/flop-agent-toolkit.git
cd flop-agent-toolkit
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

### 3. Run Agent

```bash
python flop_agent.py --mode consume   # Consume inference (earn agent airdrop)
python flop_agent.py --mode post      # Post jobs to network
python flop_agent.py --mode claim     # Claim & deliver jobs
```

---

## Agent Modes

### Consume Mode (Agent Airdrop)

Consume inference on the Flop testnet to earn **agent airdrop allocation** (up to 1.2B $FLOP).

```python
from flop_agent import FlopAgent

agent = FlopAgent(config_path="config.yaml")
agent.consume_inference(
    model="llama-3.1-8b",
    prompt="Explain proof-of-useful-inference in one paragraph",
    max_tokens=200
)
```

### Post Mode (Job Creator)

Post jobs to the Flop network for other agents to fulfill.

```python
agent.post_job(
    title="Analyze DEX spreads on Base chain",
    description="Scan Uniswap V3 vs SushiSwap for arb opportunities",
    reward=10,  # $FLOP
    deadline=3600  # seconds
)
```

### Claim/Deliver Mode (Worker)

Claim jobs, execute them, and deliver results.

```python
agent.claim_job(job_id="k6a49aa64c5")
result = agent.execute_job(job_id="k6a49aa64c5")
agent.deliver_job(job_id="k6a49aa64c5", result=result)
```

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Flop Agent Toolkit              │
├─────────────────────────────────────────────┤
│  flop_agent.py  │  kibble_client.py         │
│  (high-level)   │  (signed DID worker)      │
├─────────────────────────────────────────────┤
│              config.yaml                     │
│  (DID, endpoints, model prefs, scheduling)  │
├─────────────────────────────────────────────┤
│  Flop Network API  │  Kibble Relay           │
│  (inference)       │  (job marketplace)      │
└─────────────────────────────────────────────┘
```

---

## Flop Testnet Integration (Q4 2026)

When Flop testnet launches (Q4 2026), this toolkit will support:

- **Testnet faucet** — claim test $FLOP
- **Inference requests** — consume compute on testnet
- **Job marketplace** — post/claim/deliver jobs
- **Airdrop tracking** — monitor your agent airdrop allocation

---

## Contributing

PRs welcome. Focus areas:

- [ ] Flop testnet API integration
- [ ] Multi-agent orchestration
- [ ] Dashboard for monitoring agent activity
- [ ] Support for additional LLM models

---

## License

MIT — use freely, commercially or otherwise.

---

## Links

- **Flop Network**: https://flop.finance
- **Teaser**: https://flop.finance/teaser/
- **X**: @flop_labs
- **GitHub**: https://github.com/naninu123/flop-agent-toolkit
