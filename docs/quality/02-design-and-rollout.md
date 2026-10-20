# Quality-gate architecture and rollout

This design follows the repository assessment. Its acceptance state is recorded
in the readiness report; configuration alone does not establish enforcement.

## Execution and trust boundaries

1. Read the target branch's policy, classify changed paths, and identify the
   exact PR head, target and tested merge revision.
2. Run unprivileged checks: dependency integrity, formatting/lint/type/compile,
   Gitleaks, Semgrep, Bandit, dependency audits, deterministic tests, coverage,
   frontend build consistency, and traceability validation.
3. Upload bounded JSON results and human-readable evidence. A failed command,
   unavailable scanner, absent report, malformed result or skipped mandatory
   suite is a failure.
4. A separate controller running protected default-branch code reads reports as
   data and obtains actual reviews from GitHub. It never checks out or executes
   PR code. It verifies revision identity, workflow provenance, current policy,
   approvals, exception expiry and every required stage before writing
   `quality/gate`.
5. Branch protection requires that check, current-target validation, independent
   approval, stale-review dismissal, resolution of conversations, and no force
   pushes, deletions or administrator bypass. The deployment branch needs the
   same protection as `main`.

Reports are evidence, not trusted executable input. PR jobs have no deployment
credentials, no write token and no persistent checkout credentials. Controller
jobs use a different ephemeral runner. No `pull_request_target` job executes
PR code. Actions are pinned to verified commit SHAs. CI workflow changes cannot
silently weaken their own check: the controller compares the executed workflow
with the approved target-branch template. An enforcement-template update needs
a separately reviewed policy transition before that template becomes active.

Independent human review remains essential: scanners and coverage cannot prove
correctness, rule out malicious intent, or detect every typosquatted dependency.
Native review protection is required in addition to a programmable status check.
A repository administrator can change GitHub settings; organizational separation
of administration requires an organization and separate administrators, not a
claim that a personal repository can make its owner powerless.

## Policy matrix

| Rule | Mechanism | Blocking condition | Evidence / responsible role |
| --- | --- | --- | --- |
| SEC-SECRET | Gitleaks, redacted output, GitHub push protection | Any detected credential pending triage; confirmed exposure requires rotation | Rule/file/line, fingerprint and rotation or false-positive record; security reviewer |
| SEC-SAST | Semgrep and Bandit; reviewed HTML trust boundaries | Confirmed high/critical; unresolved policy findings require scoped exception | Versioned rules, finding severity/confidence, affected location, remediation; engineer/security reviewer |
| DEP-INTEGRITY | Hash locks, approved registries and dependency inventory | Unapproved source/package, absent hashes, inconsistent locks, malicious dependency | Dependency delta, approved source/license/version; maintainer |
| DEP-VULN | pip-audit and npm audit | Known vulnerabilities without permitted, approved exception; unknown severity is not a pass | Advisory ID, dependency path, fixed version; security reviewer |
| CODE-VALID | Lint, type checks, syntax/compile and Vite build | Executable error or generated bundle drift | Tool report and build result; author |
| TEST-BEHAVIOR | Existing unittest/Node suites plus negative/regression tests | Failure, skipped required suite, zero tests, missing acceptance coverage | JUnit/JSON, test mapping and review; author/reviewer |
| COV-BASELINE | coverage.py and c8 | Line/branch regression against measured, approved baseline | Full source scope and per-component counts; reviewer |
| COV-CHANGE | Diff against target plus coverage locations | Changed executable logic below configured thresholds or missing meaningful tests | Changed-line/branch report and behavioral test rationale; reviewer |
| ARCH-REVIEW | Native review protection and trusted review evaluator | Missing independent designated reviewers; stale approval; unresolved request for changes | Reviewer identity, exact commit, risks, actions, components and decision |
| TRACE | Structured change record and PR template | Missing requirement, rationale, dependency, verification or operational fields | Versioned record and PR description; author |
| EXCEPTION | Trusted policy, explicit record and real approval | Missing owner/controls/scope/approval, expired or prohibited waiver | Rule/fingerprint, rationale, owner, expiry, approver and review URL |
| FINAL | Trusted consolidated decision | Any missing or failed mandatory rule | PASS / FAIL / APPROVED EXCEPTION with links and actions |

## Risk and ownership

Documentation-only changes are low risk. Application logic and dependency
changes are at least medium risk. Untrusted archive/HTML parsing, speech service
validation, persistence/security boundaries, workflow/policy changes and release
automation are high risk. Declared risk may raise the computed minimum; it may
not lower it. High-risk reviews include negative tests, threat/failure analysis
and a rollback plan. The designated reviewer lists are explicit policy data.
An author, bot or stale approval cannot satisfy an independent human gate.

`McLeodolf` owns onboarding and repository administration and has designated
himself for peer, architecture and security review. This designation does not
approve any change, baseline or dependency. GitHub does not allow approval of
one's own PR, and high-risk changes still require two distinct independent
reviewers. Additional reviewers must be designated before those requirements
can be satisfied. Synthetic test identities are only test fixtures.

## Prioritized rollout

1. **Assessment and measurement (implementation work):** preserve existing work;
   record stack, GitHub settings, test baseline and actual security results.
2. **Security and merge controls (implementation work, owner adoption):** add
   pinned scanners, dependency policies and a tested protection installer. It
   must refuse activation until required workflows/checks are available.
3. **Tests and architecture (implementation work, reviewer approval):** establish
   measured thresholds, negative tests, exact-revision evidence and reviewer
   identity enforcement. Baseline approval is a separate human decision.
4. **Traceability and operations (implementation work):** templates, bounded
   exceptions, consolidated reports and remediation commands.
5. **Bootstrap (owner and independent reviewer):** review and approve policy,
   publish the implementation through the authorized Git workflow, run CI,
   activate/verify protections, and verify the Streamlit deployment branch.
   Existing instructions prohibit creating commits without an explicit request.
6. **Acceptance (reviewer):** demonstrate compliant and noncompliant fixtures,
   a real approved PR, rejected direct/failed merges, expiry/stale approvals,
   and a release against the approved revision.

No payment or new commercial service is required by this design. Availability
and usage quotas of GitHub-hosted CI remain external constraints; an outage
blocks the gate instead of pretending scans passed.
