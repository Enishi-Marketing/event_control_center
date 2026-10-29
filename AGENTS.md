# ECC project instructions

## Project context

- ECC is a macOS desktop app: a SwiftUI frontend, Python backend, and a legacy
  Tkinter interface. Preserve the separation between UI and service logic, type
  hints, and existing project conventions.
- Read `README.md` for current behavior and packaging. `Codex.md` and the
  `Phase *.md` files describe earlier development phases; preserve them. Current
  dependencies and build scripts describe the evolved application.
- Use the existing `.venv` for Python. Run `.venv/bin/python -m unittest discover
  -s tests -v`; native tests require macOS, Swift, and normal system cache access.
- Do not expose local settings, Google credentials, tokens, or signing keys.
  Preserve unrelated changes, including untracked files and existing artifacts.

## Permanent GitHub workflow policy

- Prefer terminal `git` and `gh` for all GitHub operations: commits, pushes,
  branches, pull requests, tags, releases, and GitHub Actions inspection.
- Do not use Computer Use or browser automation for routine GitHub work or
  releases. Report terminal authentication, network, or sandbox failures with
  the failing command and the required remedy. Request narrowly scoped sandbox
  approval when needed; do not silently switch tools or repeat authentication.
- Before releasing, inspect repository status, root, branch, remotes, staged and
  unstaged diffs, untracked files, upstream divergence, and existing releases.
  Confirm the intended branch, source repository, and asset repository from
  user instructions and repository evidence. State an unambiguous established
  destination and proceed; ask only when a material ambiguity remains.
- Run applicable tests and production build checks before pushing release work.
  Follow existing branching, versioning, packaging, and release conventions in
  `docs/RELEASING.md`. Recheck remote rules and CI/CD rather than assuming the
  setup-time observations remain current. Use existing GitHub Actions where
  present. Creating a new workflow or dispatching a deployment requires scope
  appropriate to the user's request.
- Stage only intended, reviewed files with explicit paths. Never force-push,
  overwrite unrelated work, discard changes, expose secrets, or commit generated
  bundles, local credentials, or signing material. Do not bypass remote rules.
- Only publish or deploy when explicitly instructed. A source push, GitHub
  Release publication, and staff automatic-update rollout are separate actions.
  Publishing the latest signed appcast can update installed staff apps.
- The phrase **"Release ECC to GitHub"** authorizes the source-release procedure
  in `docs/RELEASING.md`: validate, commit intended changes, push, and create or
  update a PR if required. It does **not** by itself authorize publishing a
  Sparkle update, making a GitHub Release latest, or production deployment.
  Publish staff assets only when the user explicitly includes that action.
- Report the commit hash, branch, version if applicable, test/build results,
  workflow status (including when no workflows exist), and GitHub URLs. If a
  step is blocked, report what was completed and what remains unverified.
