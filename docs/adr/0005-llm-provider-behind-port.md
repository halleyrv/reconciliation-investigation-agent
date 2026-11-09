# ADR-0005: LLM provider behind a port

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** docs/architecture/project-structure.md (Port inventory)

## Context

The investigation agent needs an LLM to form hypotheses and write findings. The LLM never calculates or matches (principle 3). Tests and evaluations need reproducible runs, and providers and models change over time.

## Decision

Investigation's application layer depends on a `HypothesisGenerator` port that returns validated domain objects. Provider SDKs appear only in `investigation/adapters/outbound/llm/`. The proposed default provider is Anthropic Claude. The exact model ID is selected and verified against current documentation in Phase 4 (investigation agent). Tests use a scripted fake that returns fixed outputs.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Call a provider SDK directly from LangGraph nodes | Business flow becomes coupled to one vendor and cannot be tested deterministically |
| A generic "LLM client" port with `complete(prompt)` | Leaks prompt engineering into the application layer. The port should speak domain language |

## Consequences

- **Positive:** Deterministic tests. The provider can change without touching use cases.
- **Negative:** Each provider needs an adapter that maps structured output to domain objects.
- **Follow-ups:** Every agent run records model and prompt version (`investigation.agent_runs`).
