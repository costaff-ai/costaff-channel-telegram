# Security Policy

## Reporting a vulnerability

**Please do not open public GitHub issues for security problems.**

If you find a security issue:

1. Email the maintainer directly. The contact address is listed in
   the project README or available through the [costaff-ai org page](https://github.com/costaff-ai).
2. Provide enough detail to reproduce: affected version, steps to
   reproduce, and (if applicable) a proof-of-concept.
3. Allow up to **7 days** for an initial response and up to **30 days**
   for a coordinated fix before any public disclosure.

We will acknowledge receipt within 7 days, share an assessment within
14 days, and aim to ship a fix or mitigation within 30 days for
confirmed issues. Credit will be given in the fix release notes unless
you prefer to remain anonymous.

## What counts as a security issue

- Authentication / authorization bypass (license-key, MCP secret,
  channel tokens).
- Remote code execution via any input the agent or its tools accept.
- Credential leakage (env var dumping, log oversharing, history
  exposure).
- Privilege escalation between agents or between users (multi-tenant
  contexts).
- Any issue that lets a request escape the agent's intended sandbox
  (path traversal, command injection, SQL injection in tool inputs).

## What is NOT a security issue

- LLM jailbreaks that only affect the calling user's own session.
- Prompt injection where the consequence is bounded to that session's
  outputs.
- Rate-limit absence (we'll fix it, but please file as a normal issue).
- Bugs in dependencies — report to that dependency upstream.

## Supported versions

The `main` branch receives security fixes. Tagged releases older than
6 months are best-effort; please upgrade.
