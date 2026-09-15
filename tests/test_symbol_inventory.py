"""Coverage accounting must not lose definitions or silently certify stale code."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from scripts.perf.symbol_inventory import build_inventory, review_complete

if TYPE_CHECKING:
    from pathlib import Path

GIT = shutil.which("git")
assert GIT is not None


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run([GIT, "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    return tmp_path


def test_nested_methods_duplicate_definitions_and_hidden_files_are_inventoried(repository: Path) -> None:
    (repository / "src/module.py").write_text(
        "class Service:\n"
        "    async def run(self):\n"
        "        def callback():\n"
        "            return 1\n"
        "        return callback()\n"
        "    @property\n"
        "    def state(self): return 1\n"
        "    @state.setter\n"
        "    def state(self, value): pass\n",
        encoding="utf-8",
    )
    hidden = repository / ".hooks"
    hidden.mkdir()
    (hidden / "entry.py").write_text("def run(): pass\n", encoding="utf-8")
    inventory = build_inventory(repository)
    symbols = {s["id"].split("::", 1)[1]: s for s in inventory["symbols"]}
    assert set(symbols) == {
        "Service#1",
        "Service.run#1",
        "Service.run.callback#1",
        "Service.state#1",
        "Service.state#2",
        "run#1",
    }
    assert symbols["Service.run#1"]["async"] is True
    assert symbols["Service.run#1"]["kind"] == "method"
    assert symbols["Service.run.callback#1"]["kind"] == "nested_function"
    assert inventory["counts"]["src"]["classes"] == 1
    assert inventory["counts"]["src"]["functions"] == 4
    assert inventory["review_status_counts"] == {"pending": 6}
    assert not review_complete(inventory, "src/")


def test_file_changes_expire_reviews_and_deleted_definitions_remain_visible(repository: Path) -> None:
    source = repository / "src/module.py"
    source.write_text("def run(): return 1\n", encoding="utf-8")
    initial = build_inventory(repository)
    symbol = initial["symbols"][0]
    reviews = {
        symbol["id"]: {
            "file_sha256": symbol["file_sha256"],
            "decision": "retain",
            "reviewed_by": "reviewer",
            "notes": "Checked the return contract",
            "evidence": ["manual contract review"],
        }
    }
    assert review_complete(build_inventory(repository, reviews), "src/")
    assert not review_complete(initial, "does-not-exist/")
    source.write_text("import os\ndef run(): return 1\n", encoding="utf-8")
    changed = build_inventory(repository, reviews)
    assert changed["snapshot_sha256"] != initial["snapshot_sha256"]
    assert changed["review_status_counts"] == {"stale_review": 1}
    assert not review_complete(changed, "src/")
    source.write_text("def replacement(): return 2\n", encoding="utf-8")
    assert build_inventory(repository, reviews)["orphan_reviews"] == [symbol["id"]]


def test_parse_gaps_and_non_python_files_block_completion_without_counting_ignored_files(repository: Path) -> None:
    (repository / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repository / "ignored.py").write_text("invalid !!!\n", encoding="utf-8")
    (repository / "src/broken.py").write_text("def bad(\n", encoding="utf-8")
    (repository / "src/client.js").write_text("function run() {}\n", encoding="utf-8")
    inventory = build_inventory(repository)
    assert inventory["file_status_counts"] == {"parse_error": 1, "not_python": 1}
    assert not review_complete(inventory, "src/")
    assert all(file["path"] != "ignored.py" for file in inventory["files"])
    # Tracked files stay in scope even when a later ignore rule would hide them.
    subprocess.run([GIT, "add", "-f", "ignored.py"], cwd=repository, check=True)
    assert build_inventory(repository)["file_status_counts"]["parse_error"] == 2


def test_deleted_tracked_file_leaves_orphan_review_without_a_parse_gap(repository: Path) -> None:
    source = repository / "src/obsolete.py"
    source.write_text("def obsolete(): pass\n")
    subprocess.run([GIT, "add", "src/obsolete.py"], cwd=repository, check=True)
    symbol = build_inventory(repository)["symbols"][0]
    source.unlink()
    inventory = build_inventory(repository, {symbol["id"]: {"decision": "retain"}})
    assert inventory["files"] == []
    assert inventory["symbols"] == []
    assert inventory["orphan_reviews"] == [symbol["id"]]
    assert not review_complete(inventory, "src/")
