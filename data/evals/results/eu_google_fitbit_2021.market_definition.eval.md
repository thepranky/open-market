# Extraction Evaluation — eu_google_fitbit_2021

Generated: 2026-05-30T00:17:21.333616+00:00

## Summary
- Gold partial: True
- Reviewed markets: 13
- **Gating decision: AUTO_ACCEPT**
- Overall F1: 0.889
- *(Partial gold: precision/recall cover reviewed scope only)*

## Product Markets
- TP: 7, FP: 0, FN: 4
- Unjudged: 17, Out-of-scope: 0
- Partial Precision: 1.0, Partial Recall: 0.636, Partial F1: 0.778

### Matched
  - ✓ `Wrist-worn wearable devices` → `Wrist-worn wearable devices` (exact)
  - ✓ `Supply of licensable OSs for wrist-worn wearable devices` → `Supply of licensable OSs for wrist-worn wearable devices` (exact)
  - ✓ `Online search advertising services` → `Online search advertising services` (exact)
  - ✓ `Supply of search ad network services` → `Supply of search ad network services` (exact)
  - ✓ `Supply of display ads SSP services` → `Supply of display ads SSP services` (exact)
  - ✓ `Supply of display ads advertiser ad server services` → `Supply of advertiser ad server services` (expected_draft_name)
  - ✓ `Supply of analytics services` → `Data analytics services (for online search and display advertising)` (expected_draft_name)

### False Negatives (gold not found in draft)
  - ✗ `Online display advertising services`
    aliases: ['Online non-search advertising', 'Display advertising services']
    nearest draft candidates:
      - `Online search advertising services` (overlap=0.5, id=pm_7)
      - `Data analytics services (for online search and display advertising)` (overlap=0.5, id=pm_12)
      - `Online advertising intermediation services (search and non-search)` (overlap=0.333, id=pm_8)
      - `Online advertising intermediation services (including sub-segments: online search advertising intermediation, display ad network services, display ads publisher ad server services, display ads advertiser ad server services, analytics services)` (overlap=0.214, id=pm_14)
      - `Supply of display ads SSP services` (overlap=0.2, id=pm_10)
  - ✗ `Supply of display ads DSP services`
    aliases: ['Display ads DSP services', 'DSP services']
    nearest draft candidates:
      - `Supply of display ads SSP services` (overlap=0.5, id=pm_10)
      - `Online advertising intermediation services (including sub-segments: online search advertising intermediation, display ad network services, display ads publisher ad server services, display ads advertiser ad server services, analytics services)` (overlap=0.133, id=pm_14)
      - `Data analytics services (for online search and display advertising)` (overlap=0.125, id=pm_12)
  - ✗ `Supply of display ad network services`
    aliases: ['Display ad network services']
    nearest draft candidates:
      - `Supply of search ad network services` (overlap=0.333, id=pm_9)
      - `Supply of display ads SSP services` (overlap=0.25, id=pm_10)
      - `Data analytics services (for online search and display advertising)` (overlap=0.143, id=pm_12)
      - `Online advertising intermediation services (including sub-segments: online search advertising intermediation, display ad network services, display ads publisher ad server services, display ads advertiser ad server services, analytics services)` (overlap=0.143, id=pm_14)
  - ✗ `Supply of display ads publisher ad server services`
    aliases: ['Publisher ad server services']
    nearest draft candidates:
      - `Supply of display ads SSP services` (overlap=0.4, id=pm_10)
      - `Online advertising intermediation services (including sub-segments: online search advertising intermediation, display ad network services, display ads publisher ad server services, display ads advertiser ad server services, analytics services)` (overlap=0.286, id=pm_14)
      - `Supply of advertiser ad server services` (overlap=0.2, id=pm_11)
      - `Data analytics services (for online search and display advertising)` (overlap=0.111, id=pm_12)

### Unjudged (17 draft markets outside reviewed scope)
  - `App stores for a given OS platform of smart mobile devices (in particular Android app stores)`
  - `App stores for a given OS platform of wrist-worn wearable devices (in particular app stores for Wear OS and Fitbit devices)`
  - `General search services`
  - `App stores for wrist-worn wearable devices (Wear OS and Fitbit app stores)`
  - `Online advertising intermediation services (search and non-search)`
  - `Health and fitness apps`
  - `Online advertising intermediation services (including sub-segments: online search advertising intermediation, display ad network services, display ads publisher ad server services, display ads advertiser ad server services, analytics services)`
  - `Mobile payment services (including proximity/offline and remote/online segments)`
  - `Retail provision of mobile payment services`
  - `Navigation apps offering turn-by-turn navigation`
  - `Virtual assistants`
  - `Digital music distribution services`
  - `Digital translation services`
  - `Provision of cloud infrastructure and data analytics`
  - `Patient monitoring`
  - `Provision of data for medical research and real-world evidence (RWE)`
  - `Corporate wellness programmes`

## Geographic Markets
- TP: 2, FP: 0, FN: 0
- Unjudged: 17, Out-of-scope: 0
- Partial Precision: 1.0, Partial Recall: 1.0, Partial F1: 1.0

### Matched
  - ✓ `Wrist-worn wearable devices geographic market` → `Wrist-worn wearable devices — geographic market` (expected_draft_name)
  - ✓ `Online advertising services geographic market` → `Online advertising services (search and display) — national geographic market` (expected_draft_name)

### Unjudged (17 draft markets outside reviewed scope)
  - `Licensable OSs for smart mobile devices — worldwide excluding China`
  - `Licensable OSs for wrist-worn wearable devices — at least EEA-wide, potentially worldwide excluding China`
  - `Geographic market for app stores for a given OS platform of smart mobile devices (worldwide excluding China)`
  - `Worldwide excluding China — app stores for smart mobile devices and wrist-worn wearable devices`
  - `General search services — national geographic market`
  - `Online advertising intermediation services (ad tech) — EEA-wide`
  - `Health and fitness apps — geographic scope`
  - `Geographic market for health and fitness apps`
  - `Retail provision of mobile payment services – geographic scope`
  - `Navigation apps – geographic scope`
  - `Virtual assistants – geographic scope`
  - `Digital music distribution services – geographic scope`
  - `Digital translation services — geographic market`
  - `Provision of cloud infrastructure and data analytics — geographic market`
  - `Patient monitoring — geographic market`
  - `Provision of data for medical research and RWE — geographic market`
  - `Corporate wellness programmes — geographic market`

## Promotion Safety
- Safe promoted: 0
- Risky promotions: 0
- Promotion safety score: 1.0
- Overpromotion risk: LOW

## Quote Validity
- Checked: 33
- Passed: 33
- Failures: 0
- Warnings (cache unavailable): 0