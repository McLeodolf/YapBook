# Readiness report

Status: **implemented and locally validated; NOT activated as hosted enforcement**.

The owner authorized committing and pushing the prepared changes on feature
branch `feat/ai-quality-gates` and designated `McLeodolf` as reviewer. This does
not approve the measured baseline, licenses, bootstrap merge or a release.
The measured source snapshot and machine-readable evidence are recorded under
`test-output/quality-current`; this directory is intentionally not source control.
The full-suite evidence predates the reviewer designation; publication sanity
checks are recorded separately under `test-output/quality-publication`.

## Deliverables and evidence

| Requested deliverable | Location |
| --- | --- |
| Current-state assessment | `01-assessment.md` |
| Architecture, execution order and responsibilities | `02-design-and-rollout.md` |
| Policy matrix | `02-design-and-rollout.md`, `03-tools-and-policy.md`, `quality/policy.json` |
| Prioritized implementation/rollout plan | `02-design-and-rollout.md`, bootstrap steps in `05-operations-and-validation.md` |
| Configuration and automation | `.github/workflows/`, `quality/`, Python hash locks, frontend test/lint configuration |
| Review and exception templates | `.github/pull_request_template.md`, `04-review-templates.md`, `quality/changes/quality-gates.json` |
| Validation scenarios and commands | `05-operations-and-validation.md`, `quality/tests/`, `quality/demonstrate.py` |
| Operational documentation | `05-operations-and-validation.md` |
| Final readiness | This file, actual `decision.json`, and read-only `quality-protection.json` |

## Verified locally

- Gitleaks scans current files and Git history with redacted results. Generated
  inert credentials in source/test fixtures are detected without exposing values.
- Semgrep CE local rules and Bandit execute. A real unsafe-code fixture is
  detected. The scanner's vulnerable Python MCP dependency was removed by
  using the checksum-verified native engine directly.
- Python and Node known-vulnerability audits report no known vulnerabilities
  after updating Vite 8.0.13 to 8.0.16 and removing the vulnerable tool dependency.
- Desktop tests, a real GUI self-test, Streamlit backend/initialization tests,
  Node unit tests and deterministic browser integration execute successfully.
- Browser tests cover hostile EPUB markup/resources, invalid/oversized archives,
  search, citation filtering, prefetch, theme persistence and cached replay.
- Governance tests cover missing/skipped evidence, exact revisions, stale/author/
  bot reviews, changes requested, workflow provenance, archive handling,
  exception scope/expiry, protection payloads and positive/negative decisions.
- Production lint, gate-core strict typing, Python compilation, frontend build
  consistency and gate formatting run. Dependency installation is hash-locked.
- The sample compliant simulation passes; missing scan, synthetic secret,
  stale approval and skipped-suite simulations fail for the expected rules.
  These are labelled simulations, not fabricated GitHub approvals.
- The protection preflight uses the saved Windows GitHub login and correctly
  refuses activation while prerequisites are missing. It observed both proposed
  protected branches still unprotected and required workflows unpublished.

Final exact counts, percentages and status are in `07-validation-evidence.json`.
That file is generated from executed reports, not aspirational configuration.
Core policy decisions receive substantially higher coverage than the wider
controller/network/bootstrap surface; review coverage scope before approving it.

## Blocking adoption items

1. **Owner: complete independent reviewer onboarding.** `McLeodolf` is now
   designated for peer, architecture and security review and remains the only
   current collaborator. His account cannot approve its own PR. High-risk
   changes require two distinct qualified independent people; designate the
   additional reviewers and confirm permissions. No approval is inferred from
   reviewer designation or an AI response.
2. **Qualified reviewers: approve baseline and dependencies.** The measured
   coverage floors are proposals. Existing copyleft/custom/unknown license
   metadata and the native scanner's bundled libraries remain explicit findings.
   Record package-specific decisions rather than silently grandfathering them.
3. **Owner/reviewers: approve and merge the initial trusted controls.** Feature
   branch publication is authorized. The initial policy/workflow still needs
   independent review and placement on the target/default branches before it can
   enforce subsequent PRs. Publishing a feature branch alone does not activate
   the controller or branch protection.
4. **CI/reviewers: execute real hosted acceptance.** Windows/Linux workflow setup,
   artifact transport, current-commit human approvals, required checks and an
   actual rejected merge cannot be proven by local fixture tests. Run a real
   compliant/noncompliant PR and then apply/read back protections.
5. **Owner: verify deployment boundary.** Confirm the currently selected Streamlit
   branch and protect it. The proposed branches are `main` and
   `feat/streamlit-reader`; neither is claimed protected yet. The EXE artifact
   workflow is prepared but has not run on GitHub or published a release.

## Platform limits and remaining assurance work

- This personal repository cannot use GitHub's organization-only merge queue.
  Strict target validation plus exact merge-parent evidence is the current plan.
- Native status checks have no atomic merge-time expiry. Approved exceptions
  remain merge-blocking until that control exists; hourly reevaluation is not
  represented as an instantaneous guarantee during scheduler/API outages.
- GitHub Actions app identity does not isolate a hostile repository administrator
  or trusted writer. Stronger separation needs an organization-enforced workflow
  policy or separate GitHub App; native independent review remains mandatory.
- Scanners do not prove all packages benign or all authorization/resource issues
  absent. The application currently has no payment/login system. Human review
  must assess actual trust boundaries rather than assume a generic scanner covers them.
- Tests mock the external speech boundary; they do not assess live voice quality
  or Microsoft's uptime. Existing listening acceptance remains a separate check.
- No formal mutation-testing claim is made. Negative scanner fixtures and gate
  tampering/failure scenarios provide targeted control checks; wider mutation
  testing and hosted operating-system parity remain follow-up assurance work.

The authoritative local result intentionally remains **FAIL** while adoption
requirements and license reviews are unresolved. The framework must not be
described as fully enforced or complete until hosted acceptance succeeds.
