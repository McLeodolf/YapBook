# Human review and exception records

Reviewer designation belongs in the protected policy and CODEOWNERS. The owner
must confirm competence and repository permissions. An AI reviewer, author,
unknown account, bot or approval on an older commit does not satisfy the gate.

## Architecture review

Review actual behavior and the attached evidence, then submit an actual GitHub
**Approve** review containing this record (replace every example value):

````text
YAPBOOK-REVIEW
```json
{
  "head_sha": "exact-current-40-character-PR-head-SHA",
  "decision": "approve",
  "components": ["specific affected components"],
  "risks": "Assessed architectural, security, performance and regression risks.",
  "actions": "Required actions and their resolution, or an explicit none with reason.",
  "exception_ids": []
}
```
````

The marker must immediately precede the fenced JSON in the review body. GitHub
supplies reviewer identity, review ID, URL and commit; text claiming an approval
in a PR description does not count. Changes Requested and dismissed reviews
supersede older approvals. New commits require new reviews.

Assess these questions proportionally to risk:

- Does the change solve the stated requirement, with explicit assumptions and useful failure behavior?
- Are presentation, parsing, speech, persistence and infrastructure responsibilities in the correct modules?
- Are EPUB/HTML, browser-message, filesystem and external-service trust boundaries preserved?
- Are request deduplication, bounded queues, cancellation, timeout and retry behavior correct under concurrency?
- Are interfaces and persisted reading positions/cache keys compatible, and errors observable without leaking text or credentials?
- Are dependency identity, license obligations and operational costs understood?
- Do tests demonstrate real behavior and meaningful failures, including hostile/invalid input and regressions?
- Are rollout, rollback, configuration and resource implications acceptable?

Low risk needs one designated peer. Medium risk needs an architecture reviewer.
High risk needs two distinct independent people, covering architecture and
security, plus a threat/failure analysis and rollback strategy. High risk is
computed from paths and cannot be downgraded in a PR description.

## Exception request

Add an object to `quality/exceptions.json`; do not change the failed stage to PASS.

```json
{
  "id": "EX-YYYY-NNN",
  "rule": "exact rule from the report",
  "fingerprint": "exact finding fingerprint from the report",
  "rationale": "Why immediate remediation is impractical and why the remaining risk is acceptable.",
  "owner": "accountable-github-login",
  "approver": "independent-designated-security-login",
  "compensating_controls": "Specific controls and a remediation issue/deadline.",
  "created_at": "YYYY-MM-DDTHH:MM:SSZ",
  "expires_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

Maximum duration is centrally configured (currently 30 days). The designated
security approver must list the exception ID in their exact-commit GitHub review.
The controller binds the recorded exception to that actual commit; the file does
not need a self-referential commit hash. Duplicate, unmatched, future-dated,
expired, unauthorized and overlong records fail. Secrets, malicious packages,
critical vulnerabilities and the protected rules in policy cannot be waived.

An approved exception remains visible with its underlying failed finding,
compensating controls, owner, expiry and actual approval URL. Under the current
personal-repository policy it does not make the merge check green; see the
merge-time expiry limitation in `03-tools-and-policy.md`.

For a false positive, provide specific evidence and a narrowly scoped rule or
fingerprint adjustment in a reviewed policy change. Do not use inline suppression
comments or broad exclusions. For revoked historic credentials, record rotation
evidence without including values, then obtain a specific history-scanner policy
decision. Review outstanding exceptions weekly and delete resolved records in
the remediation PR.
