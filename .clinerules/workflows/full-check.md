# Full Check (Python + VS Code Extension + Docker Smoke)

Run the full local verification gates for this repo.

## Step 1: Python lint/type/test
<execute_command>
<command>uv run ruff check .</command>
</execute_command>

<execute_command>
<command>uv run ruff format --check .</command>
</execute_command>

<execute_command>
<command>uv run mypy src --ignore-missing-imports</command>
</execute_command>

<execute_command>
<command>uv run pytest</command>
</execute_command>

If any step fails, stop and report the failures.

## Step 1.1: Release harness audit
<execute_command>
<command>python3 scripts/audit_release_harness.py</command>
</execute_command>

If it fails, stop and report the drift before changing release logic.

## Step 2: VS Code extension tests
<execute_command>
<command>npm --prefix vscode-extension run sync-assets:check</command>
</execute_command>

<execute_command>
<command>npm --prefix vscode-extension run test:ci</command>
</execute_command>

If it fails, stop and report the failures.

## Step 2.1: VSIX install/update smoke test
This is required before release. Activation smoke is required for release environments that can provide a display.
<execute_command>
<command>npm --prefix vscode-extension run test:install-smoke</command>
</execute_command>

- Windows/macOS: run `npm run test:install-smoke`
- Linux install/update only: run `npm run test:install-smoke`
- Linux with activation required: run `xvfb-run -a npm run test:install-smoke -- --require-activation` (requires `xvfb` and a few desktop libs)

## Step 3: Docker smoke import
<execute_command>
<command>docker build -t asset-aware-mcp:smoke .</command>
</execute_command>

<execute_command>
<command>docker run --rm --entrypoint python asset-aware-mcp:smoke -c "import src.presentation.server; print('server import ok')"</command>
</execute_command>

If it fails, stop and report the failures.

## Step 4: Packaging sanity check
<execute_command>
<command>uv build</command>
</execute_command>

<execute_command>
<command>python3 scripts/audit_release_artifacts.py</command>
</execute_command>

## Step 5: Diff hygiene
<execute_command>
<command>git diff --check</command>
</execute_command>
