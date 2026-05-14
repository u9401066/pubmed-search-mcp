# Release Publish (asset-aware-mcp)

Prepare and publish a new tagged release for this repository.

## Step 1: Ensure a clean working directory
<execute_command>
<command>git status --porcelain</command>
</execute_command>

If there are uncommitted changes, ask whether to continue or stop.

## Step 2: Choose how to bump the version
<ask_followup_question>
<question>How should I determine the next version?</question>
<options>["Patch (x.y.Z)", "Minor (x.Y.0)", "Major (X.0.0)", "Custom (enter exact X.Y.Z)"]</options>
</ask_followup_question>

Read the current version from `pyproject.toml`, compute the next semantic version if Patch/Minor/Major was chosen, and ask the user to confirm the exact `X.Y.Z`.

If Custom was chosen, ask the user for the exact version string (must match `^\\d+\\.\\d+\\.\\d+$` and have no leading `v`).

## Step 3: Update versions everywhere (keep in sync)
Update these files to the chosen version:
- `pyproject.toml`
- `src/__init__.py`
- `Dockerfile` image version label
- `vscode-extension/package.json`
- `vscode-extension/package-lock.json`
- `uv.lock` (run `uv lock` if needed)
- `CHANGELOG.md` (add a new dated section)

If any tests have version pins/expectations, update them too.

## Step 4: Run full verification
Execute the steps in `.clinerules/workflows/full-check.md` in this task.
If anything fails, stop and report the failures.

VSIX install/activation smoke is required for release. On Linux, prefer:
<execute_command>
<command>xvfb-run -a npm --prefix vscode-extension run test:install-smoke -- --require-activation</command>
</execute_command>

Validate release harness parity and built artifacts:
<execute_command>
<command>python3 scripts/audit_release_harness.py</command>
</execute_command>

<execute_command>
<command>python3 scripts/audit_release_artifacts.py</command>
</execute_command>

## Step 5: Commit
Stage only reviewed release changes, then create a release commit. Do not use
`git add -A`; it can sweep root PDFs, ad-hoc review docs, and experimental agent
files into a release tag/source archive.

<execute_command>
<command>git add -u</command>
</execute_command>

List untracked files and explicitly decide whether each belongs in the release.
If any root `*.pdf`, `docs/code-review-*`, ad-hoc `.github/agents/*.agent.md`,
new skill directory, or temporary review artifact appears here, leave it
unstaged unless it was intentionally reviewed as part of the release.

<execute_command>
<command>git ls-files -o --exclude-standard</command>
</execute_command>

Stage intentional new files with exact pathspecs only, for example:

<execute_command>
<command>git add -- src/application/ingest_worker.py src/presentation/markdown_utils.py scripts/count_tools.ps1 vscode-extension/resources/repo-assets/asset-aware/scripts/count_tools.ps1</command>
</execute_command>

Review the final staged set before committing:

<execute_command>
<command>git diff --cached --name-only</command>
</execute_command>

Validate the version in `pyproject.toml` is a strict `X.Y.Z`:
<execute_command>
<command>python3 scripts/get_version.py --strict-semver</command>
</execute_command>

Create a release commit:
<execute_command>
<command>git commit -m "Release $(python3 scripts/get_version.py --strict-semver)"</command>
</execute_command>

## Step 6: Push commit to origin
Push the default branch (`master`) to `origin`. If git credentials are missing, stop and ask the user to configure authentication.

<execute_command>
<command>git push origin master</command>
</execute_command>

## Step 7: Tag + push tag
Create an **annotated** tag named `vX.Y.Z` and push it to origin.

<execute_command>
<command>git tag -a "v$(python3 scripts/get_version.py --strict-semver)" -m "Release v$(python3 scripts/get_version.py --strict-semver)"</command>
</execute_command>

<execute_command>
<command>git push origin "v$(python3 scripts/get_version.py --strict-semver)"</command>
</execute_command>

Verify the tag exists on the remote (should include `refs/tags/vX.Y.Z`):
<execute_command>
<command>git ls-remote --tags origin</command>
</execute_command>
