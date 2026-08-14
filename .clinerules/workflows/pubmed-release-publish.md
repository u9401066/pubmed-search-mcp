# Release Publish: PubMed Search MCP

Prepare a new PubMed Search MCP release.

## Step 1: Check working tree

<execute_command>
<command>git status --porcelain=v1</command>
</execute_command>

If there are uncommitted changes, ask whether to continue or stop.

## Step 2: Choose the version

Ask the user for the exact version `X.Y.Z` and confirm the tag will be `vX.Y.Z`.

## Step 3: Update versioned files

Update:

- `pyproject.toml`
- `src/pubmed_search/__init__.py`
- `uv.lock`
- `CITATION.cff`
- `Dockerfile`
- `copilot-studio/openapi-schema.yaml`
- `CHANGELOG.md`
- Any downstream docs or skill references that mention the version.

## Step 4: Run full verification

Execute the steps in `.clinerules/workflows/pubmed-full-check.md`.

## Step 5: Commit

<execute_command>
<command>git add -u</command>
</execute_command>

Review every untracked path before staging it. Add intentional source, test,
documentation, and generated files with explicit pathspecs; never sweep local
fixtures, credentials, downloads, or review artifacts into a release tag.

<execute_command>
<command>git ls-files -o --exclude-standard</command>
</execute_command>

Review the staged set and keep each commit within the repository's 30-file
pre-commit limit:

<execute_command>
<command>git diff --cached --name-status</command>
</execute_command>

<execute_command>
<command>git diff --cached --check</command>
</execute_command>

Create focused implementation/documentation commits first and a final
`chore(release): prepare vX.Y.Z` metadata commit. Replace `X.Y.Z` with the
confirmed version.

## Step 6: Push, verify CI, and merge

Push a release branch, open a pull request to `master`, and wait for the full CI
workflow. Do not tag a commit that has not passed the branch/PR checks.

<execute_command>
<command>git push -u origin HEAD</command>
</execute_command>

<execute_command>
<command>gh pr checks --watch --fail-fast</command>
</execute_command>

Merge only after the checks pass and verify `origin/master` points at the merge
commit.

## Step 7: Tag and publish

Create the annotated tag on the verified master commit, then push it:

<execute_command>
<command>git tag -a vX.Y.Z VERIFIED_MASTER_SHA -m "Release vX.Y.Z"</command>
</execute_command>

<execute_command>
<command>git push origin vX.Y.Z</command>
</execute_command>

The tag-triggered publish workflow must finish all three jobs: distribution
verification, PyPI publication, and GitHub Release creation. Verify both PyPI
and the GitHub Release before announcing completion.

After publishing, update the parent Zotero Keeper submodule pointer and
extension pin if needed.
