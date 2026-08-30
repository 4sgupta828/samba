# Dataraft — How do you benchmark a root-cause-analysis AI when you never know the real root cause?

*A LinkedIn post. Repo: https://github.com/4sgupta828/samba*

---

**A quietly fundamental problem in AIOps:**

Everyone is building AI to do root-cause analysis. Almost no one can *measure* whether it works. Why? Because in production, **you rarely know the true root cause** — that's the whole reason you needed RCA. So the field evaluates itself on anecdotes and cherry-picked incidents. You can't improve what you can't score, and you certainly can't trust an "AI SRE" you couldn't grade.

**What I explored: Dataraft — a simulator that *manufactures* ground-truth-labeled incidents, then tries to solve them.**

The closed loop, in one repo:
1. Procedurally (or with an LLM) generate diverse microservice topologies — gateways, services, DBs, caches, queues, typed edges.
2. Inject a **known** fault at a **known** node, ramped *gradually* (warmup → onset → full effect → recovery) so telemetry shows realistic onset and propagation.
3. Emit production-like, deliberately *imperfect* observability — metrics, logs, traces — with dropped samples, clock skew, correlated noise, retry storms, and circuit-breaker cascades.
4. Ship an exact `label.json` naming the root cause.
5. Run a whitebox RCA engine against it — and **score the answer against the label.**

The realism knobs are the point: a fragility index that runs the system near saturation, propagation delays that enforce temporal causality, and "hard negatives" — different faults with near-identical signatures — so RCA is tested against genuine ambiguity, not a clean oracle. Every run is fully replayable, turning any incident into a fixed regression test.

**What AI solves well:**
- Designing *plausible, varied* systems and scenarios (LLM-generated topologies with real architectural flavor) — great for coverage and diversity.
- Narrating a causal story from evidence once the statistics have done the separation.

**What AI does NOT solve:**
- The physics. Whether a spike is a cause or a symptom is a question for changepoint detection, statistical tests (Mann-Whitney, Cohen's d), and dependency reasoning — not a language model's intuition. Dataraft's engine is deliberately *whitebox*.
- Ground truth. You cannot prompt your way to a labeled dataset; you have to *author* the incident.

**What stays genuinely hard:**
- The sim-to-real gap: does an RCA method that wins on simulated incidents transfer to production? Simulation buys you ground truth and volume; it owes you a validation story.
- Hub bias — blaming the most-connected node just because everything routes through it — and disambiguating a real traffic spike from a retry storm. These are the failure modes that separate a real RCA engine from a plausible one.

**How to take it from here:**
- Grow the fault library and topology diversity; treat the labeled episodes as a public **benchmark** for RCA methods (including LLM agents like the sibling project, OATS).
- Score not just "did you name the node" but "did you separate cause from cascade and explain it."

**Products this could become:**
- An RCA benchmark + leaderboard for the AIOps industry (the "ImageNet moment" for incident diagnosis).
- Synthetic training data for observability ML where real labeled incidents are scarce.
- A pre-production chaos/validation harness — a digital twin you can break on purpose.

**To go deeper, look up:** chaos engineering (Chaos Monkey, Gremlin), discrete-event simulation (SimPy), OpenTelemetry, causal inference for RCA, and changepoint detection (PELT, `ruptures`).

The takeaway: **before we can trust AI to find root causes, we have to be able to score it — and that means manufacturing the ground truth reality won't give us.**

#AIOps #SRE #Observability #RCA #ChaosEngineering #Benchmarking #MLSystems
