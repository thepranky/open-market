# Data Quality Notes

## EU Cases

### eu_illumina_grail_2022 — source document mismatch

**Issue:** The PDF URL in `eu_illumina_grail_2022.yaml` currently points to a 2024 document
(`M_10188_10279986_7167_3.pdf`), which corresponds to the General Court's 2024 annulment
proceedings, **not** the original September 2022 Commission prohibition decision.

**Impact:** Any source-first extraction or eval benchmarking run against this case will read
the wrong document. The 2024 document does not contain the market definitions, theories of
harm, or remedies analysis from the original prohibition decision.

**TODO:** Exclude `eu_illumina_grail_2022` from extraction/eval benchmarking until either:
- The correct PDF for the 2022 Commission prohibition decision (M.10188) is located and
  the `pdf_url` is updated, or
- The case is removed from the seed dataset.

The Commission case registry page is:
`https://competition-cases.ec.europa.eu/cases/M.10188`
