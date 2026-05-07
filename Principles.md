# Investment Research Agent — Project Principles

> These principles govern every decision in this project.
> When in doubt, come back here. Code that violates these principles gets rewritten.

---

## 1. The LLM is an analyst. The engine is the judge.

The most important principle in the entire system.

The LLM (Claude) is hired to think qualitatively:
- Read news and extract what matters
- Compare today's situation to the previous thesis
- Identify what information is missing
- Generate a bull case and a bear case
- Write a clear explanation a human can understand

The LLM is **never** asked:
- "Should I buy this stock?"
- "What score should this get?"
- "Does this pass the risk policy?"

Those decisions belong to the deterministic scoring engine and the risk policy engine.
They are explicit, auditable, versioned, and backtestable.
The LLM's output feeds them — it does not replace them.

**Why this matters:** LLMs hallucinate, drift, and change with model updates.
A scoring engine does not. An audit trail of scores is trustworthy. An audit trail of LLM opinions is not.

---

## 2. Every recommendation is a record, not a message.

A recommendation is not a chat reply. It is a structured database record with:

- The score and how every component was calculated
- The action and exactly why the policy produced it
- Every piece of evidence used (news, prices, filings, memory)
- The prompt version and strategy version that generated it
- The price at the time of recommendation
- The portfolio state at the time of recommendation
- Confidence and data quality scores
- What was missing

This makes three things possible:
1. **Auditing** — you can always explain why any recommendation was made
2. **Backtesting** — you can replay decisions against historical data
3. **Learning** — you can track outcomes and do post-mortems

If a recommendation cannot be fully reconstructed from the database record alone, it was not saved correctly.

---

## 3. Failure is expected. Crashes are not.

The research system runs twice daily, unattended. External services will fail.
News APIs go down. yfinance times out. LLM calls fail. IBKR disconnects.

**The system must always produce a result.**

Rules:
- LLM failure → apply confidence penalty, mark data quality, continue
- News API failure → skip news node, mark missing, continue
- IBKR failure → use last known portfolio snapshot, mark stale, continue
- Any single node failure → log error, degrade gracefully, never halt the run

The worst outcome is a low-confidence `WATCHLIST` recommendation with all the failures logged.
The unacceptable outcome is a crash with no recommendation saved.

Every node that calls an external service is wrapped in try/except.
Every failure is logged with a correlation ID.
Every confidence penalty is recorded in the recommendation.

---

## 4. Determinism is sacred in the decision layer.

Given the same inputs, the scoring engine must always produce the same output.
No randomness. No LLM in the decision path. No "it depends."

This means:
- Score formulas are explicit Python functions, not prompts
- Action mapping is a lookup table, not an inference
- Risk policy is a checklist of boolean conditions
- All thresholds are in `strategy_config` and versioned

When you update the scoring logic, you create a new `strategy_version`.
You do not edit the old one.
Old recommendations always point to the version that produced them.

---

## 5. Neutral before personal. Always.

The system produces two recommendations in sequence, never just one.

**Neutral first:** Is this stock attractive on its own merits?
This question is answered without any knowledge of your portfolio.
It could be published to anyone.

**Personal second:** Given the neutral view, what should *I* do?
This takes the neutral recommendation and applies your portfolio reality:
position size, concentration limits, cost basis, cash, risk tolerance.

This separation matters because:
- It forces honesty. A stock can be `BUY_CANDIDATE` while your personal action is `HOLD` because you're already overweight.
- It makes the neutral recommendation reusable — you could share it with others later.
- It makes bugs obvious — if neutral and personal always agree, the personalization is broken.

---

## 6. Memory makes the system intelligent.

A research system that doesn't remember previous runs is just a calculator.

Before every research run, the system retrieves from ChromaDB:
- The previous thesis for this stock
- The last recommendation and its reasoning
- Key risks that were flagged in previous runs
- Past mistakes made on this symbol or similar patterns

During analysis, the LLM is given this context and asked:
- What has changed since the last run?
- Is the previous thesis still valid?
- Are we about to repeat a past mistake?

After every run, the system indexes:
- The full research report
- The recommendation and its reasoning
- Any new risks or thesis updates

Memory is not optional. A run without memory retrieval is incomplete.

---

## 7. Versioning is how the system learns.

The system has three versioned objects:

**Strategy versions** — the scoring weights, thresholds, and policy rules.
When we discover the technical score is overweighted, we create `strategy_v2`.
Every recommendation records which strategy version produced it.

**Prompt versions** — the exact text sent to Claude for each node.
When we improve the news analysis prompt, we create `news_analysis_v2`.
Every recommendation records which prompt versions were used.

**Model versions** — which Claude model was used.
Recorded automatically.

This means we can always ask:
- "Did the new strategy version perform better than the old one?"
- "Did the new prompt produce better bull/bear cases?"
- "Which model version produced the most accurate recommendations?"

You never edit a version. You create a new one. Old records are immutable.

---

## 8. The learning loop depends on the research loop.

We build in two phases, in order:

**Phase 1 — Research loop:**
Every run produces a complete, structured, reproducible recommendation record.

**Phase 2 — Learning loop:**
We analyze past recommendations, track outcomes, run post-mortems, and propose improvements.

Phase 2 is impossible without Phase 1 being solid.
Do not build any learning loop features until the research loop has been running for real.

The learning loop features (outcome tracking, post-mortems, strategy proposals) are
explicitly deferred to Milestones 12–15. Do not implement them earlier.

---

## 9. Human approval at every important gate.

The system is autonomous in research. It is not autonomous in action.

Things the system does automatically:
- Fetch data
- Run analysis
- Score stocks
- Apply risk policy
- Generate recommendations
- Save reports
- Index to memory

Things that require human review:
- Acting on any recommendation (always)
- Approving a new strategy version
- Approving a new prompt version
- Applying a post-mortem lesson to the active strategy

This is not a limitation — it is the design.
The system's job is to make your research better and faster, not to replace your judgment.

---

## 10. Safety rules are absolute. No exceptions.

These rules cannot be overridden by any configuration, strategy version, or prompt:

1. **No automated order submission.** No IBKR write operations. Ever.
2. **No options.** The system does not model, suggest, or track options positions.
3. **No margin.** No leveraged position suggestions.
4. **No shorting.** Long-only system.
5. **No trading on behalf of the user.** The system recommends. The human decides.
6. **No API keys in code.** All secrets via environment variables.
7. **No LLM as decision-maker.** The scoring engine always has final say.
8. **No unversioned strategy changes.** Every config change creates a new version.

If any code is written that violates these rules, it is a bug — not a feature.

---

## How to use these principles

When Claude Code generates code that feels wrong, check it against these principles.

The most common violations to watch for:
- LLM output used directly in scoring without deterministic processing → violates #1
- Recommendation saved without full evidence + metadata → violates #2
- Node raises exception on external service failure → violates #3
- Score formula uses randomness or LLM → violates #4
- System produces only one combined recommendation → violates #5
- Run executes without ChromaDB retrieval → violates #6
- Scoring weights changed in-place instead of new version → violates #7

When in doubt: **more structure, more logging, more versioning.**
