# Terminal GitHub setup report

Verified 2026-10-29 (Japan time). No commits, pushes, tags, releases, remote
settings changes, or deployment triggers were performed during setup.

## Local changes

- `.codex/config.toml`: ECC-scoped sandbox, approvals, and GitHub network policy.
- `AGENTS.md`: permanent terminal-first GitHub policy and release authorization
  boundaries. No pre-existing AGENTS.md was found in the repository or ancestor
  locations checked; existing `Codex.md`, phase documents, and scripts remain.
- `docs/RELEASING.md`: reusable source and staff publication procedures.
- `README.md`: added a link to the release procedure, preserving existing work.
- This report records verification and outstanding limitations.

`~/.codex/config.toml` was inspected and left unchanged. It contained project
trust, model, plugin, notification, and app settings, but no explicit sandbox,
approval, or terminal-network defaults. Its Computer Use notification command
does not constitute a requirement to use browser automation for GitHub.

## Resulting settings and scope

```toml
sandbox_mode = "workspace-write"
approval_policy = "on-request"
approvals_reviewer = "auto_review"

[sandbox_workspace_write]
network_access = true

[features.network_proxy]
enabled = true
```

The proxy uses exact allow rules for `github.com`, `api.github.com`,
`uploads.github.com`, `objects.githubusercontent.com`,
`release-assets.githubusercontent.com`, `raw.githubusercontent.com`, and
`codeload.github.com`. Other terminal destinations remain blocked under this
configuration. Dependency hosts outside GitHub require a separate permission
decision. No credentials, blanket command allow rules, extra writable home
directories, unrestricted execution mode, or permanent Full Access were added.

The installed `codex-cli 0.165.0-alpha.1.2` accepts these fields with
`app-server --strict-config --print-startup-config`. Its `config/read` API
confirmed the project layer supplies all the settings above, including the
network domain table. No local `/etc/codex/config.toml`,
`/etc/codex/requirements.toml`, or `~/.codex/requirements.toml` was found.
This does not exclude app/session or remotely managed constraints.

The original chat retains its launch-time restricted network policy. New
sessions load the saved defaults unless app-selected permissions, command-line
overrides, or managed policy take precedence. No app restart or live-session
permission change was claimed. The repo is already marked trusted globally.

Fresh execution through the installed app server's `command/exec` API, using
the saved project policy without a sandbox override, verified:

- GitHub API HEAD request: HTTP 200, exit 0.
- An unlisted public host: HTTP 403, `x-proxy-error: blocked-by-allowlist`.

The standalone `codex sandbox` helper did not establish GitHub access in its
default mode; the successful test above used the app server's configured
execution path. The installed helper syntax differs from some current web
examples, so use installed `--help` rather than assuming platform subcommands.

`.git` and `.codex` stay protected. A non-mutating attempt to open `.git/index`
for writing was denied in the original sandbox; index size and modification
time stayed unchanged. Staging, commits, fetching, branching, tagging, and
pushes can therefore require individual approval. Eligible approval requests
go through automatic review; approval is not guaranteed. Compiler caches,
Keychain access, packaging, and signing may also need scoped approval.

## Repository and verification

Root: `/Users/marketing/Documents/GitHub/event_control_center`.
Branch: `main`. Origin:
`https://github.com/Enishi-Marketing/event_control_center.git`.
HEAD: `701f922b0f521d197455fdd10deaf72c163ee38f`.
The checkout had existing modified and untracked application files before
setup. They were not committed, staged, discarded, or edited by this task.

| Capability | Result |
| --- | --- |
| Tools | Apple Git 2.54.0; gh 2.102.0; existing release/build scripts present |
| Git transport | Approved terminal `git ls-remote origin HEAD` succeeded and matched local HEAD |
| Public repository/API reads | Succeeded from terminal using unauthenticated GitHub REST requests |
| Branches/rules | Only `main`; unprotected; no rulesets or active main rules returned |
| Pull requests | Read succeeded; none returned |
| Releases | Read succeeded; latest `v0.1.17`, then `v0.1.16` and `v0.1.15` |
| Release assets | Latest has signed appcast, DMG, and DMG SHA-256 checksum |
| Actions | Read succeeded; zero workflows and runs; workflow directory HTTP 404 |
| Deployment metadata | Read succeeded; no environments or deployments returned |
| gh authentication | After the user completed login, approved terminal verification succeeded as `Enishi-Marketing`, using Keychain and HTTPS |
| gh authenticated API/PR/release/Actions commands | Passed: repository, API, branches, PRs, releases, workflows, and runs inspected through gh |
| GitHub write role/token scope | `viewerPermission: ADMIN`; API reports push/admin/maintain access; token scopes include `repo` and `workflow`; actual writes remain intentionally untested |
| Actual commits/pushes/publication | Intentionally not tested |
| Unit tests | All 83 passed with normal macOS access and SDK override |
| Production Swift build | Passed with macOS 15.2 SDK and existing native-build override |
| Shell scripts/diff whitespace | Existing release shell scripts passed `bash -n`; tracked diff passed `git diff --check` |

