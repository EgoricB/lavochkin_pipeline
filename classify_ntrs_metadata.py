import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "ntrs"
OUT = BASE / "thematic"

FLAGS = re.IGNORECASE
SEP = r"[\s\u2010-\u2015-]*"
DASH_OR_SPACE = r"[\s\u2010-\u2015-]+"

RULES = []


def add_rule(label, group, pattern):
    RULES.append({
        "label": label,
        "group": group,
        "regex": re.compile(pattern, FLAGS),
    })


add_rule("Lavochkin", "organization", r"\bLavochkin(?:a)?\b|Лавочкин[а-я]*")
add_rule("Lunokhod", "lunar", r"\bLunokhod(?:s)?\b|Луноход[а-я]*")
add_rule("Venera", "venus", r"\bVenera\b|Венера")

for number in (9, 10, 13, 16, 17, 20, 21, 24):
    add_rule(
        f"Luna {number}",
        "lunar",
        rf"(?:\bLuna|Луна){SEP}{number}(?!\w)",
    )

for number in (1, 2):
    add_rule(
        f"Vega {number}",
        "vega",
        rf"(?:\bVega|Вега){SEP}{number}(?!\w)",
    )

for number in (2, 3, 4, 5, 6, 7):
    add_rule(
        f"Mars {number}",
        "mars",
        rf"(?:\bMars|Марс){SEP}{number}(?!\w)",
    )

for number in (1, 2):
    add_rule(
        f"Phobos {number}",
        "phobos_numbered",
        rf"(?:\bPhobos|Фобос){SEP}{number}(?!\w)",
    )

AMBIGUOUS_RULES = [
    (
        "Phobos without a numbered designation",
        re.compile(r"\bPhobos\b|Фобос[а-я]*", FLAGS),
        re.compile(
            rf"(?:\bPhobos|Фобос){SEP}[12](?!\w)", FLAGS
        ),
    ),
    (
        "Vega without a numbered designation",
        re.compile(r"\bVega\b|Вега", FLAGS),
        re.compile(
            rf"(?:\bVega|Вега){SEP}[12](?!\w)", FLAGS
        ),
    ),
]


def write_csv(name, rows, fields):
    with (OUT / name).open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def context(text, start, end, radius=100):
    fragment = text[max(0, start - radius): min(len(text), end + radius)]
    return re.sub(r"\s+", " ", fragment).strip()


def classify(document):
    fields = {
        "title": str(document.get("title") or ""),
        "abstract": str(document.get("abstract") or ""),
    }
    labels = []
    groups = set()
    evidence = []
    ambiguity = []

    for rule in RULES:
        matched = False
        for field, text in fields.items():
            matches = list(rule["regex"].finditer(text))
            if matches:
                matched = True
            for match in matches[:3]:
                evidence.append({
                    "label": rule["label"],
                    "field": field,
                    "matched_text": match.group(),
                    "context": context(text, match.start(), match.end()),
                })

        if matched:
            labels.append(rule["label"])
            groups.add(rule["group"])

    for reason, broad_pattern, numbered_pattern in AMBIGUOUS_RULES:
        for field, text in fields.items():
            numbered_spans = [
                match.span() for match in numbered_pattern.finditer(text)
            ]

            for match in broad_pattern.finditer(text):
                inside_numbered = any(
                    start <= match.start() and match.end() <= end
                    for start, end in numbered_spans
                )
                if not inside_numbered:
                    ambiguity.append({
                        "reason": reason,
                        "field": field,
                        "matched_text": match.group(),
                        "context": context(text, match.start(), match.end()),
                    })
                    break

    has_metadata = any(text.strip() for text in fields.values())

    if not has_metadata:
        state = "INSUFFICIENT_METADATA"
    elif ambiguity:
        state = "AMBIGUOUS_MENTIONS"
    elif labels:
        state = "MENTIONS_FOUND"
    else:
        state = "NO_RULE_MATCH"

    return {
        "method": "rule_based_title_abstract_mentions",
        "rule_version": "1.0",
        "state": state,
        "labels": labels,
        "groups": sorted(groups),
        "evidence": evidence,
        "ambiguous_mentions": ambiguity,
        "relevance": "UNREVIEWED",
        "human_review_completed": False,
    }


