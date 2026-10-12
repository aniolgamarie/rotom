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

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
