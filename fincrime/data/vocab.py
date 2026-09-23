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

PENDING_REASONS = ["", "Pending EDD", "Pending Skopenow", "RFI Sent", "Pending Resubmission", "Pending QC", "Pending L2"]

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
CASE_OUTCOMES = ["Approve - False Positive", "Escalate - Potential Match", "Escalate - True Positive", "Reject - True Positive"]
CASE_OUTCOME_RATIONALES = ["All alerts resolved as false positive", "Unresolved potential match", "Confirmed true positive", "Other"]
SCREENING_PLATFORMS = ["In-house CMS", "Internal_blacklist"]

# ── World-Check (simulated) ──────────────────────────────────────────────────
WC_STATUSES = ["True positive", "Potential match", "False positive", "Unspecified"]
WC_RISKS = ["High", "Medium", "Low"]
WC_REASONS = [
    "Date of Birth mismatch", "Nationality mismatch", "Gender mismatch", "Name mismatch", "Age mismatch",
    "Identification mismatch", "Location mismatch", "Confirmed by identification", "Confirmed by adverse media",
    "Insufficient information",
]
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
