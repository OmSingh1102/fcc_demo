"""Every list the UI offers in a dropdown, tab row or badge.

Constants only, so a template, a builder and a validator agree on the exact
strings. The spellings follow the tools being modelled (`DataConfirming`,
`Namescreen hit - WC or CMS`) because the demo is meant to read like them.
"""

# ── KYC case status ──────────────────────────────────────────────────────────
STATUSES = [
    "Submitted", "IDVerification", "DataConfirming", "DataScreening",
    "DataEscalatingL2", "Verified", "Rejected",
    "ResubmitID", "ResubmitPOA",
    # Present in the status filter of the real list; this demo never moves a
    # case into them, they exist so the filter looks complete.
    "POAScreening", "POAReviewingL1", "POAReviewingL2", "POAReviewingL3", "POAResubmit",
]

STATUS_TONE = {
    "Submitted": "slate", "IDVerification": "slate",
    "DataConfirming": "blue", "DataScreening": "blue",
    "DataEscalatingL2": "amber",
    "Verified": "emerald", "Rejected": "rose",
    "ResubmitID": "amber", "ResubmitPOA": "amber",
    "POAScreening": "violet", "POAReviewingL1": "violet", "POAReviewingL2": "violet",
    "POAReviewingL3": "violet", "POAResubmit": "amber",
}

# Which are "open" — in somebody's queue.
OPEN_STATUSES = {"Submitted", "IDVerification", "DataConfirming", "DataScreening", "DataEscalatingL2"}
CLOSED_STATUSES = {"Verified", "Rejected"}

# The six verification points on the case page, in order.
STEP_LABELS = ["Submitted", "ID Verification", "Data Confirming", "Data Screening", "Data Escalating L2", "Completed"]

# Which step a status sits on (0-based). Resubmit statuses sit on Data
# Confirming: the case is waiting for the user, then re-enters there.
STATUS_STEP = {
    "Submitted": 0, "IDVerification": 1, "DataConfirming": 2, "DataScreening": 3,
    "DataEscalatingL2": 4, "Verified": 5, "Rejected": 5,
    "ResubmitID": 2, "ResubmitPOA": 2, "POAResubmit": 2,
    "POAScreening": 3, "POAReviewingL1": 3, "POAReviewingL2": 4, "POAReviewingL3": 4,
}

# Review Decision table rows.
CHECK_POINTS = ["Submitted", "System Review", "Data Matching", "Data Confirming", "Data Screening", "Data Escalating L2"]

PENDING_REASONS = ["", "Pending EDD", "Pending Skopenow", "RFI Sent", "Pending Resubmission", "Pending QC", "Pending L2",
                   "Pending Checker 2"]

MANUAL_REVIEW_REASONS = [
    "Namescreen hit - WC or CMS",
    "POA Collected",
    "Namescreen hit - Sanction country",
    "Vendor rejected",
    "Age verification",
    "Duplicate account",
    "High-risk country",
    "Manual referral",
]

# The resubmit reasons offered to the user, verbatim from the tool's dropdown.
RESUBMIT_ID_REASONS = [
    "This is a non Government Issued ID document e.g work ID or membership ID. We require a gov issued photo ID",
    "This is a foreign document not recognised",
    "This is a bank card, not an ID document",
    "The document you have submitted is expired",
    "The document you have submitted is in digital format",
    "The document you submitted is a scan/photocopy",
    "The document you have provided is a screenshot",
    "Missing photo",
    "Missing Expiry Date",
    "Handwritten details not clear eg signature",
    "Cropped",
    "We require the name written on the front of the ID, not the back",
    "This ID is not in a suitable state",
]

RESUBMIT_POA_REASONS = [
    "The proof of address is older than 6 months",
    "The document type is not an accepted proof of address",
    "The name on the proof of address does not match the ID",
    "The address is not fully visible",
    "The proof of address is a screenshot",
    "The proof of address is from a prohibited country",
]

ESCALATE_REASONS = [
    "Fraud ID / AI-generated document",
    "Sanctioned country ID with same-country POA",
    "Unresolved medium or high risk screening hit",
    "Non-US person with potential match",
    "Inconclusive Skopenow report",
    "Other",
]

SOURCES = ["Live Standard KYC", "Live Agency KYC", "Shop Seller KYB", "Periodic Review"]
TAGS = ["Gifter G6", "Gifter G4", "Creator G3", "Creator G2", "Agency", "Priority Review"]
CASE_REVIEW_LEVELS = ["L1", "L2", "L3"]
QC_RESULTS = ["", "Pass", "Fail"]
ID_TYPES = ["Passport", "DrivingLicense", "NationalID", "ResidencePermit", "TradeLicense"]
VENDORS = ["shufti_pro_ios_webview", "shufti_pro_android_webview", "jumio_ios_webview", "jumio_android_webview"]

