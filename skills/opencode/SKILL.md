---
name: gospelo-github-identity-check
description: Use before GitHub write operations such as git push, pull-request creation, release, merge, deploy, or package publish. Verify the repository identity and stop on mismatch or tool errors.
---

# gospelo-github-identity

Use this skill before any operation that writes to a remote GitHub repository or
publishes an artifact.

The CLI is managed by `uv`. Do not invoke the package with `python -m` or a
system `python` executable. If the CLI is missing, stop and instruct the user
to run `uv tool install gospelo-github-identity`.

Run the following command in the target repository:

```bash
gospelo-github-identity check
```

Handle the result as follows:

- Exit code `0`: continue with the requested operation.
- Exit code `1`: stop and show the mismatch and the suggested
  `gospelo-github-identity switch <profile>` command. Do not retry until the
  user fixes the identity or explicitly overrides the mismatch.
- Exit code `2`: show the error verbatim and do not assume a default identity.

The PATH guard is the final enforcement layer. Do not bypass it with absolute
paths or `GOSPELO_GITHUB_IDENTITY_SKIP=1` unless the user explicitly requests
that one-time override.
