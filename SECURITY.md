# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in Watchtower, please **do not** open a public issue.

Instead, please report it privately by emailing the maintainer. Include:

1. A description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if any)

You should receive a response within 72 hours. We'll work with you to understand the issue and coordinate a fix before any public disclosure.

## Scope

Watchtower is designed with multiple security layers (Glass content filter, Docker sandbox, Bandit scanning, secret detection, hash-chained audit log). The following are in-scope for security reports:

- Sandbox escapes (agent code affecting the host)
- Prompt injection bypasses through the Glass content filter
- Secret leakage through model output or logs
- Audit log tampering or hash-chain bypass
- Guardrails bypass (e.g., importing non-stdlib packages when `stdlib_only: true`)
- Arbitrary code execution outside the sandbox

## Out of scope

- Vulnerabilities in upstream dependencies (report to those projects directly)
- Issues requiring physical access to the machine
- Social engineering attacks on the human-in-the-loop approval flow