TENANTS = {
    "ttlive": {
        "key": "ttlive", "label": "TT Live", "business_line": "TikTok Live",
        "wc_group": "TTLIVE_KYC_name_screening_prod", "event": "Onboarding KYC Live",
        "cms_queue": "Sanction_CMS_Customer_KYC_Onboarding", "source": "Live Standard KYC",
    },
    "ttshop": {
        "key": "ttshop", "label": "TT Shop", "business_line": "TikTok Shop",
        "wc_group": "TTSHOP_KYB_name_screening_prod", "event": "Onboarding KYB Shop",
        "cms_queue": "Sanction_CMS_Seller_KYB_Onboarding", "source": "Shop Seller KYB",
    },
}

# ── Name-screening case ──────────────────────────────────────────────────────
ALERT_OUTCOMES = ["Pending", "False Positive", "Potential Match", "True Positive"]
RESULT_LABELS = ["False Positive", "Potential Match", "True Positive"]
RATIONALES = [
    "Image Mismatch", "DOB Mismatch", "Nationality Mismatch", "Name Mismatch", "Gender Mismatch",
    "Different Person - Public Records", "Confirmed Identity", "Insufficient Information",
    "Transliteration Variant", "Same Person - Adverse Media",
]
RISK_LEVELS = ["Low", "Medium", "High"]
REVIEW_MODES = ["Smart Review", "Manual Review"]
# The actor the automation signs with: the AI screening rules on a match, the
# screening case they close, the KYC case they auto-verify.
SYSTEM_USER = "System User"
# Every KYC case carries one of these once it has been screened (SOP: current
# automation; the client's two workflows, 2026-09-24).
REVIEW_WORKFLOWS = {"auto-verified": "Auto-verified", "human-in-the-loop": "Human-in-the-loop"}
CASE_OUTCOMES = ["Approve - False Positive", "Escalate - Potential Match", "Escalate - True Positive", "Reject - True Positive"]
CASE_OUTCOME_RATIONALES = ["All alerts resolved as false positive", "Unresolved potential match", "Confirmed true positive", "Other"]
SCREENING_PLATFORMS = ["In-house CMS", "Internal_blacklist"]

# ── World-Check (simulated) ──────────────────────────────────────────────────
WC_STATUSES = ["True positive", "Potential match", "False positive", "Unspecified"]
WC_RISKS = ["High", "Medium", "Low"]
# The risk level is not a choice: it follows the outcome, in the watchlist
# console (by status) and on the screening case (by result label) alike.
RISK_FOR_OUTCOME = {"False positive": "Low", "Potential match": "Medium", "True positive": "High", "Unspecified": ""}
RISK_FOR_LABEL = {"False Positive": "Low", "Potential Match": "Medium", "True Positive": "High"}
WC_REASONS = [
    "Date of Birth mismatch", "Nationality mismatch", "Gender mismatch", "Name mismatch", "Age mismatch",
    "Identification mismatch", "Location mismatch", "Confirmed by identification", "Confirmed by adverse media",
    "Insufficient information",
]
# A watchlist resolution as the screening case labels it, and its rationale.
WC_STATUS_LABEL = {"False positive": "False Positive", "Potential match": "Potential Match", "True positive": "True Positive"}
WC_REASON_RATIONALE = {
    "Date of Birth mismatch": "DOB Mismatch", "Nationality mismatch": "Nationality Mismatch",
    "Gender mismatch": "Gender Mismatch", "Name mismatch": "Name Mismatch", "Age mismatch": "DOB Mismatch",
    "Identification mismatch": "Different Person - Public Records", "Location mismatch": "Different Person - Public Records",
    "Confirmed by identification": "Confirmed Identity", "Confirmed by adverse media": "Same Person - Adverse Media",
    "Insufficient information": "Insufficient Information",
}
WC_TYPES = {
    "PEP": "Politically exposed person", "SIC": "Special interest category", "OB": "Other bodies",
    "LE": "Law enforcement", "RE": "Regulatory enforcement", "SAN": "Sanctions", "RCA": "Relative or close associate",
}
WC_CATEGORIES = ["POST CONVICTION", "LEGAL", "SANCTIONS", "REGULATORY", "ADVERSE MEDIA", "PEP"]
WC_PAGE_SIZE = 50

# ── Decisions ────────────────────────────────────────────────────────────────
EDD_DECISIONS = ["False positive", "True positive - Escalate", "Potential match - Escalate", "Request Skopenow report", "Approve after Skopenow"]
L2_DECISIONS = ["Approve", "Reject", "Escalate to EDD"]
RISK_RATINGS = ["Low", "Medium", "High"]

