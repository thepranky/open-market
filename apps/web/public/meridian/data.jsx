// data.jsx — mock dataset for Meridian (competition / market-definition research)

const JURIS = {
  EU: { code: 'EU', label: 'European Union', authority: 'European Commission', short: 'EC' },
  UK: { code: 'UK', label: 'United Kingdom', authority: 'Competition & Markets Authority', short: 'CMA' },
  US: { code: 'US', label: 'United States', authority: 'DOJ / FTC', short: 'DOJ/FTC' },
};

// outcome -> tone mapping handled in ui.jsx
const OUTCOMES = {
  cleared: 'Cleared',
  conditions: 'Cleared with conditions',
  blocked: 'Blocked',
  abandoned: 'Abandoned',
};

// definition status -> tone mapping handled in ui.jsx
const DEFN = {
  defined: 'Defined',
  left_open: 'Left open',
  segmented: 'Segmented',
  discussed: 'Discussed',
};

const STATS = {
  cases: 1284,
  markets: 3961,
  jurisdictions: 3,
  theories: 412,
  sourceReviewed: 263,
};

// ---- Source-reviewed (rich) cases ----------------------------------------
const CASES = [
  {
    id: 'eu_broadcom_vmware_2023',
    tier: 'source',
    name: 'Broadcom / VMware',
    juris: 'EU', date: '11 Jul 2023', year: 2023,
    sector: 'Technology', sectorKey: 'tech',
    stage: 'Phase 2', caseType: 'Merger', caseNo: 'M.10806',
    outcome: 'conditions',
    parties: [
      { name: 'Broadcom Inc.', role: 'acquirer' },
      { name: 'VMware, Inc.', role: 'target' },
    ],
    theories: [
      { label: 'Mixed bundling — FC/SAN HBAs with virtualization software', type: 'conglomerate' },
      { label: 'Technical interoperability degradation', type: 'foreclosure' },
    ],
    markets: [
      { name: 'IT Asset Management & Software Asset Management (ITAM & SAM)', status: 'left_open',
        defn: 'The Commission left the exact product market definition for ITOM software open but carried out its assessment on the narrowest plausible market — ITAM & SAM — based on Gartner segmentation.',
        sources: [{ p: 24, para: 112 }, { p: 24, para: 118 }] },
      { name: 'System infrastructure software', status: 'left_open',
        defn: 'Exact market definition left open; assessment conducted on the narrowest plausible market including ITACM and DSAC based on IDC segmentation.',
        sources: [{ p: 31, para: 140 }] },
      { name: 'Server virtualization software', status: 'defined',
        defn: 'A distinct product market for server virtualization software, separate from container and bare-metal solutions, was established consistent with prior precedent.',
        sources: [{ p: 38, para: 171 }, { p: 39, para: 176 }] },
      { name: 'Fibre Channel Host-Bus Adapters (FC HBAs)', status: 'defined',
        defn: 'Distinct market for FC HBAs, separate from Ethernet NICs, on the basis of demand- and supply-side substitution evidence.',
        sources: [{ p: 52, para: 233 }] },
    ],
    aiSummary: 'The Commission cleared the acquisition subject to interoperability commitments. Most software markets were left open and assessed on the narrowest plausible basis; the central concern was conglomerate foreclosure between Broadcom hardware and VMware virtualization software.',
    sourceDocs: [
      { label: 'Broadcom / VMware — Decision', kind: 'pdf', meta: '214 pp · EN' },
      { label: 'Case page (europa.eu)', kind: 'link', meta: 'competition-cases' },
    ],
    history: [
      { date: '22 May 2023', label: 'Phase 2 opened' },
      { date: '11 Jul 2023', label: 'Cleared with conditions' },
    ],
    related: ['eu_nvidia_arm_2022', 'eu_microsoft_activision_2023'],
  },
  {
    id: 'eu_apple_shazam_2018',
    tier: 'source',
    name: 'Apple / Shazam',
    juris: 'EU', date: '5 Sep 2018', year: 2018,
    sector: 'Digital', sectorKey: 'digital',
    stage: 'Phase 2', caseType: 'Merger', caseNo: 'M.8788',
    outcome: 'cleared',
    parties: [
      { name: 'Apple Inc.', role: 'acquirer' },
      { name: 'Shazam Entertainment', role: 'target' },
    ],
    theories: [
      { label: 'Data advantage — music-taste data for streaming', type: 'data' },
      { label: 'Input foreclosure — removal of referral traffic to rivals', type: 'foreclosure' },
    ],
    markets: [
      { name: 'Software solutions / app platforms', status: 'segmented',
        defn: 'Segmented by device type: PCs, smart mobile devices, smart TVs, smart watches / wearables. Exact boundaries left open.',
        sources: [{ p: 12, para: 41 }] },
      { name: 'Digital music streaming apps', status: 'defined',
        defn: 'A market for digital music streaming apps for smart mobile devices, excluding video streaming, was established.',
        sources: [{ p: 18, para: 73 }, { p: 19, para: 78 }] },
      { name: 'Automatic Content Recognition (ACR) software', status: 'discussed',
        defn: 'Dedicated stand-alone music recognition apps discussed; broader ACR markets for PCs, mobile and wearables considered but not delineated.',
        sources: [{ p: 22, para: 95 }] },
    ],
    aiSummary: 'Unconditional clearance. The Commission examined whether access to Shazam data could foreclose competing music-streaming services and found no significant impediment to effective competition.',
    sourceDocs: [
      { label: 'Apple / Shazam — Decision', kind: 'pdf', meta: '93 pp · EN' },
      { label: 'Case page (europa.eu)', kind: 'link', meta: 'competition-cases' },
    ],
    history: [
      { date: '23 Apr 2018', label: 'Phase 2 opened' },
      { date: '5 Sep 2018', label: 'Cleared (unconditional)' },
    ],
    related: ['eu_booking_etraveli_2023', 'us_ticketmaster_2010'],
  },
  {
    id: 'eu_bayer_monsanto_2018',
    tier: 'source',
    name: 'Bayer / Monsanto',
    juris: 'EU', date: '20 Mar 2018', year: 2018,
    sector: 'Agriculture', sectorKey: 'agri',
    stage: 'Phase 2', caseType: 'Merger', caseNo: 'M.8084',
    outcome: 'conditions',
    parties: [
      { name: 'Bayer AG', role: 'acquirer' },
      { name: 'Monsanto Company', role: 'target' },
    ],
    theories: [
      { label: 'Horizontal unilateral effects in vegetable seeds', type: 'horizontal' },
      { label: 'Elimination of close innovation competitors', type: 'innovation' },
    ],
    markets: [
      { name: 'Licensing & commercialisation of vegetable seeds (per crop)', status: 'defined',
        defn: 'Distinct markets per crop for the licensing and commercialisation of vegetable seeds, following the Commission’s consistent seed-sector practice.',
        sources: [{ p: 61, para: 290 }] },
      { name: 'Vegetable seeds', status: 'defined',
        defn: 'Separate product markets for individual vegetable-seed crops were defined.',
        sources: [{ p: 64, para: 305 }] },
      { name: 'Microbial crop-efficiency products (biostimulants / biofertilisers)', status: 'discussed',
        defn: 'Emerging markets discussed; the Commission considered competitive dynamics without delineating precise boundaries.',
        sources: [{ p: 88, para: 410 }] },
    ],
    aiSummary: 'Cleared subject to a EUR 6bn divestiture package addressing horizontal overlaps in seeds and traits and innovation-competition concerns in digital agriculture.',
    sourceDocs: [
      { label: 'Bayer / Monsanto — Decision', kind: 'pdf', meta: '658 pp · EN' },
      { label: 'Case page (europa.eu)', kind: 'link', meta: 'competition-cases' },
    ],
    history: [
      { date: '22 Aug 2017', label: 'Phase 2 opened' },
      { date: '20 Mar 2018', label: 'Cleared with conditions' },
    ],
    related: ['eu_dow_dupont_2017'],
  },
  {
    id: 'eu_booking_etraveli_2023',
    tier: 'source',
    name: 'Booking Holdings / eTraveli Group',
    juris: 'EU', date: '24 Sep 2023', year: 2023,
    sector: 'Digital', sectorKey: 'digital',
    stage: 'Phase 2', caseType: 'Merger', caseNo: 'M.10615',
    outcome: 'blocked',
    parties: [
      { name: 'Booking Holdings Inc.', role: 'acquirer' },
      { name: 'eTraveli Group AB', role: 'target' },
    ],
    theories: [
      { label: 'Conglomerate / envelopment — cross-selling flights to hotel OTA', type: 'conglomerate' },
      { label: 'Strengthening of dominant position in hotel OTA', type: 'dominance' },
    ],
    markets: [
      { name: 'Hotel OTA services', status: 'defined',
        defn: 'A distinct EEA-wide market for the supply of hotel online travel agency services was established.',
        sources: [{ p: 28, para: 121 }] },
      { name: 'Flight OTA services', status: 'defined',
        defn: 'A separate market for flight OTA services was defined, distinct from hotel OTA services.',
        sources: [{ p: 33, para: 149 }] },
      { name: 'Private / other accommodation OTA services', status: 'left_open',
        defn: 'Exact boundaries between hotel and alternative-accommodation OTA left open.',
        sources: [{ p: 41, para: 188 }] },
    ],
    aiSummary: 'Prohibited. The Commission found the transaction would strengthen Booking’s dominant position in hotel OTA by expanding its customer-acquisition ecosystem; remedies offered were deemed insufficient.',
    sourceDocs: [
      { label: 'Booking / eTraveli — Decision', kind: 'pdf', meta: '301 pp · EN' },
      { label: 'Case page (europa.eu)', kind: 'link', meta: 'competition-cases' },
    ],
    history: [
      { date: '8 Nov 2022', label: 'Phase 2 opened' },
      { date: '24 Sep 2023', label: 'Prohibited' },
    ],
    related: ['eu_apple_shazam_2018'],
  },
  {
    id: 'uk_microsoft_activision_2023',
    tier: 'source',
    name: 'Microsoft / Activision Blizzard',
    juris: 'UK', date: '13 Oct 2023', year: 2023,
    sector: 'Digital', sectorKey: 'digital',
    stage: 'Phase 2', caseType: 'Merger', caseNo: 'ME/6980/22',
    outcome: 'conditions',
    parties: [
      { name: 'Microsoft Corporation', role: 'acquirer' },
      { name: 'Activision Blizzard, Inc.', role: 'target' },
    ],
    theories: [
      { label: 'Input foreclosure — withholding content from cloud rivals', type: 'foreclosure' },
      { label: 'Conglomerate effects across console & cloud gaming', type: 'conglomerate' },
    ],
    markets: [
      { name: 'Cloud gaming services', status: 'defined',
        defn: 'A nascent but distinct market for cloud gaming services was established as the focal point of the theory of harm.',
        sources: [{ p: 44, para: 6.21 }] },
      { name: 'Console gaming', status: 'discussed',
        defn: 'Console gaming discussed; the CMA narrowed its concerns to cloud after the initial decision.',
        sources: [{ p: 51, para: 7.3 }] },
      { name: 'PC operating systems', status: 'left_open',
        defn: 'Relevance to cloud streaming clients considered; precise boundaries left open.',
        sources: [{ p: 58, para: 8.1 }] },
    ],
    aiSummary: 'Cleared on re-notification after a restructured deal divesting cloud-streaming rights to Ubisoft. The CMA’s remedy targeted the cloud gaming market specifically.',
    sourceDocs: [
      { label: 'Microsoft / Activision — Final Report', kind: 'pdf', meta: '418 pp · EN' },
      { label: 'Case page (gov.uk)', kind: 'link', meta: 'cma-cases' },
    ],
    history: [
      { date: '1 Sep 2022', label: 'Phase 2 referred' },
      { date: '26 Apr 2023', label: 'Prohibited (original deal)' },
      { date: '13 Oct 2023', label: 'Cleared (restructured)' },
    ],
    related: ['eu_broadcom_vmware_2023'],
  },
  {
    id: 'us_illumina_grail_2022',
    tier: 'source',
    name: 'Illumina / GRAIL',
    juris: 'US', date: '31 Mar 2023', year: 2023,
    sector: 'Pharma & life sciences', sectorKey: 'pharma',
    stage: 'Adjudicated', caseType: 'Merger', caseNo: 'FTC D-9401',
    outcome: 'blocked',
    parties: [
      { name: 'Illumina, Inc.', role: 'acquirer' },
      { name: 'GRAIL, Inc.', role: 'target' },
    ],
    theories: [
      { label: 'Vertical input foreclosure — NGS sequencing to MCED developers', type: 'foreclosure' },
    ],
    markets: [
      { name: 'Next-generation DNA sequencing (NGS) platforms', status: 'defined',
        defn: 'A relevant market for NGS platforms used by multi-cancer early detection (MCED) developers was defined as the upstream input.',
        sources: [{ p: 17, para: 44 }] },
      { name: 'Multi-cancer early detection (MCED) tests', status: 'defined',
        defn: 'A developing US market for MCED tests was defined as the downstream market subject to foreclosure.',
        sources: [{ p: 22, para: 61 }] },
    ],
    aiSummary: 'The FTC ordered divestiture, finding the vertical merger would likely diminish innovation competition in the nascent MCED market by giving Illumina ability and incentive to foreclose rivals.',
    sourceDocs: [
      { label: 'Opinion of the Commission', kind: 'pdf', meta: '57 pp · EN' },
      { label: 'Case page (ftc.gov)', kind: 'link', meta: 'ftc-cases' },
    ],
    history: [
      { date: '30 Mar 2021', label: 'Administrative complaint' },
      { date: '31 Mar 2023', label: 'Divestiture ordered' },
    ],
    related: [],
  },
];

