# Validate Repository

Run the repository validation flow used for non-trivial changes.

## Step 1: Check the working tree context
<execute_command>
<command>git status --short</command>
<requires_approval>false</requires_approval>
</execute_command>

If there are unexpected changes, summarize them before continuing.

## Step 2: Run focused validation first when the task only touched a narrow slice
Use the smallest relevant pytest target for the changed files.
If the task is broad or already integration-heavy, continue directly to the full validation step.

## Step 3: Run repository-wide validation
<execute_command>
<command>uv run pytest -q && uv run mypy src/ tests/ && uv run python scripts/check_async_tests.py</command>
<requires_approval>false</requires_approval>
</execute_command>

If any command fails, stop and report the first actionable failure instead of continuing.

## Step 4: Summarize validation status
Report what passed, what failed, and any remaining risk or missing manual verification.