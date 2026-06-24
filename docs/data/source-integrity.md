# Source integrity and locator semantics

Authoritative rules for `source_documents`, `source_passages`, and quote grounding
across case and jurisdiction YAML. Enforcement: `check_source_integrity.py`,
`check_source_links.py`, `validate_gold_quotes.py`.

---

## Locator semantics

For all `source_passages` entries:

- **`paragraph`** — official paragraph or recital number as printed in the authority
  document (e.g. `"79"` for EC recital (79), `5.44` for CMA). Not a PDF chunk index.
- **`page`** — printed page label in the document footer/header, not the PDF reader's
  0-indexed page. EC decisions: folio at bottom (often ~2-page offset from PDF index).
  US court opinions: court-filing header page (e.g. "Page 75 of 113").
- **`quote_snippet`** — verbatim text, character-for-character. No paraphrase. Do not
  add quotation marks the source omits.
- **`review_status: spot_checked`** — only after a human opened the source at the cited
  location and confirmed the quote is verbatim.

---

## Source documents

- `pdf_url` / `case_page_url` must resolve (HTTP 200, expected content-type).
- Do not add a document with only a title and no verified URL.
- `doc_type` must match the actual document (complaint vs decision vs opinion).

---

## Source passages

- Every passage must reference a `source_document_id` in the same record.
- Quotes must appear in the linked document at the stated page/paragraph.
- Complaint allegations are not adjudicated findings — use `definition_status: discussed`,
  not `defined`, when the only source is a complaint.
- If no verified source exists, omit the passage and mark notes `SOURCE NEEDED`.
- Outcome/clearance passages must not be linked in `supports_markets` or
  `supports_geographic_markets` (see [`promotion-checklist.md`](../operations/promotion-checklist.md)).

---

## Case history events

Record only events you are confident occurred. Public-record events without `source_url`
must be `review_status: unreviewed` with `SOURCE NEEDED` in the summary. Do not invent
procedural history.

---

## Remediation log

Historical corrections that inform locator practice:

| Case | Note |
|------|------|
| `eu_illumina_grail_2022` | Removed from canonical — PDF pointed to GC annulment, not 2022 prohibition |
| `eu_google_fitbit_2021` | Passages re-verified against M.9660; EC PDF page ≠ printed folio (~2 offset) |
| `uk_meta_giphy_2022` | `pdf_url` corrected to Remittal Final Report; paragraphs re-verified |
| `us_jetblue_spirit_2024` | Court-filing header page numbers used, not internal printed offset |
