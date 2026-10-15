# NTRS corpus: initial analysis

This directory contains aggregate reports from the initial collection,
technical audit and metadata-based thematic analysis.

## Corpus snapshot

- Candidate metadata records: 1,527
- Records with local PDFs: 604
- Local PDF files: 606
- Records with multiple PDFs: 2
- PDFs matched to metadata: 606
- Unmatched PDFs: 0
- Total PDF bytes: 4,299,956,099
- Total pages: 24,637
- Mean pages per PDF: 40.66
- Median pages per PDF: 8
- Maximum pages per PDF: 1,757
- Exact duplicate files detected by SHA-256: 0

## Technical audit

- Non-empty text extracted without registered extraction errors: 604 PDFs
- No extractable text: 1 PDF
- Page-level text extraction errors: 1 PDF

Successful extraction does not establish text completeness or correctness.

## Preliminary thematic analysis

Classification uses document titles and abstracts only.
Search queries are not used as classification evidence.

Among the 604 records with local PDFs:

- MENTIONS_FOUND: 215
- AMBIGUOUS_MENTIONS: 214
- NO_RULE_MATCH: 175

The states are mutually exclusive, but thematic labels overlap.
AMBIGUOUS_MENTIONS records may also contain numbered mission labels.

Labels indicate mentions, not confirmed main subjects or museum relevance.
No rule match does not mean that a document is irrelevant.
The rules cover only an explicitly listed set of names.

## Limitations

- Relevance remains UNREVIEWED.
- No mission-year filtering has been applied.
- Publication-year analysis has not been performed.
- Search-query counts overlap and must not be summed as unique records.
- Records without local PDFs are not automatically download failures.
- PDF counts and metadata-record counts are different units.
- Full PDFs, extracted texts and complete metadata exports are not
  included in this directory.

## Scripts

Run from the project root in the following order:

1. audit_ntrs_pdfs.py
2. build_ntrs_corpus.py
3. analyze_ntrs_corpus.py
4. classify_ntrs_metadata.py

The audit requires locally downloaded PDFs and pypdf.
The corpus builder also requires data/ntrs/candidates.json.
The scripts do not reproduce the initial download by themselves.

Generated review tables should be copied before manual editing because
rerunning the scripts overwrites their generated outputs.
