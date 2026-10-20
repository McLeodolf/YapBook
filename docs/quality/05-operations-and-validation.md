# Operating and validating the quality gates

Run commands from the YapBook repository, not `C:\Windows\System32`.
Windows uses `.venv\Scripts\python.exe`; equivalent commands use the virtualenv
Python on other systems. Desktop GUI/MCI acceptance runs on Windows.

## Local setup and normal changes

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --index-url https://pypi.org/simple -r quality/ci.lock
npm --prefix web/frontend ci --ignore-scripts --registry=https://registry.npmjs.org
```

Local browser checks use installed Chrome. CI installs pinned Playwright Chromium.
Add/update one `quality/changes/*.json` record; use the existing change record and
PR template as the schema. Run:

```powershell
.\.venv\Scripts\python.exe -m quality.run --base HEAD
.\.venv\Scripts\python.exe -m quality.demonstrate
```

`--base HEAD` measures the local uncommitted change. For a branch PR, use the
actual current target commit, such as `origin/main`, after fetching it. CI binds
head, base, tested merge, policy digest and run ID automatically. Local dirty-tree
reports are previews and cannot authorize a merge.

The local decision remains FAIL until real policy approvals are configured;
GitHub approvals are read only by the trusted controller. A stage can be rerun
using `--stage security`, `dependencies`, `code`, `desktop-tests`, `web-tests`,
`frontend-tests`, `browser-tests`, `governance-tests`, `coverage` or `traceability`.
After remediation run the full command to produce one consistent evidence bundle.
Never combine reports from different commits or run IDs.

## Resolve failures

| Failure | Action |
| --- | --- |
| Secret | Remove it, revoke/rotate if real, record remediation without values, rescan current source and history. Source and test fixtures are scanned. |
| SAST | Review rule/file/line and confidence; fix unsafe construction or obtain a narrow reviewed false-positive policy decision. |
| Dependency vulnerability | Upgrade to a fixed compatible release, regenerate all locks/inventory, review the delta and rerun audits/tests. |
| Dependency integrity/source | Use approved registries, exact versions and hashes; do not add extra indexes or direct Git/URL dependencies. |
| License | Inspect actual package notices and intended use/distribution, then record a qualified package-specific decision. Generic or unknown metadata is not automatic approval. |
| Tests or coverage | Fix the regression or add a relevant behavior/negative test. Do not skip tests or lower the baseline to hide failures. |
| Build drift | Run `npm --prefix web/frontend run build` and review/include generated changes. |
| Missing/stale evidence | Rerun the full current-target pipeline; unavailable scanners, timeouts and cancelled/skipped jobs fail closed. |
| Human review | Obtain the configured independent review on the current head, using the architecture record. |
| Expired exception | Remediate; any replacement requires fresh independent approval and scope, not an automatic expiry extension. |

Useful diagnostics (run locally; do not paste sensitive source/logs into public PRs):

```powershell
.\.venv\Scripts\python.exe -m ruff check --config quality/ruff.toml .
.\.venv\Scripts\python.exe -m ruff format --check --config quality/ruff.toml quality
.\.venv\Scripts\python.exe -m mypy --config-file quality/mypy.ini
npm --prefix web/frontend run lint
.\.venv\Scripts\python.exe -m unittest discover -v
npm --prefix web/frontend test
```

The runner deliberately omits raw child stdout from public findings because a
linter/assertion can quote a credential. Reports identify the failing command
and provide file/rule metadata where safe. Secret values and source-book text
must not be attached as evidence.

## Dependency and policy maintenance

Use pinned `uv` from policy to compile `quality/ci.in` first, with
`--generate-hashes --universal --python-version 3.13 --no-header --no-annotate`.
Regenerate the other inputs with `--constraint quality/ci.lock`:

| Input | Output |
| --- | --- |
| requirements.in | requirements.txt |
| web/requirements.in | web/requirements.txt |
| quality/requirements.in | quality/requirements.lock |
| quality/build.in | quality/build.lock |

Then sync/install the combined CI lock and run `python -m quality.inventory`.
Inventory regeneration proposes evidence; it never grants license or security
approval. Keep tool archive hashes pinned and verify changed releases against
the publisher. Scanner outages are failures; no empty-success fallback exists.

Coverage policy changes need measured reports, an explained scope/baseline delta
and independent approval. Do not reduce thresholds as an incidental code change.
The trusted base policy controls the candidate; workflow-template changes need a
separately reviewed transition hash or reviewed bootstrap. Action versions are
immutable commit SHAs. Review dependency/update PRs through the same gates.

## Bootstrap and merge protection

1. Complete independent reviewer onboarding and repository permissions.
   `McLeodolf` is designated in policy/CODEOWNERS, but cannot approve his own PR.
   High-risk changes need two distinct independent reviewers; their identities
   and approvals cannot be fabricated by automation.
2. Approve the measured coverage baseline and resolve/review package licenses.
   Record real reviewer, review URL and measured revision in policy.
3. Publish the feature branch for review. The owner explicitly authorized this
   commit/push; that authorization does not approve the baseline, dependencies
   or initial merge. This one-time trust bootstrap requires a separate recorded
   human decision, not a fabricated green CI.
4. Publish reviewed controls to the protected targets/default branch, execute
   the workflows and demonstrate an independently approved PR. Do not enable a
   required check name before it exists and runs successfully.
5. Run `python -m quality.protect --evidence-sha <passing-PR-head>` for read-only
   preflight, then `--apply` to configure and read back protection. Its report
   records what was observed. It preserves existing stricter review/check rules,
   enforces administrators, dismisses stale approvals, requires last-push review
   and resolved conversations, and disallows force pushes/deletions.
6. Confirm Streamlit's actual deployment branch in the hosting account. Both
   `main` and `feat/streamlit-reader` are proposed protected targets. Until this
   is verified, do not claim all deployment paths are gated.

The controller uses only protected code; artifacts are bounded JSON read without
extraction or PR execution. PR jobs have read-only tokens and no deployment secrets.
Native review protection complements the custom check. API/setup failures cannot
silently activate an incomplete configuration. The protection command uses the
existing Windows Git Credential Manager connection and never prints its token.

## Release path

The reviewed EXE workflow accepts an open PR number, rechecks current evidence
and actual approvals, and builds exactly its tested merge revision. It runs the
EXE self-test and produces a review artifact; it does not silently publish a
GitHub release. Local `build_exe.ps1` uses a hash-locked build dependency set but
is a developer build, not release authorization. Streamlit publishing is governed
by the verified protected deployment branch. Hosted release/rollback acceptance
must still be executed after bootstrap; a local YAML file is not evidence of it.

## Acceptance scenarios

| Scenario | Expected result and evidence |
| --- | --- |
| Real scanner synthetic credential in source/test input | Finding with value redacted; never publish the generated token. |
| Dynamic execution fixture | SAST detects it; scanner absence or parser error fails. |
| Existing Vite vulnerable release / repaired lock | Audit detects advisory; smallest compatible fixed release rescans clean. |
| Missing report, empty/skipped suite, mismatched revision/run | Consolidator FAIL with actionable rule. |
| Author/bot/unknown/stale review, dismissed approval or changes requested | Independent approval gate FAIL. |
| Hostile EPUB and malformed/oversized ZIP | Browser integration preserves safe rendering and rejects invalid input. |
| Cache persistence, storage failure, eviction and prefetch | No redundant synthesis for reusable cached requests; integration/unit evidence. |
| Exact commit + all synthetic stages + designated fixture reviews | Simulation PASS; clearly labelled, never a real approval. |
| Real compliant PR after bootstrap | All automated evidence plus actual independent reviews and required check PASS. Still pending hosted execution. |
| Direct push, failed/missing check, stale target or expired waiver | Protected merge/release refused. Hosted rejection must be demonstrated after activation. |

The positive/negative simulations and contract tests prove decision behavior.
They do not claim GitHub protection or Streamlit deployment has been exercised.