// ---- Indexed (metadata-only) cases ---------------------------------------
const INDEXED = [
  { id: 'eu_nvidia_arm_2022', name: 'NVIDIA / Arm', juris: 'EU', date: '2022', sector: 'Technology', outcome: 'abandoned', marketCount: 11 },
  { id: 'eu_dow_dupont_2017', name: 'Dow / DuPont', juris: 'EU', date: '2017', sector: 'Agriculture', outcome: 'conditions', marketCount: 64 },
  { id: 'us_ticketmaster_2010', name: 'Live Nation / Ticketmaster', juris: 'US', date: '2010', sector: 'Digital', outcome: 'conditions', marketCount: 6 },
  { id: 'uk_sainsbury_asda_2019', name: 'Sainsbury’s / Asda', juris: 'UK', date: '2019', sector: 'Retail', outcome: 'blocked', marketCount: 537 },
  { id: 'eu_google_fitbit_2020', name: 'Google / Fitbit', juris: 'EU', date: '2020', sector: 'Digital', outcome: 'conditions', marketCount: 9 },
  { id: 'us_att_timewarner_2018', name: 'AT&T / Time Warner', juris: 'US', date: '2018', sector: 'Media & telecoms', outcome: 'cleared', marketCount: 4 },
  { id: 'eu_siemens_alstom_2019', name: 'Siemens / Alstom', juris: 'EU', date: '2019', sector: 'Industrials', outcome: 'blocked', marketCount: 12 },
  { id: 'uk_meta_giphy_2021', name: 'Meta / Giphy', juris: 'UK', date: '2021', sector: 'Digital', outcome: 'blocked', marketCount: 3 },
  { id: 'eu_lufthansa_ita_2024', name: 'Lufthansa / ITA Airways', juris: 'EU', date: '2024', sector: 'Transport', outcome: 'conditions', marketCount: 27 },
  { id: 'us_jetblue_spirit_2024', name: 'JetBlue / Spirit', juris: 'US', date: '2024', sector: 'Transport', outcome: 'blocked', marketCount: 18 },
];

