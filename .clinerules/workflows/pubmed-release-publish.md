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
- `CHANGELOG.md`
- Any downstream docs or skill references that mention the version.

## Step 4: Run full verification

Execute the steps in `.clinerules/workflows/pubmed-full-check.md`.

## Step 5: Commit

<execute_command>
<command>git add -A</command>
</execute_command>

<execute_command>
<command>git commit -m "Release vX.Y.Z"</command>
</execute_command>

Replace `X.Y.Z` with the confirmed version.

## Step 6: Tag and push

<execute_command>
<command>git tag -a vX.Y.Z -m "Release vX.Y.Z"</command>
</execute_command>

<execute_command>
<command>git push origin master</command>
</execute_command>

<execute_command>
<command>git push origin vX.Y.Z</command>
</execute_command>

After publishing, update the parent Zotero Keeper submodule pointer and extension pin if needed.
