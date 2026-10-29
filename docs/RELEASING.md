# ECC terminal release procedure

Run from the repository root. Routine GitHub work uses `git` and `gh`.
Never substitute browser automation for an authentication or sandbox failure.

## What a release means

**"Release ECC to GitHub"** means validate and commit the intended source changes,
then push them to the established source destination, using a pull request if
remote rules or the user's instructions require one. It does not automatically
publish a staff update. **"Publish the ECC staff update to GitHub Releases"**
explicitly authorizes the additional version, packaging, tag, and publication
steps below. State the selected scope before performing remote writes.

As inspected on 2026-10-29:

- Source and release assets: `Enishi-Marketing/event_control_center` (public).
- Default and only branch: `main`, unprotected; no PR requirement was observed.
  Existing history includes direct source commits and `Release 0.1.x` commits.
- Latest published version: `v0.1.17`; local `VERSION`: `0.1.17`.
- No Actions workflows, runs, deployment environments, or deployment records
  were returned. There is no observed CI-driven production deployment.
- Staff updates use Sparkle's signed `appcast.xml` at
  `https://github.com/Enishi-Marketing/event_control_center/releases/latest/download/appcast.xml`.
  Publishing a new latest release with its signed feed can roll out an app
  update. A source push alone does not replace installed apps.

These are observations, not permanent remote policy. Rediscover them each time.

## 1. Inspect and select the destination

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
git remote -v
git diff --stat
git diff
git diff --cached
git ls-files --others --exclude-standard
gh auth status
gh repo view Enishi-Marketing/event_control_center \
  --json nameWithOwner,url,defaultBranchRef,viewerPermission,isPrivate
gh api repos/Enishi-Marketing/event_control_center --jq '{default_branch,permissions}'
gh api repos/Enishi-Marketing/event_control_center/branches/main
gh api repos/Enishi-Marketing/event_control_center/rules/branches/main
gh pr list --repo Enishi-Marketing/event_control_center --state open
gh release list --repo Enishi-Marketing/event_control_center --limit 10
gh workflow list --repo Enishi-Marketing/event_control_center --all
gh run list --repo Enishi-Marketing/event_control_center --limit 10
```

Check that `origin` still resolves to the intended repository before any write.
Do not stage everything simply because it is modified. Review untracked files
and distinguish intended changes from unrelated work, `.DS_Store`, generated
files, credentials, and local settings. Announce the intended file set, branch,
and destination. If these are clear from the request and evidence, proceed;
resolve material ambiguity with the user before committing.

After release authorization, fetch and check divergence (this changes local
Git metadata and may require sandbox approval):

```bash
git fetch origin --prune --tags
git rev-list --left-right --count HEAD...origin/main
git log --oneline origin/main..HEAD
```

Do not overwrite a remote update. Reconcile divergence while preserving local
work; do not automatically rebase a dirty checkout or stash unrelated changes.
If a PR is required, create an appropriate `codex/` branch rather than pushing
directly to protected `main`. Do not push a detached HEAD inadvertently.

## 2. Validate the intended source

On the setup Mac, the default macOS 27 SDK failed because SwiftUI macro plugins
were missing. The installed macOS 15.2 SDK passed the production build. If this
toolchain issue still applies, set the project's existing override before tests
and packaging (first confirm that the SDK path exists):

```bash
export ECC_SWIFT_SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX15.2.sdk
```

The build check below also honors that override. On another Mac, use its
validated toolchain; do not assume that this SDK path exists.

```bash
.venv/bin/python -m unittest discover -s tests -v
SWIFT_BUILD_ARGS=(--package-path swiftui --configuration release --scratch-path "$PWD/build/swift")
if [ -n "${ECC_SWIFT_SDK:-}" ]; then
  SWIFT_BUILD_ARGS+=(--sdk "$ECC_SWIFT_SDK" --build-system native)
fi
swift build "${SWIFT_BUILD_ARGS[@]}"
git diff --check
```

Use the existing `.venv`; dependencies are in `requirements.txt` and
`requirements-build.txt`. Do not reinstall them or re-authenticate routinely.
Swift compilation, `sips`, and signing tools may need access to normal macOS
caches or Keychain. If sandbox access is denied, request a scoped rerun of the
specific command. Do not treat a sandbox-induced test failure as a passing test.
Stop before remote release writes if required checks remain failed or unverified.

For a staff update, follow the packaging checks in step 4 before committing or
pushing release work. For a source-only change, a version bump is not mandatory.

## 3. Commit and push source (only after a release instruction)

Stage explicit reviewed paths using `git add -- <path> ...`, then inspect
`git diff --cached --check` and `git diff --cached`. Commit with a descriptive
message, e.g. `git commit -m 'Fix archive verification progress'` or, for a
versioned staff build, `Release X.Y.Z: <concrete change>`.

For the established direct-to-main workflow, once all checks pass:

```bash
git push origin HEAD:main
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

If rules or instructions require a PR instead, push the chosen `codex/` branch
with `git push -u origin <branch>`. Use `gh pr list --head <branch>` to discover
an existing PR, then `gh pr edit` or `gh pr create --base main --head <branch>`
as appropriate. Write multiline PR descriptions to a temporary file and pass
`--body-file`. Attach every created PR to the current Codex chat using its
`attach_artifact` tool. Do not merge merely to complete a push request. A staff
release must wait until its intended source commit is on the release branch.

Git metadata writes (`add`, `commit`, `fetch`, branch/tag creation) and pushes
may need separate sandbox approval. This is compatible with terminal operation;
it does not require Full Access mode or a browser.

