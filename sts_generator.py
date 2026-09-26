"""Backward-compatible shim - implementations moved to generators.sts"""
from generators.sts import (  # noqa: F401
    enhance_test_cases_with_ai,
    generate_quality_report,
    generate_sts,
    generate_sts_validation_report,
    generate_sts_xlsm,
    generate_test_cases,
    generate_traceability_matrix,
    map_requirements_to_functions,
    parse_requirements_structured,
    parse_srs_docx_tables,
    validate_sts_output,
)
