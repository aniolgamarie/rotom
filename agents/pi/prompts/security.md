---
description: Security review of staged or specified changes
argument-hint: "[path or 'staged']"
---


Security review **$@** (default: `git diff --cached`).

## Threats to check

### High priority
- [ ] **Secrets**: hardcoded API keys, tokens, passwords, private keys (also in tests/fixtures!)
- [ ] **Injection**: SQL, command, LDAP, XPath, template, prompt
- [ ] **Auth bypass**: missing authn/authz checks, wrong role checks, IDOR
- [ ] **SSRF**: unbounded outbound HTTP, user-controlled URLs
- [ ] **Path traversal**: `../` in user-controlled file paths
- [ ] **XSS**: unsanitized HTML/JS in browser-rendered output
- [ ] **CSRF**: state-changing endpoints without CSRF protection
- [ ] **Crypto misuse**: ECB mode, MD5/SHA1 for auth, hardcoded keys, weak RNG

### Medium priority
- [ ] **Deserialization** of untrusted data (pickle/yaml.load/Marshal/JSON with prototypes)
- [ ] **Race conditions** in security-relevant code (TOCTOU)
- [ ] **Information disclosure**: error messages, logs, stack traces leaking PII/internals
- [ ] **Rate limiting** missing on auth/expensive endpoints
- [ ] **Dependency vulns**: outdated packages with known CVEs

### Low priority
- [ ] **Logging gaps**: security events not logged
- [ ] **CORS**: too permissive
- [ ] **Cookie flags**: `Secure`, `HttpOnly`, `SameSite`
- [ ] **HTTP headers**: CSP, HSTS, X-Content-Type-Options

## Output format

```markdown
## Security Review: <subject>

### CRITICAL (block merge)
- <file:line> — <issue> — <suggested fix>

### HIGH (fix before merge)
- ...

### MEDIUM (track as issue)
- ...

### LOW / Observations
- ...

### No issues found in:
- <areas you reviewed and cleared>
```

## Rules

- Cite **file:line** for every finding.
- Distinguish "I saw this" from "I worry about this" — do not pad with hypotheticals.
- If you used a heuristic (regex, pattern match) say so; do not pretend to have run a real scanner.
- If user input flows are unclear, ask before flagging.


## 执行路由

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
