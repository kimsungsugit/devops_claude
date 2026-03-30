"""Backward-compatible shim - implementations moved to generators.suts"""
from generators.suts import (  # noqa: F401
    collect_unit_functions,
    set_globals_type_cache,
    infer_variable_type,
    get_boundary_values,
    determine_gen_method,
    generate_sequences,
    enhance_sequences_with_ai,
    generate_suts_xlsm,
    generate_suts_quality_report,
    validate_suts_xlsm,
    validate_sts_xlsm,
    generate_suts,
    generate_suts_validation_report,
    validate_suts_output,
)
