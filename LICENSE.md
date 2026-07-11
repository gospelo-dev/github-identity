MIT License

Copyright (c) 2026 NoStudio LLC

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## User-Created Configuration

Configuration files (`config.yml`) authored by users using this software,
including profile definitions, path globs, git identities, and `gh` CLI
account references, are the intellectual property of their respective
creators. This license applies only to the gospelo-github-identity software itself,
not to the configuration content produced by or for it.

## External Tools and Credentials

This software invokes external tools (`git`, `gh` CLI) on the user's behalf
to read and modify local repository configuration and to switch GitHub
account contexts. The developers of gospelo-github-identity make no representations
or warranties regarding the behavior of these external tools or the safety of
the credentials they manage. Users are solely responsible for:

- Reviewing the planned changes before running `switch` (use `--dry-run` to
  preview, or run `check` first to confirm the target profile)
- Managing GitHub authentication credentials (`gh auth login`) and the
  scope/lifetime of access tokens in accordance with applicable laws,
  regulations, GitHub's terms of service, and their own security policies
- Any commits, pushes, releases, or other actions performed under the GitHub
  account selected by `switch`

## No Account Verification

gospelo-github-identity verifies that the locally configured git identity and `gh`
CLI active account match the user-declared profile for the current working
directory. It does **not** verify ownership of the GitHub account, employer
authorization, or any contractual obligations. Selecting a profile does not
grant any rights the user does not already hold. Users are solely responsible
for ensuring they have the right to publish under each configured account.