# ── SLA (hours) ──────────────────────────────────────────────────────────────
SLA_HOURS_L1 = 48
SLA_HOURS_EDD = 14 * 24

# ── Tiers (SOP 2.1, 5.2: L1 → L2 → L3) ───────────────────────────────────────
# Decisions are recorded under L1 / L2 / EDD; the case review level shown in
# the header counts L1 / L2 / L3. Both spellings map to the same label.
LEVEL_LABELS = {"L1": "L1 Frontline", "L2": "L2 Escalation", "EDD": "L3 EDD / PIC", "L3": "L3 EDD / PIC", "QC": "QC / Team Lead"}

# ── Operations hub: routing (SOP 5.2.1–5.2.3) ────────────────────────────────
SCRIPTS = ["latin", "cyrillic", "arabic"]
CAPACITY_MAX = 20
ROUTING_TRIGGERS = {
    "handoff": "Immediate hand-off", "on_demand": "Case on-demand", "next": "Get next case",
    "lead_run": "Routing run by the lead", "seed": "Routed at intake",
}

# ── Proof of address (SOP 4.1.2 step 1) ──────────────────────────────────────
# The "internal library" of accepted POA document types. Demo list.
ACCEPTED_POA_TYPES = {"utility_bill": "Utility bill", "bank_statement": "Bank statement",
                      "council_tax": "Council tax / municipal bill", "tenancy_agreement": "Tenancy agreement"}
POA_MAX_AGE_DAYS = 183
# Demo list only — the real hub reads the internal library of sanctioned and
# prohibited jurisdictions. ISO-2 codes, as the seed stores nationalities.
SANCTIONED_OR_PROHIBITED = {"RU": "Russian Federation", "IR": "Iran", "KP": "North Korea", "SY": "Syria",
                            "CU": "Cuba", "BY": "Belarus", "AF": "Afghanistan", "MM": "Myanmar", "VE": "Venezuela"}
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "SG": "Singapore", "RU": "Russian Federation", "CY": "Cyprus",
    "VN": "Vietnam", "MX": "Mexico", "PK": "Pakistan", "BR": "Brazil", "AE": "United Arab Emirates", "DE": "Germany",
    "ES": "Spain", "JO": "Jordan", "CH": "Switzerland", "GH": "Ghana", "JP": "Japan", "IN": "India", "CO": "Colombia",
    "NG": "Nigeria", "IT": "Italy", "IE": "Ireland", "LB": "Lebanon", "AU": "Australia", "FR": "France", "KR": "South Korea",
    "CZ": "Czechia", "EG": "Egypt", "DK": "Denmark", "SE": "Sweden", "PT": "Portugal", "KZ": "Kazakhstan", "MA": "Morocco",
    "MY": "Malaysia", "CA": "Canada", "IR": "Iran", "KP": "North Korea", "SY": "Syria", "CU": "Cuba", "BY": "Belarus",
    "AF": "Afghanistan", "MM": "Myanmar", "VE": "Venezuela",
}
# What the document itself prints, so the analyst reads the birthday in the
# right order before confirming it (SOP 4.1.2: dd/mm vs mm/dd; system stores yyyy-mm-dd).
DATE_FORMAT_NOTES = {
    "Passport": "the passport prints dates as DD MON YYYY",
    "NationalID": "the ID card prints dates as DD MON YYYY",
    "ResidencePermit": "the permit prints dates as DD MON YYYY",
    "DrivingLicense": "the US licence prints dates as MM/DD/YYYY",
    "TradeLicense": "the licence prints dates as DD MON YYYY",
}

# ── Escalation typology (SOP 4.1.3 step 2.1.1: Fraud Typology on the tracker) ─
FRAUD_TYPOLOGIES = [
    "Forged or altered document",
    "AI-generated or synthetic document",
    "Stolen or borrowed identity (impersonation)",
    "Template or specimen document",
    "Sanctions evasion (ID / POA mismatch)",
    "Mule or third-party account",
    "Not applicable (screening escalation)",
]

# ── TT Shop Checker 2 (SOP 4.2: second reviewer on seller approvals) ─────────
CHECKER2_DECISIONS = ["Approve", "Return to Checker 1", "Escalate to L2"]

# ── QC sampling (SOP 2.1: QA / QC / Team Lead) ───────────────────────────────
QC_REASONS = [
    "Decision correct and evidenced",
    "Rationale insufficient",
    "Wrong outcome",
    "World-Check export missing",
    "POA check not evidenced",
    "SLA breached without a note",
    "Data-entry error",
]
QC_SAMPLE_RATE = 0.2
QC_SAMPLE_MIN = 5
