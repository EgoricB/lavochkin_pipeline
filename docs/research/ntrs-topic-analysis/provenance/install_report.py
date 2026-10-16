from pathlib import Path
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone

ROOT = Path.cwd()
PACKAGE = Path(__file__).resolve().parent
TARGET = ROOT / "docs/research/ntrs-topic-analysis"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not (ROOT / ".git").exists():
        raise SystemExit("Run this script from the Git repository root.")
    if TARGET.exists():
        raise SystemExit(f"Target exists; nothing changed: {TARGET}")
    readme = ROOT / "README.md"
    if not readme.exists():
        raise SystemExit("README.md not found; nothing changed.")
    original = readme.read_text(encoding="utf-8-sig")
    start = "<!-- BEGIN NTRS RESEARCH -->"
    end = "<!-- END NTRS RESEARCH -->"
    if (start in original) != (end in original):
        raise SystemExit("Incomplete README markers; nothing changed.")
    block = (PACKAGE / "README_SECTION.md").read_text(encoding="utf-8")
    status = "Статус: проектирование. Реализация ещё не начата."
    replacement = ("Статус: исследование корпуса NASA NTRS выполнено в разведочном режиме; "
                   "программный конвейер и ML-планировщик — отдельное направление разработки.")
    updated = original.replace(status, replacement)
    if start in updated:
        updated = re.sub(re.escape(start) + r".*?" + re.escape(end),
                         lambda _: block.strip(), updated, flags=re.S)
    else:
        updated = updated.rstrip() + "\n\n" + block
    backup = ROOT / ".research-report-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True)
    shutil.copy2(readme, backup / "README.md")
    shutil.copytree(PACKAGE / "docs/research/ntrs-topic-analysis", TARGET)
    provenance = TARGET / "provenance"
    provenance.mkdir()
    scripts = [
        "audit_research_metadata.py", "prepare_metadata_corpus.py",
        "build_metadata_features.py", "run_metadata_nmf.py",
        "assess_metadata_stability.py", "check_metadata_sensitivity.py",
    ]
    metadata = [
        "metadata_corpus_v1/manifest.json",
        "metadata_audit_v1/audit_manifest.json",
        "metadata_audit_v1/exact_duplicate_groups.csv",
        "features_metadata_v1/feature_manifest.json",
        "features_metadata_v1/stopwords.json",
        "features_metadata_v1/environment.txt",
        "nmf_metadata_v1/experiment.json",
        "nmf_metadata_v1/run_summary.json",
        "nmf_metadata_stability_v1/stability_summary.csv",
        "nmf_metadata_stability_v1/assessment_manifest.json",
        "metadata_sensitivity_v1/manifest.json",
        "metadata_sensitivity_v1/run_metrics.csv",
        "metadata_sensitivity_v1/topic_changes.csv",
    ]
    copied, missing = [], []
    candidates = [(ROOT / x, Path("scripts") / x) for x in scripts]
    candidates += [(ROOT / "data/ntrs/research" / x, Path("experiments") / x) for x in metadata]
    for src, rel in candidates:
        if not src.is_file():
            missing.append(str(src.relative_to(ROOT)))
            continue
        dst = provenance / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append({"source": str(src.relative_to(ROOT)),
                       "snapshot": str(rel), "sha256": digest(dst)})
    shutil.copy2(Path(__file__), provenance / "install_report.py")
    (provenance / "snapshot_manifest.json").write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "copied": copied, "missing": missing,
        "note": "Local snapshots; execution provenance is not independently verified."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    readme.write_text(updated, encoding="utf-8")
    print("REPORT INSTALLED")
    print(f"Report: {TARGET / 'README.md'}")
    print(f"README backup: {backup / 'README.md'}")
    print(f"Provenance files copied: {len(copied)}; missing: {len(missing)}")
    print("No Git commit or push has been performed.")


if __name__ == "__main__":
    main()
