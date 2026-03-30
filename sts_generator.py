"""Backward-compatible shim - implementations moved to generators.sts"""
from generators.sts import (  # noqa: F401
    parse_srs_docx_tables,
    parse_requirements_structured,
    map_requirements_to_functions,
    generate_test_cases,
    generate_traceability_matrix,
    generate_quality_report,
    generate_sts_xlsm,
    enhance_test_cases_with_ai,
    generate_sts,
    validate_sts_output,
    generate_sts_validation_report,
)