const ALL_INDEXED_BY_ID = {};
INDEXED.forEach((c) => { ALL_INDEXED_BY_ID[c.id] = c; });
const CASE_BY_ID = {};
CASES.forEach((c) => { CASE_BY_ID[c.id] = c; });

// ---- Graph data: sectors -> markets -> cases -----------------------------
const SECTORS = [
  { key: 'digital', label: 'Digital', markets: 14, cases: 38 },
  { key: 'tech', label: 'Technology', markets: 22, cases: 41 },
  { key: 'agri', label: 'Agriculture', markets: 31, cases: 12 },
  { key: 'pharma', label: 'Pharma & life sciences', markets: 47, cases: 29 },
  { key: 'telecoms', label: 'Media & telecoms', markets: 19, cases: 33 },
  { key: 'energy', label: 'Energy', markets: 16, cases: 14 },
  { key: 'transport', label: 'Transport', markets: 12, cases: 22 },
  { key: 'retail', label: 'Retail & consumer', markets: 28, cases: 19 },
];

// markets within "digital" sector for the drill demo
const MARKETS = {
  digital: [
    { id: 'm_music_streaming', name: 'Digital music streaming', status: 'defined', cases: 4 },
    { id: 'm_acr', name: 'ACR software solutions', status: 'segmented', cases: 2 },
    { id: 'm_cloud_gaming', name: 'Cloud gaming services', status: 'defined', cases: 3 },
    { id: 'm_console', name: 'Console gaming', status: 'discussed', cases: 5 },
    { id: 'm_display_ads', name: 'Display advertising', status: 'defined', cases: 6 },
    { id: 'm_online_ads_gen', name: 'Online advertising (general)', status: 'left_open', cases: 7 },
    { id: 'm_online_ads_inc', name: 'Online advertising (incl. search)', status: 'left_open', cases: 4 },
    { id: 'm_social', name: 'Social media', status: 'defined', cases: 5 },
    { id: 'm_gif', name: 'GIF libraries', status: 'defined', cases: 1 },
    { id: 'm_hotel_ota', name: 'Hotel OTA services', status: 'defined', cases: 3 },
    { id: 'm_flight_ota', name: 'Flight OTA services', status: 'defined', cases: 2 },
    { id: 'm_wearable_os', name: 'Wearable OS / platforms', status: 'discussed', cases: 2 },
    { id: 'm_wrist_wearable', name: 'Wrist-worn wearables', status: 'defined', cases: 3 },
    { id: 'm_music_data', name: 'Licensing of music data', status: 'left_open', cases: 1 },
  ],
};

// cases hanging off a market (for the third drill level)
const MARKET_CASES = {
  m_music_streaming: ['eu_apple_shazam_2018', 'eu_google_fitbit_2020'],
  m_acr: ['eu_apple_shazam_2018'],
  m_cloud_gaming: ['uk_microsoft_activision_2023'],
  m_console: ['uk_microsoft_activision_2023'],
  m_hotel_ota: ['eu_booking_etraveli_2023'],
  m_flight_ota: ['eu_booking_etraveli_2023'],
  m_social: ['uk_meta_giphy_2021'],
  m_gif: ['uk_meta_giphy_2021'],
};

window.MERIDIAN_DATA = {
  JURIS, OUTCOMES, DEFN, STATS,
  CASES, INDEXED, SECTORS, MARKETS, MARKET_CASES,
  CASE_BY_ID, ALL_INDEXED_BY_ID,
};
