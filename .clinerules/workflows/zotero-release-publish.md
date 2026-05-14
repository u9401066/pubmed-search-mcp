# Release Publish: Zotero VS Code Extension

Prepare and publish a new tagged extension release.

## Step 1: Check working tree

<execute_command>
<command>git status --porcelain=v1</command>
</execute_command>

If there are uncommitted changes, ask whether to continue or stop.

## Step 2: Choose the version

Ask the user for the exact extension version `X.Y.Z` and confirm the tag will be `vX.Y.Z-ext`.

## Step 3: Update versioned files

Update:

- `vscode-extension/package.json`
- `vscode-extension/package-lock.json`
- `vscode-extension/CHANGELOG.md`
- Any tests or status fallbacks that assert the extension version.

If the Python server package is also being released, update the Python version sources separately.

## Step 4: Sync assets and verify

Execute the steps in `.clinerules/workflows/zotero-full-check.md`.

## Step 5: Commit

<execute_command>
<command>git add -A</command>
</execute_command>

<execute_command>
<command>git commit -m "Release VS Code extension vX.Y.Z"</command>
</execute_command>

Replace `X.Y.Z` with the confirmed version.

## Step 6: Tag and push

<execute_command>
<command>git tag -a vX.Y.Z-ext -m "Release vX.Y.Z-ext"</command>
</execute_command>

<execute_command>
<command>git push origin main</command>
</execute_command>

<execute_command>
<command>git push origin vX.Y.Z-ext</command>
</execute_command>

Verify the publish workflow after pushing.
