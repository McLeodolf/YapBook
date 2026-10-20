# Tool selection and policy scope

Assessment date: 2026-10-20. Versions and thresholds live in `quality/policy.json`
and the hash locks. This document explains decisions; it does not grant approval.

| Tool | Verified fit and integration | Licensing/limits | Decision |
| --- | --- | --- | --- |
| Gitleaks | Windows/Linux release, Git history and working-tree scanning; fixture detection and redaction are executed | Maintainer's MIT project; archive digests pinned | Mandatory secret scanner |
| Semgrep CE engine | Official 1.181.0 engine scans Python/JavaScript using 13 local rules; real negative fixtures exercise it | LGPL engine and bundled native libraries require recorded review; local rules avoid a remote ruleset dependency | Mandatory SAST alongside Bandit and ESLint |
| Semgrep Python CLI | Package metadata pins `mcp==1.29.0`; pip-audit reported CVE-2026-59951 | Installing the CLI brought unnecessary MCP/telemetry dependencies | Excluded; only the verified native engine is extracted from the official wheel |
| Bandit | Python checks for injection, unsafe serialization, crypto and other insecure constructs | Apache-2.0; pinned | Mandatory complementary SAST |
| pip-audit and npm audit | Known-vulnerability checks of locked Python and Node dependencies; errors/unavailability fail | No paid account required; advisory services are external dependencies | Mandatory SCA |
| Ruff, mypy, ESLint | Bug-pattern lint, strict typing of the policy decision core, JavaScript security rules | Locked development dependencies | Mandatory, with explicit scope |
| coverage.py, c8, Playwright | Existing unittest and node:test plus real browser integration; no replacement test framework needed | Development-only dependencies; speech is mocked at the external boundary | Mandatory behavioral and coverage evidence |
| Snyk | Official free plan provides bounded test/project quotas; it supports code and dependency analysis | Account and quota management required; free is not unlimited | Evaluated, not required by this free workflow |
| OX Security | Maintainer describes supply-chain/security capabilities and a demo/trial | An unlimited free plan and this repository's integration were not independently established | Not selected |
| VibeGuard | Several unrelated products/projects use the name | Specific product identity, licensing and stack capabilities are not independently established | Not selected; do not assume a name supplies required controls |
| Artiforge | Consulted for design suggestions through its connected MCP tools | Advisory output was not a source-code scan or human review | Optional assistance, never an approval substitute |

Primary references: [Gitleaks](https://github.com/gitleaks/gitleaks),
[Semgrep CE](https://github.com/semgrep/semgrep),
[Semgrep release metadata](https://pypi.org/pypi/semgrep/1.181.0/json),
[Bandit](https://bandit.readthedocs.io/), [pip-audit](https://github.com/pypa/pip-audit),
[Snyk plans](https://snyk.io/plans/),
[Snyk usage](https://docs.snyk.io/platform-administration/snyk-hierarchy/usage-settings),
[OX supply-chain offering](https://www.ox.security/solutions/software-supply-chain-security/).

## Pass/fail policy

The full rule matrix is in `02-design-and-rollout.md`. Every detected credential
blocks pending triage; confirmed exposure requires removal and revocation/rotation.
Critical findings and malicious/unapproved-source packages cannot be waived.
Other unresolved scanner findings also block until fixed or formally reviewed.
Scanner confidence is not proof of exploitability: reports retain classification,
tool/rule, severity, file/line and a stable finding fingerprint. pip-audit does
not supply severity for every advisory; those findings receive a conservative
high blocking classification until a qualified reviewer assesses the advisory.

Python inputs and all transitive locks are inventoried. npm dependencies require
the approved registry, exact direct versions and SHA-512 integrity. Python locks
require exact versions and SHA-256 hashes; source overrides are rejected.
Inventory hashes expose unexplained input/lock drift. The dependency change
record and human review address package identity, maintenance and suspicious
names: known-advisory scans cannot prove a previously unseen package is benign.
License metadata is evidence to review, not a legal approval. Existing AGPL/LGPL,
custom, dual or unknown licenses remain visible until reviewed. Native scanner
libraries have a separate explicit review requirement.

Measured starting app floors were desktop 79.9% lines / 68.7% branches, web
63.8% / 57.5%, frontend 84.1% / 79.2%, rounded down from actual runs. Changed
code uses the same component floors. Governance has its own measured floor.
All floors are proposals until `coverage.approval` records a real review.
Exclusions and typing scope are explicit; these numbers are not a claim of
complete behavioral or application-wide type coverage.

## Hosting constraints

GitHub's [merge queue availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
requires an organization-owned repository. YapBook currently belongs to a personal
account, so the design uses strict current-target checks and validates the actual
merge revision. It does not claim a merge queue is configured.

GitHub [skipped jobs can appear successful](https://docs.github.com/en/pull-requests/reference/status-checks).
The controller therefore checks report presence, nonzero test counts, skips,
execution steps and exact revision/workflow provenance explicitly.

Native status checks have no time-to-live at the instant a user presses Merge.
The controller re-evaluates reviews/events and hourly expiry, but an approved
exception is intentionally reported as `APPROVED EXCEPTION` with a **failing
merge check** until a trusted merge-time expiry control is adopted. This avoids
leaving a reusable green check after a waiver expires. Policy evaluation still
rejects expired waivers automatically. Scheduler/API outages cannot be claimed
to provide instantaneous invalidation of an already published check.

GitHub Actions checks are tied to the Actions app, not a cryptographically unique
workflow identity. The controller verifies workflow content and independent
native reviews are mandatory, but a hostile repository administrator/write
collaborator is outside this personal-repository isolation boundary. A separate
GitHub App or organization-enforced workflow policy is needed for stronger
separation. No protection can prevent the sole repository owner from changing
repository settings; such changes require an organizational audit/role boundary.
