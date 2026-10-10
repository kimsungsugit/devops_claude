"""Backward-compatible shim - implementations moved to generators.suts"""
from generators.suts import (  # noqa: F401
    collect_unit_functions,
    determine_gen_method,
    enhance_sequences_with_ai,
    generate_sequences,
    generate_suts,
    generate_suts_quality_report,
    generate_suts_validation_report,
    generate_suts_xlsm,
    get_boundary_values,
    infer_variable_type,
    set_globals_type_cache,
    validate_sts_xlsm,
    validate_suts_output,
    validate_suts_xlsm,
)
