"""Build the working manuscript from pinned local evidence, without running benchmarks.

Use --prepare-only for offline validation; PDF compilation requires Tectonic.
Only an explicit source allowlist enters the arXiv ZIP. Nothing is submitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PUBLICATION = Path("docs/publication")
SOURCE_FILES = ("main.tex", "references.bib", "evidence.tex", "retrieval-table.tex", "execution-table.tex")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_evidence(root: Path) -> dict[str, Any]:
    """Refuse changed evidence or paths outside the repository's report directory."""
    manifest = json.loads((root / PUBLICATION / "evidence.json").read_text(encoding="utf-8"))
    records = {}
    for role, record in manifest["records"].items():
        path = (root / record["path"]).resolve()
        if not path.is_relative_to((root / "docs/reports").resolve()):
            raise ValueError(f"Evidence path is outside docs/reports: {record['path']}")
        if digest(path) != record["sha256"]:
            raise ValueError(f"Evidence hash mismatch: {record['path']}")
        records[role] = json.loads(path.read_text(encoding="utf-8"))
    return records


def validate_citations(manuscript: str, bibliography: str) -> None:
    """Check the manuscript's simple citation syntax before invoking a TeX engine."""
    entries = re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bibliography)
    if len(entries) != len(set(entries)):
        raise ValueError("Duplicate bibliography keys")
    cited = {
        key.strip()
        for group in re.findall(r"\\cite(?:p|t)?(?:\[[^\]]*\])*\{([^}]+)\}", manuscript)
        for key in group.split(",")
    }
    missing, unused = cited - set(entries), set(entries) - cited
    if missing or unused:
        raise ValueError(f"Bibliography mismatch: missing={sorted(missing)}, unused={sorted(unused)}")


def write_table(path: Path, columns: str, heading: str, rows: list[str], caption: str, label: str) -> None:
    path.write_text(
        "\\begin{table}[htbp]\n\\centering\\small\n"
        f"\\begin{{tabular}}{{{columns}}}\n\\toprule\n{heading} \\\\\n\\midrule\n"
        + "\n".join(row + r" \\" for row in rows)
        + f"\n\\bottomrule\n\\end{{tabular}}\n\\caption{{{caption}}}\\label{{{label}}}\n\\end{{table}}\n",
        encoding="utf-8",
    )


