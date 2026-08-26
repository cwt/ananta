# Security Policy

## Supported Versions

| Version                                     | Supported          |
| ------------------------------------------- | ------------------ |
| HEAD (Git) / tip (Hg) (ongoing development) | :white_check_mark: |
| Latest release (`vX.Y.Z` marked as `latest`)| :white_check_mark: |
| Older releases                              | :x:                |

**Note**: Security fixes are applied to the current development (HEAD/tip) first. A new tagged release will follow to incorporate these updates.

## Reporting a Vulnerability

Please do not report security issues via public GitHub Issues or SourceHut Tickets. Instead, email vulnerabilities to my email address listed in the [LICENSE](LICENSE) file. Include:
- A description of the vulnerability.
- Steps to reproduce (if applicable).
- Potential impact.

As this is a *single person* project, I aim to acknowledge your report within **7 days** and will keep you updated on the resolution process.

## Disclosure

I follow a **coordinated disclosure** process. Please give me time to investigate and address the issue before disclosing it publicly.
Once resolved, vulnerabilities will be announced with credits to the reporter, unless you prefer to remain anonymous.

Thank you for helping keep this project secure!

## Built-in Host-Key Verification

Ananta verifies every server's SSH host key against `~/.ssh/known_hosts`
before executing any command. There is no option to disable this check.

- **Known key, matches** — connects normally.
- **Unknown host** — trusted on first use (TOFU): the key is appended to
  your `known_hosts` file and reported with its fingerprint after the session.
- **Key changed since last connection** — the connection is refused without
  retries and the entire batch is aborted *before any command executes*
  (exit code 3), showing both the recorded and presented fingerprints.

This design protects against man-in-the-middle attacks and prevents
partially-applied changes across a fleet of hosts. A key change can only be
accepted by re-running with `--override-mismatched-keys` and explicitly
typing `CONFIRM`, which replaces the stale entry.

Scope notes for security reviewers:
- Hashed (`|1|salt|hash`) known_hosts entries are supported; wildcard host
  patterns and certificate authority entries (`@cert-authority`) are
  currently ignored rather than trusted.
- Host keys are verified during the pre-flight connect phase using the same
  connection that later executes commands, avoiding a check-then-use gap.
- The TUI applies the same policy; mismatched hosts are refused and flagged,
  but the CONFIRM override flow is only available in non-TUI mode.
