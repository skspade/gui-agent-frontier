# vision-model

Mapping the **Pareto frontier of (task class, harness sophistication, model
size)** for local GUI grounding agents.

**Findings webapp:** https://skspade.github.io/gui-agent-frontier/

The contribution is identifying *where the cliffs are* across task classes
(known-site DOM short-horizon, long-horizon with grounding pinches,
visual-grounding-required, novel real-world e-commerce) — not "is local 8B
good enough?" but "for task class X, what is the minimum (model size,
harness sophistication) that achieves Y% reliability at Z× lower cost than
a frontier API model?"

## Reading order

- [`docs/thesis.md`](docs/thesis.md) — framing: task classes, harness axes,
  cost model, currently-known frontier, cliff hypotheses.
- [`docs/findings.md`](docs/findings.md) — progressive trail of every phase,
  smoke test, fix, and dead end.
- [`docs/backlog.md`](docs/backlog.md) — concrete next-up work as cell-fills
  `[class=…, H=…, model=…]` plus tactical items.
- [`CLAUDE.md`](CLAUDE.md) — operational reference (inference server, smoke
  runner, Thunder cloud path, hard-won rules).