Initial sandbox tests hit Swift/system-cache and `sips` access failures; those
tests passed with approved macOS resource access. The default macOS 27 SDK
failed SwiftUI macro loading even with approved access. The successful build
command was:

```bash
swift build --package-path swiftui --configuration release \
  --scratch-path "$PWD/build/swift" \
  --sdk /Library/Developer/CommandLineTools/SDKs/MacOSX15.2.sdk \
  --build-system native
```

It reported existing Swift isolation warnings and a native-build-system
deprecation warning. No application-code fixes were made for these warnings.
The full test suite also passed with `ECC_SWIFT_SDK` set to that SDK.
DMG packaging, staff installation, Sparkle private-key access, signed-feed
generation, and optional notarization were not exercised by this setup.
Existing distributed bundles were not rebuilt or replaced.

## Authentication repair and likely prior fallback causes

Initially, `gh auth status` reported **You are not logged into any GitHub
hosts**, both in the sandbox and with approved host access. `HOME` was
`/Users/marketing`; `GH_CONFIG_DIR` and `XDG_CONFIG_HOME` were unset, and no
GitHub token variables or expected gh config directory were visible. A
metadata-only lookup did not find the expected `gh:github.com` Keychain item.
No unmasked token values were retrieved or printed.

The user subsequently completed the terminal login. Follow-up verification on
2026-10-29 succeeded as `Enishi-Marketing`, with the active credential stored
in Keychain, HTTPS Git transport, and token scopes `gist`, `read:org`, `repo`,
and `workflow`. The repository reports `viewerPermission: ADMIN`, and its API
reports `push`, `admin`, and `maintain` permissions. The authentication blocker
is resolved; do not repeat login as a routine release step.

Authenticated `gh` calls successfully inspected the repository, API, branch
list, PRs, releases, workflows, and runs. The observed branch remained `main`,
the latest release remained `v0.1.17`, and no PRs or Actions workflows/runs were
returned. `git ls-remote origin HEAD` again matched the SHA above. No remote
write was attempted; actual push, tag, and publication success remains
untested by design.

Before setup, terminal networking failed with DNS errors under this chat's
sandbox; approved Git transport worked. This, missing visible gh login, and
protected Git metadata explain concrete terminal blockers. There is no
evidence that GitHub itself requires Computer Use. Historical attempts were
not reconstructed, so these findings do not establish every prior cause.

For reference, the one-time repair the user completed was:

```bash
gh auth login --hostname github.com --git-protocol https
gh auth setup-git
gh auth status
```

These read-only checks passed through approved terminal execution after login;
they can be repeated in a new ECC session to confirm its access:

```bash
gh repo view Enishi-Marketing/event_control_center \
  --json nameWithOwner,url,defaultBranchRef,viewerPermission
gh api repos/Enishi-Marketing/event_control_center --jq '{permissions}'
gh api repos/Enishi-Marketing/event_control_center/branches
gh pr list --repo Enishi-Marketing/event_control_center
gh release list --repo Enishi-Marketing/event_control_center
gh workflow list --repo Enishi-Marketing/event_control_center --all
gh run list --repo Enishi-Marketing/event_control_center
git ls-remote origin HEAD
```

Codex did not initiate another authentication flow or change remote settings.

## Future instructions

- **Release ECC to GitHub.** Follow `docs/RELEASING.md` to validate, commit the
  intended source, and push (with a PR if required), then report results.
- **Publish the ECC staff update to GitHub Releases.** Explicitly includes
  building/signing the next version and publishing the latest Sparkle assets.

Authentication and repository permission checks are now verified. New sessions
must still load the project settings, and individual Git metadata/Keychain or
other sandbox approvals may be required. A real release must still complete
the documented checks, signing, and publication steps appropriate to its scope.

Supported configuration and security behavior were checked against the
[official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic),
and [sandbox/network guidance](https://learn.chatgpt.com/docs/agent-approvals-security).