def main():
    corpus = json.loads(
        (BASE / "processed" / "corpus.json").read_text(encoding="utf-8")
    )
    documents = corpus["documents"]
    OUT.mkdir(parents=True, exist_ok=True)

    labels_all = Counter()
    labels_pdf = Counter()
    states_all = Counter()
    states_pdf = Counter()
    table = []
    evidence_rows = []

    for document in documents:
        result = classify(document)
        document["thematic_preliminary"] = result
        has_pdf = bool(document.get("files"))

        states_all[result["state"]] += 1
        if has_pdf:
            states_pdf[result["state"]] += 1

        for label in result["labels"]:
            labels_all[label] += 1
            if has_pdf:
                labels_pdf[label] += 1

        row = {
            "ntrs_id": document["ntrs_id"],
            "title": document.get("title") or "",
            "abstract": document.get("abstract") or "",
            "has_local_pdf": has_pdf,
            "labels": "; ".join(result["labels"]),
            "groups": "; ".join(result["groups"]),
            "classification_state": result["state"],
            "ambiguity_reasons": "; ".join(sorted({
                item["reason"] for item in result["ambiguous_mentions"]
            })),
            "human_decision": "",
            "human_notes": "",
        }
        table.append(row)

        for item in result["evidence"]:
            evidence_rows.append({
                "ntrs_id": document["ntrs_id"],
                "kind": "label_evidence",
                "label_or_reason": item["label"],
                "field": item["field"],
                "matched_text": item["matched_text"],
                "context": item["context"],
            })

        for item in result["ambiguous_mentions"]:
            evidence_rows.append({
                "ntrs_id": document["ntrs_id"],
                "kind": "ambiguous_mention",
                "label_or_reason": item["reason"],
                "field": item["field"],
                "matched_text": item["matched_text"],
                "context": item["context"],
            })

    label_rows = [
        {
            "label": label,
            "candidate_records": labels_all[label],
            "records_with_pdf": labels_pdf[label],
        }
        for label in sorted(
            labels_all, key=lambda value: (-labels_all[value], value)
        )
    ]

    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_records": len(documents),
        "records_with_local_pdf": sum(
            bool(document.get("files")) for document in documents
        ),
        "classification_states_all": dict(sorted(states_all.items())),
        "classification_states_with_pdf": dict(sorted(states_pdf.items())),
        "preliminary_label_counts": label_rows,
        "relevance": "UNREVIEWED",
        "notes": [
            "Labels indicate mentions, not confirmed main subjects.",
            "Search queries are not used for classification.",
            "Labels overlap and their counts must not be summed.",
            "No match does not mean irrelevant.",
            "Numbered names may still be ambiguous in context.",
            "Rules are limited to the explicitly listed names.",
        ],
    }

    corpus["thematic_analysis"] = summary

    (OUT / "corpus_thematic.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "thematic_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fields = [
        "ntrs_id", "title", "abstract", "has_local_pdf",
        "labels", "groups", "classification_state",
        "ambiguity_reasons", "human_decision", "human_notes",
    ]
    write_csv("thematic_records.csv", table, fields)
    write_csv(
        "review_queue_with_pdf.csv",
        [row for row in table if row["has_local_pdf"]],
        fields,
    )
    write_csv(
        "unmatched_records.csv",
        [
            row for row in table
            if row["classification_state"]
            in {"NO_RULE_MATCH", "INSUFFICIENT_METADATA"}
        ],
        fields,
    )
    write_csv(
        "thematic_counts.csv",
        label_rows,
        ["label", "candidate_records", "records_with_pdf"],
    )
    write_csv(
        "classification_evidence.csv",
        evidence_rows,
        [
            "ntrs_id", "kind", "label_or_reason",
            "field", "matched_text", "context",
        ],
    )

    print("THEMATIC ANALYSIS COMPLETE")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nOutput folder: {OUT}")


if __name__ == "__main__":
    main()
