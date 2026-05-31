# Data Quality Notes

## Locator semantics (authoritative definition)

For all `source_passages` entries the following rules apply:

- **`paragraph`** — the official paragraph or recital number as printed in the authority
  document, e.g. `(79)` in an EC decision (written as `"79"` in YAML), `5.44` in a CMA
  report, or omitted for US court opinions that do not number paragraphs. It must NOT be
  a PDF page-chunk index, extraction offset, or any internally-derived number.
- **`page`** — the printed page label shown in the document footer/header (not the PDF
  reader's 0-indexed page). For EC decisions, use the folio page printed at the bottom
  (e.g. EC M.9660 PDF page 26 = printed page 24). For CMA reports, printed = PDF page.
  For US court opinions filed with PACER, use the court-filing page number shown in the
  document header (e.g. "Page 75 of 113").
- **`quote_snippet`** — verbatim text copied character-for-character from the cited
  paragraph, including original punctuation, hyphenation, and spelling. No paraphrases.
  EC decisions often omit surrounding quotation marks in continuous prose — do not add them.
- **`review_status: spot_checked`** — may only be set after a human has opened the source
  document, located the cited paragraph/page, and confirmed that `quote_snippet` is
  verbatim text from that location.

---

## EU Cases

### eu_illumina_grail_2022 — removed from canonical dataset (2026-05-30)

Removed due to source document mismatch: the pdf_url pointed to the 2024 General Court
annulment document, not the original 2022 Commission prohibition decision (M.10188).
Re-add once the correct prohibition decision PDF is located. Registry:
`https://competition-cases.ec.europa.eu/cases/M.10188`

---

### eu_google_fitbit_2021 — passages verified 2026-05-30

All three passages replaced with verbatim text verified against the EC M.9660 decision PDF
(`m9660_3314_3.pdf`, 254 pages). Corrections made:

| Passage | Old (wrong) | Correct |
|---------|-------------|---------|
| sp_1 | para 88, p.14 — OS precedent paragraph, wrong topic | para 79, p.24 — product market conclusion |
| sp_2 | para 130, p.21 — app store geographic scope, wrong topic | para 427, p.98 — advertising data concern |
| sp_3 | para 51, p.9 — search engine description, wrong topic | para 84, p.25 — geographic market conclusion |

Product market name corrected from "Wearable fitness devices" → "Wrist-worn wearable devices"
to match EC decision terminology.

Note: EC M.9660 PDF uses a 2-page offset between PDF reader page and printed folio
(PDF page 26 = printed page 24).

---

## UK Cases

### uk_meta_giphy_2022 — passages verified 2026-05-30

**pdf_url corrected:** was pointing to `Final_Order__Remittal_.pdf` (a remedial order);
now points to `Final_Report_Meta.GIPHY.pdf` (CMA Remittal Final Report, 18 October 2022,
433 pages). Original `published_date` updated to `2022-10-18`.

All three passages replaced with verbatim text from the Remittal Final Report. Corrections:

| Passage | Old (wrong) | Correct |
|---------|-------------|---------|
| sp_1 | para 5.23, p.80 — GIF sticker substitutability | para 5.44, p.85 — searchable GIF library market definition |
| sp_2 | para 7.41, p.200 — GIPHY innovation analysis | para 8.10, p.272 — vertical foreclosure SLC conclusion |
| sp_3 | para 6.18, p.150 — counterfactual assessment | para 7.279, p.269 — horizontal display advertising SLC conclusion |

---

## US Cases

### us_jetblue_spirit_2024 — passages verified 2026-05-30

All three passages replaced with verbatim text from the D. Mass. court opinion
(Document 461 Filed 01/16/24, 113 pages). Corrections:

| Passage | Old (wrong) | Correct |
|---------|-------------|---------|
| sp_1 | p.22 — fleet size discussion | p.75 — court's geographic market definition (O&D pairs) |
| sp_2 | p.41 — divestiture slot analysis | p.83 — court's finding on Spirit as disruptive competitor |
| sp_3 | p.58 — expert credentials section | p.109 — court's finding that ULCC entry insufficient |

Note: The court opinion uses court-filing page numbers (embedded in document header as
"Page X of 113"). Internal printed numbers (shown at bottom of pages) are offset by ~3.
The `page` field uses the court-filing header page number as it is the standard citation form.