def prepare(root: Path, output: Path) -> dict[str, Any]:
    """Validate inputs and generate a portable TeX source directory."""
    records = load_evidence(root)
    manuscript = (root / PUBLICATION / "main.tex").read_text(encoding="utf-8")
    bibliography = (root / PUBLICATION / "references.bib").read_text(encoding="utf-8")
    validate_citations(manuscript, bibliography)
    output.mkdir(parents=True, exist_ok=True)
    for filename in SOURCE_FILES[:2]:
        shutil.copyfile(root / PUBLICATION / filename, output / filename)

    retrieval = records["retrieval"]["splits"]
    comparison = retrieval["test"]["comparison"]
    macros = {
        "NdcgBefore": retrieval["test"]["before"]["ndcg@10"],
        "NdcgAfter": retrieval["test"]["after"]["ndcg@10"],
        "NdcgDelta": comparison["ndcg@10"]["delta"],
        "NdcgLow": comparison["ndcg@10"]["paired_bootstrap_95_interval"][0],
        "NdcgHigh": comparison["ndcg@10"]["paired_bootstrap_95_interval"][1],
        "RecallDelta": comparison["recall@100"]["delta"],
        "RecallLow": comparison["recall@100"]["paired_bootstrap_95_interval"][0],
        "RecallHigh": comparison["recall@100"]["paired_bootstrap_95_interval"][1],
    }
    macro_text = "".join(f"\\newcommand{{\\{key}}}{{{value:.6f}}}\n" for key, value in macros.items())
    reduction = records["execution_after"]["scenarios"]["staggered"]["comparison"]["mcp"]["p50_reduction_percent"]
    (output / "evidence.tex").write_text(
        macro_text + f"\\newcommand{{\\StaggeredReduction}}{{{reduction:.2f}}}\n", encoding="utf-8"
    )
    rows = []
    for split, data in retrieval.items():
        for metric in ("ndcg@10", "recall@100", "precision@10"):
            before, after = data["before"][metric], data["after"][metric]
            rows.append(
                f"{split} ({data['query_count']}) & {metric} & {before:.6f} & {after:.6f} & {after - before:+.6f}"
            )
    write_table(
        output / "retrieval-table.tex",
        "llrrr",
        "Split ($n$) & Metric & Before & After & Difference",
        rows,
        "Historical NFCorpus lexical-scorer comparison (September 9, 2026). These are not full-agent scores.",
        "tab:retrieval",
    )
    rows = []
    for name, after in records["execution_after"]["scenarios"].items():
        before = records["execution_before"]["scenarios"][name]
        for field in ("signature", "provider_operations", "mcp_calls_per_sample"):
            if before[field] != after[field]:
                raise ValueError(f"Execution comparison changes required work: {name}/{field}")
        label = name.replace("_", "-")
        rows.append(
            f"{label} & {before['executor']['p50_ms']:.3f} & {after['executor']['p50_ms']:.3f}"
            f" & {before['mcp']['p50_ms']:.3f} & {after['mcp']['p50_ms']:.3f}"
            f" & {after['comparison']['mcp']['p50_reduction_percent']:+.2f}"
        )
    write_table(
        output / "execution-table.tex",
        "lrrrrr",
        "Scenario & Exec. before & Exec. after & MCP before & MCP after & Reduction (\\%)",
        rows,
        "Offline median latency in milliseconds, 20 repetitions per condition (September 18, 2026). "
        "Positive reduction means faster; negative means slower. Providers use fixed-delay fixtures.",
        "tab:execution",
    )
    citation = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    authors = " and ".join(f"{a['family-names']}, {a['given-names']}" for a in citation["authors"])
    software_bib = (
        "@software{pubmed_search_mcp,\n"
        f"  author = {{{authors}}},\n  title = {{{citation['title']}}},\n"
        f"  version = {{{citation['version']}}},\n  year = {{{str(citation['date-released'])[:4]}}},\n"
        f"  url = {{{citation['repository-code']}}}\n}}\n"
    )
    (output / "software-citation.bib").write_text(software_bib, encoding="utf-8")
    return {
        "status": "prepared; not compiled or submitted",
        "software_version": citation["version"],
        "evidence_manifest_sha256": digest(root / PUBLICATION / "evidence.json"),
        "evidence": json.loads((root / PUBLICATION / "evidence.json").read_text(encoding="utf-8"))["records"],
        "builder_sha256": digest(root / "scripts/build_publication.py"),
        "citation_cff_sha256": digest(root / "CITATION.cff"),
        "source_sha256": {name: digest(output / name) for name in SOURCE_FILES},
    }


def source_bundle(output: Path) -> Path:
    """Package only sources and the compiled bibliography, excluding local artifacts."""
    paths = [output / name for name in (*SOURCE_FILES, "main.bbl")]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unsafe publication source: {path.name}")
    bundle = output / "arxiv-source.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            info = zipfile.ZipInfo(path.name, date_time=(2026, 9, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/publication")
    parser.add_argument(
        "--prepare-only", action="store_true", help="Validate and generate sources without TeX or network"
    )
    parser.add_argument("--tectonic", default="tectonic", help="Path to a locally installed Tectonic executable")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == (ROOT / PUBLICATION).resolve() or (ROOT / PUBLICATION).resolve().is_relative_to(output):
        parser.error("Output must not overwrite the canonical publication workspace or its parents")
    # Stale output must not appear to validate this build, including prepare-only builds.
    for filename in ("main.pdf", "main.bbl", "main.log", "arxiv-source.zip", "manifest.json"):
        (output / filename).unlink(missing_ok=True)
    receipt = prepare(ROOT, output)
    if not args.prepare_only:
        result = subprocess.run(
            [args.tectonic, "--keep-intermediates", "--keep-logs", "--outdir", str(output), str(output / "main.tex")],
            check=False,
            capture_output=True,
            text=True,
        )
        print(result.stdout + result.stderr)
        result.check_returncode()
        log = (output / "main.log").read_text(encoding="utf-8", errors="replace")
        if re.search(r"undefined (?:citations|references)|Citation .+ undefined|Reference .+ undefined", log):
            raise ValueError("Unresolved citations or references in compiled manuscript")
        receipt["status"] = "compiled locally; not submitted"
        receipt["artifacts"] = {name: digest(output / name) for name in ("main.pdf", source_bundle(output).name)}
    (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Publication: {receipt['status']}; output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