## 4. Build staff assets (only within an explicitly requested staff update)

Inspect existing releases and tags before selecting a higher semantic version.
Never reuse a published version or replace assets in an existing published
release by default. Set `RELEASE_REPOSITORY` explicitly; if it differs from the
source repository, inspect that repository's visibility and permissions too.

For the existing no-fee staff distribution, choose the appropriate bump:

```bash
export RELEASE_REPOSITORY='Enishi-Marketing/event_control_center'
scripts/release_macos_app.sh patch
scripts/prepare_github_release.sh
```

`release_macos_app.sh` changes `VERSION` and calls `package_staff_dmg.sh`; it
does not commit, push, create a GitHub Release, or deploy. Use `minor`, `major`,
or `--version X.Y.Z` instead of `patch` when appropriate. If the intended new
version was already set but remains unpublished, use
`scripts/package_staff_dmg.sh` without bumping again. Confirm the build
succeeded and `VERSION` matches the intended source commit.

The build packages the Python backend with PyInstaller, compiles Swift in
release mode, bundles Sparkle and project templates, signs the app ad hoc,
verifies the signature, creates and verifies a DMG, and computes a checksum.
It targets the build Mac's CPU architecture and macOS 14+. Smoke-test the
distributed disk image on a staff Mac. Record if that test is unavailable.
Optional notarization follows `README.md`; do not select it or submit a build
to Apple without authorization for that distribution path.

`prepare_github_release.sh` checks the embedded feed destination and signs the
DMG and appcast with the existing Sparkle Keychain key. Never export the
private key into the repository or invent a replacement key. If it is missing
or Keychain access is unavailable, stop and report the blocker.

Before publication, verify the staged files and checksum:

```bash
VERSION="$(tr -d '[:space:]' < VERSION)"
DMG_NAME="Event.Control.Center.v${VERSION}.dmg"
(cd build/github-release && shasum -a 256 -c "$DMG_NAME.sha256")
cat build/github-release/appcast.xml
```

Check that the appcast names the intended version and exact destination asset
URL. Ensure the packaged source and `VERSION` have been committed and pushed
by step 3; do not upload a build containing unrelated or uncommitted code.
Build assets stay ignored in `build/` and `dist/`.

## 5. Tag and publish (explicit staff publication authorization required)

Recheck that no release or remote tag already uses the intended version.
For source and assets in the same repository, create an annotated local tag
at the exact validated commit and push that tag explicitly:

```bash
git tag -a "v$VERSION" <validated-commit-sha> -m "Release $VERSION"
git push origin "refs/tags/v$VERSION"
```

Create reviewed release notes in a temporary file, then publish the three
prepared assets (replace the notes path before executing):

```bash
gh release create "v$VERSION" \
  --repo "$RELEASE_REPOSITORY" --verify-tag \
  --title "Event Control Center v$VERSION" --notes-file /path/to/release-notes.md \
  --latest \
  "build/github-release/$DMG_NAME" \
  "build/github-release/$DMG_NAME.sha256" \
  build/github-release/appcast.xml
```

`--latest` publishes the staff update feed. A draft or prerelease does not
fulfill the normal latest-feed rollout. Never run this during setup or a
source-only release request. Do not use `--clobber` to overwrite published
assets. If assets use a separate repository, do not push the source tag there
blindly: establish that repository's tag/source-reference convention first
and include the source commit URL in release notes.

## 6. Inspect results and report

```bash
gh run list --repo Enishi-Marketing/event_control_center --limit 10
gh release view "v$VERSION" --repo "$RELEASE_REPOSITORY" \
  --json tagName,url,isDraft,isPrerelease,assets
git status --short --branch
git rev-parse HEAD
```

Run the release-view command only for a versioned release. If Actions runs
exist, inspect the relevant commit with `gh run view <run-id>` and
`gh run watch <run-id> --exit-status`; investigate failures with
`gh run view <run-id> --log-failed`. Do not dispatch or rerun a deployment
workflow without authorization. If no workflows exist, report **no Actions
workflows configured**, rather than claiming CI passed.

Report source commit SHA and URL, branch, pushed destination, PR URL if used,
version/tag and Release URL if published, checks and workflow status, and any
unperformed smoke test or remaining approval. For staff publication, verify
that the public latest-feed and asset URLs resolve before declaring success.

## Authentication and permission troubleshooting

Project defaults live in `.codex/config.toml`: workspace-write, on-request
approval with automatic review, and a GitHub-only network proxy allowlist.
The existing user configuration and credentials are not overwritten. A new
Codex session must load these settings; app-selected permissions, launch flags,
or managed policy can override them. `.git` and `.codex` remain protected.

First run `gh auth status`. If this environment cannot see a login that works
in the user's terminal, compare `HOME`, `GH_CONFIG_DIR`, and `XDG_CONFIG_HOME`
without printing token values. Use the existing secure configuration if it
can be located. Report missing authentication instead of repeatedly logging in
or falling back to a browser. Never run `gh auth token` into logs, copy tokens
into TOML, or use plaintext token files.

If there truly is no existing login, the user can perform the one-time repair
in their normal Mac terminal:

```bash
gh auth login --hostname github.com --git-protocol https
gh auth setup-git
gh auth status
```

Use macOS Keychain credential storage, never `--insecure-storage`. This repair
is not a recurring release step. GitHub write permissions and release access
must then be checked through `viewerPermission` and repository API permissions;
read-only access to a public repository does not establish permission to push.
