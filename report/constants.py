# report/constants.py
"""Report generator constants extracted from report_generator.py."""

UDS_RULES = {
    "section_order": ["Overview", "Requirements", "Interfaces", "UDSFrames", "Notes"],
    "formatting": {
        "title_case": True,
        "bullet_prefix": "- ",
        "max_bullets_default": 8,
        "max_sentences": 2,
        "max_words_per_sentence": 24,
        "max_chars": 180,
        "max_line_chars": 240,
        "ensure_period": True,
    },
    "sections": {
        "overview": {"max_bullets": 6, "max_sentences": 2, "max_chars": 180},
        "requirements": {"max_bullets": 10, "max_sentences": 2, "max_chars": 200},
        "interfaces": {"max_bullets": 10, "max_sentences": 2, "max_chars": 200},
        "uds_frames": {"max_bullets": 12, "max_sentences": 2, "max_chars": 200},
        "notes": {"max_bullets": 8, "max_sentences": 2, "max_chars": 180},
    },
}


UDS_PLACEHOLDERS = [
    "{{project_name}}",
    "{{job_url}}",
    "{{build_number}}",
    "{{generated_at}}",
    "{{overview}}",
    "{{requirements}}",
    "{{interfaces}}",
    "{{uds_frames}}",
    "{{notes}}",
]


UDS_SERVICE_TABLE = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x24: "ReadScalingDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2A: "ReadDataByPeriodicIdentifier",
    0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3D: "WriteMemoryByAddress",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
}

UDS_DID_PATTERNS = [
    r"\bg_UDS_\w+",
    r"\bs_UDS_\w+",
    r"\bDID_\w+",
    r"\bDID\s*=\s*0x[0-9A-Fa-f]+",
    r"\b0x(?:F[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4})\b",
    r"\bReadDataByIdentifier\b",
    r"\bWriteDataByIdentifier\b",
]

UDS_SERVICE_ID_PATTERNS = [
    r"\b0x(?:10|11|14|19|22|23|24|27|28|2[ACE]|2F|3[1-7D]|3E|85)\b",
    r"\bSID_\w+",
    r"\bUDS_SID_\w+",
    r"\bDIAG_\w+(?:REQ|RSP|SERVICE)\w*",
]

GLOBALS_FORMAT_ORDER = ["Name", "Type", "File", "Range"]
GLOBALS_FORMAT_SEP = " | "
GLOBALS_FORMAT_WITH_LABELS = True
LOGIC_MAX_DEPTH_DEFAULT = 3
LOGIC_MAX_CHILDREN_DEFAULT = 3
LOGIC_MAX_GRANDCHILDREN_DEFAULT = 2
DEFAULT_TYPE_RANGES = {
    "U8": "0 ~ 255",
    "U16": "0 ~ 65535",
    "U32": "0 ~ 4294967295",
    "S8": "-128 ~ 127",
    "S16": "-32768 ~ 32767",
    "S32": "-2147483648 ~ 2147483647",
}
