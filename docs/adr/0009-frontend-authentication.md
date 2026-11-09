# ADR-0009: Seeded development users with roles for frontend auth

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** ADR-0007

## Context

The approval flow needs identifiable users and roles (`analyst`, `approver`, `admin`) so that "approver ≠ proposer" and four-eyes are real. The project runs locally and uses no real data.

## Decision

Use seeded development users with roles and a simple signed session. Authentication sits behind an inbound adapter, so the application layer only receives an authenticated `Actor`. The backend refuses to start with dev auth unless the environment is `local` or `test`.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| OIDC (Keycloak or a hosted IdP) from day one | Real setup effort that does not show the core of the project |
| No authentication | Approval controls would be meaningless |

## Consequences

- **Positive:** Role-based flows can be demonstrated immediately.
- **Negative:** Not production-grade. It must never run outside local/test.
- **Follow-ups:** OIDC can replace the adapter later without touching use cases (new ADR).
