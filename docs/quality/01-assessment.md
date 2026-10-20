# Current-state assessment

Assessment date: 2026-10-20. Repository: `McLeodolf/YapBook` (public, personal
account). Source inspected: commit `aa8902093a3f85551a5d95956494355710f886a5`
plus the existing, uncommitted search/citation/audio-cache changes. Those feature
changes are preserved. This is a working-tree assessment, not a claim that they
have been merged or deployed.

## Existing workflow and boundaries

| Area | Observed state | Gap |
| --- | --- | --- |
| Desktop | Python, Tkinter/TkinterWeb, EbookLib, SQLite, Windows MCI; PyInstaller EXE | Build dependencies use ranges without a transitive hash lock. |
| Web | Streamlit 1.66, React 19, Vite 8, JavaScript modules; tracked frontend `dist` | Generated bundle can drift from source. No enforced build verification. |
| Dependencies | npm lockfile; pinned direct web Python dependencies; ranged desktop Python dependencies | Python transitive locks, source approval, license policy and automated audits absent. |
| Tests | `unittest`, Node `node:test`, manual Playwright scripts and live speech checks | No measured coverage baseline, CI execution or required regression evidence. |
| Deployment | Streamlit instructions use `web/streamlit_app.py`; prior deployment work uses `feat/streamlit-reader` | Hosting account's currently selected branch must be verified before release enforcement is claimed. |
| Reviews | Only collaborator returned by GitHub is owner `McLeodolf` | No independent architecture/security reviewer has been designated. |
| CI | GitHub Actions API returns zero workflows | No required test, scanner, traceability or consolidated decision checks. |
| Merge protection | Both `main` and `feat/streamlit-reader` report `protected: false`; no rulesets | Direct pushes and merges are not gated. |
| Security on GitHub | Secret scanning and secret push protection enabled | Dependabot alerts/security updates disabled; no configured SAST or dependency gate. |
| Documentation | READMEs describe usage, deployment and privacy | No risk classification, architecture decision record, approval record or exception process. |

EPUB archives and HTML are untrusted input. The browser has HTML sanitization,
an iframe sandbox and CSP; desktop HTML/resource handling is a separate trust
boundary. Browser EPUBs remain local; selected speech text goes to Streamlit and
Microsoft's voice service. Audio/text caches persist locally. Network timeouts,
request deduplication, cache identity, bounded concurrency and citation/highlight
offsets are behaviorally important. The application has no payment system or
application login; authentication-specific scanners cannot establish controls
for features which do not exist.

The previous feature validation recorded 78 desktop, 4 backend and 16 Node
tests. These counts are historical evidence only; this assessment will rerun
them with coverage before choosing thresholds. Live Microsoft speech checks
are useful acceptance tests but cannot be the only reproducible regression
checks. Windows GUI/playback tests require a Windows runner.

## Confirmed gaps and priorities

1. **QG-001, high: no enforced merge boundary.** GitHub API evidence above;
   unauthorized or untested changes can reach either branch. Add trusted checks
   and verified branch protection after the bootstrap policy is reviewed.
2. **QG-002, high: missing dependency/security verification.** Requirements and
   build scripts do not enforce reproducible Python dependencies or reject
   vulnerable releases. Add hashes, provenance/approval checks and independent
   secrets, SAST and dependency scans. Scanner findings require separate review;
   this control gap is not proof that application vulnerabilities exist.
3. **QG-003, medium: behavioral evidence is not enforced.** Existing tests are
   valuable but a passing local run is not a required merge check. Measure all
   scoped production files, enforce regression and changed-code coverage, and
   fail when required suites are absent, skipped or unsuccessful.
4. **QG-004, high: independent approval unavailable.** Do not substitute an AI
   response or the author's own approval. The owner must designate reviewers;
   the gate stays incomplete until the required human review exists.

## Assessment integrity and local tooling repair

Local MCP startup failures were reproduced before repairs: missing files in
Serena/WinDbg Python packages, Sequential Thinking's Node SDK and the Python
runtime used by Serena's language server. Packages/runtime were restored at
their installed versions. Windows Git Credential Manager sign-in was restored;
GitHub now connects directly through the official MCP endpoint and a private
credential helper. No credential is written to this repository. MCP health is
not evidence that application security or quality gates pass.

Coverage measurements, actual scanner findings and implementation readiness are
recorded separately. No human approval, clean scan or protected deployment is
assumed from the existence of this document.
