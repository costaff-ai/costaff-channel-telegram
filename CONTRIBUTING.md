# Contributing

Thank you for considering a contribution. This document covers the
essentials — what we expect, how to sign off your commits, and how to
get a change merged.

## Developer Certificate of Origin (DCO)

Every commit must be signed off by the author. Signing off certifies
that you wrote the patch (or otherwise have the right to submit it
under the project's license) — see the [DCO 1.1 text](https://developercertificate.org/).

Sign off by adding a `Signed-off-by` line to your commit message. Git
will do this for you with the `-s` flag:

```bash
git commit -s -m "your commit message"
```

This adds a line like:

```
Signed-off-by: Your Name <[email protected]>
```

That's it. We do **not** require a CLA — DCO is lightweight and keeps
your authorship intact.

## How to submit a change

1. **Open an issue first** for anything beyond a typo, doc tweak, or
   small bugfix. We want to align on scope before you spend time.
2. **Fork & branch** from `main`.
3. **Run the test suite** — see the repo's `pytest.ini` / `README.md`
   for the test command. A PR with failing tests will not be reviewed.
4. **Keep the change focused.** One PR = one logical change. Drive-by
   reformatting belongs in a separate PR.
5. **Commit message format**: a single-line summary (≤72 chars), then
   a blank line, then optional details. Sign off (`-s`).
6. **Open a PR** against `main`. Describe what changed and why; link
   the issue.

## Style

- **Python**: PEP 8 + 4-space indent. Don't reformat existing code
  beyond your change's scope.
- **Comments**: explain *why*, not *what*. The code already shows what.
- **Tests**: add tests for new behaviour. We don't enforce coverage %,
  but new code without any test is unlikely to merge.

## Reporting bugs

File an issue with: what you expected, what actually happened, how to
reproduce, and your environment (OS, Python version, agent version).

## Reporting security issues

**Please do NOT open public issues for security problems.** See
[SECURITY.md](./SECURITY.md) for the responsible-disclosure path.

## What we won't merge

- PRs without DCO sign-off.
- PRs with secrets committed (API keys, tokens, .env files). Run
  `gitleaks detect` locally before pushing.
- Drive-by license changes.
- PRs that bypass the test suite.

Thanks for making CoStaff better.
