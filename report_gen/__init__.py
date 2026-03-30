"""report_gen package - split from report_generator.py

All public and private symbols are re-exported here so that
``from report_gen import X`` works for any function previously
defined in the monolithic ``report_generator.py``.
"""

# --- source_parser (leaf) ---
from report_gen.source_parser import (
    _read_text_limited,
    _strip_c_comments,
    _extract_c_prototypes,
    _extract_c_definitions,
    _extract_c_function_bodies,
    _extract_c_macros,
    _extract_c_macro_defs,
    _extract_c_global_candidates,
    _extract_comment_lines,
    _scan_source_comment_patterns,
    _scan_source_requirement_ids,
    _scan_source_function_names,
)

# --- uds_text (leaf) ---
from report_gen.uds_text import (
    _title_case_line,
    _split_sentences,
    _trim_sentence_words,
    _apply_sentence_rules,
    _apply_uds_rules,
    _ai_section_text,
    _ai_evidence_lines,
    _ai_quality_warnings,
    _merge_section_text,
    _merge_logic_ai_items,
    _ai_document_text,
    _uds_lines_to_html,
    _uds_logic_html,
)

# --- utils ---
from report_gen.utils import (
    _safe_dict,
    _safe_list,
    _fmt_bool,
    _extract_issue_counts,
    generate_markdown_summary,
    generate_pdf_report,
    _extract_simple_call_names,
    _table_rows_from_texts,
    _build_global_rows,
    _normalize_swufn_id,
    _normalize_call_field,
    _dedupe_multiline_text,
    _normalize_asil_value,
    _normalize_related_ids,
    _extract_call_names,
    _normalize_swcom_label,
    _infer_type_from_decl,
    _infer_type_from_file,
)

# --- function_analyzer ---
from report_gen.function_analyzer import (
    _split_signature_param_chunks,
    _extract_param_symbol,
    _parse_signature_params,
    _strip_comments_and_strings,
    _safe_eval_int,
    _normalize_bracket_expr,
    _split_param,
    _collect_var_usage,
    _extract_primary_condition,
    _extract_condition_branch_calls,
    _extract_logic_terminal_paths,
    _extract_logic_flow,
    _format_param_entry,
    _extract_return_type,
    _classify_param_direction,
    _parse_signature_outputs,
    _fallback_function_description,
    _is_exact_generic,
    _is_generic_description,
    _classify_description_quality,
    _split_func_name_words,
    _enhance_function_description,
    _enhance_description_text,
    _normalize_symbol_name,
    _finalize_function_fields,
    _is_static_var,
    _infer_precondition_from_body,
    _build_function_info_rows,
)

# --- requirements ---
from report_gen.requirements import (
    _extract_requirements_from_comments,
    _extract_table_section,
    _normalize_table_row,
    _extract_function_blocks,
    _docx_to_text,
    _extract_function_info_from_docx,
    _extract_sds_partition_map,
    _load_component_map,
    _build_req_map_from_texts,
    _build_req_map_from_doc_paths,
    enrich_function_details_with_docs,
    _split_doc_function_blocks,
    _collect_section_lines,
    _extract_state_tokens,
    _extract_requirements_from_doc,
    _extract_requirements_fallback,
    _extract_doc_section,
    _extract_requirement_blocks,
    generate_uds_requirements_preview,
    generate_uds_requirements_mapping,
    _extract_doc_function_names,
    generate_uds_function_mapping,
    _normalize_trace_mapping_entry,
    _parse_traceability_json,
    _parse_traceability_csv,
    _parse_traceability_text,
    generate_uds_traceability_mapping,
    _normalize_vcast_rows,
    generate_uds_traceability_matrix,
    generate_uds_requirements_compare,
    generate_uds_requirements_from_docs,
)

# --- uds_generator ---
from report_gen.uds_generator import (
    generate_uds_logic_items,
    _group_function_blocks_by_swcom,
    _format_function_block_lines,
    parse_uds_preview_html,
    generate_uds_source_sections,
    generate_uds_preview_markdown,
    generate_uds_preview_html,
)

# --- docx_builder ---
from report_gen.docx_builder import (
    _add_docx_text_block,
    _replace_docx_text,
    _add_docx_bullets,
    _add_docx_lines,
    _add_docx_toc,
    _render_logic_flow_diagram,
    _render_logic_text_image,
    _render_call_graph_image,
    _render_unit_structure_image,
    _render_swcom_overview_image,
    _merge_function_info_table,
    _normalize_function_info_tables,
    _fill_function_info_table,
    _insert_logic_image_in_table,
    _clear_docx_body,
    _remove_docx_paragraphs,
    _template_has_placeholders,
    _iter_template_blocks,
    _extract_template_blocks,
    _extract_template_section_map,
    _add_blank_table,
    generate_uds_docx,
)

# --- validation ---
from report_gen.validation import (
    validate_uds_docx_structure,
    generate_uds_validation_report,
    generate_called_calling_accuracy_report,
    generate_swcom_context_report,
    generate_swcom_context_diff_report,
    generate_uds_field_quality_gate_report,
    generate_uds_delta_report,
    _split_csvish,
    _clean_param_lines,
    _parse_accuracy_summary,
    _parse_quality_gate_summary,
    build_uds_view_payload,
    generate_uds_constraints_report,
    generate_asil_related_confidence_report,
)

__all__ = [
    # Public functions
    "generate_markdown_summary",
    "generate_pdf_report",
    "generate_uds_logic_items",
    "parse_uds_preview_html",
    "generate_uds_source_sections",
    "generate_uds_preview_markdown",
    "generate_uds_preview_html",
    "generate_uds_docx",
    "generate_uds_requirements_preview",
    "generate_uds_requirements_mapping",
    "generate_uds_function_mapping",
    "generate_uds_traceability_mapping",
    "generate_uds_traceability_matrix",
    "generate_uds_requirements_compare",
    "generate_uds_requirements_from_docs",
    "validate_uds_docx_structure",
    "generate_uds_validation_report",
    "generate_called_calling_accuracy_report",
    "generate_swcom_context_report",
    "generate_swcom_context_diff_report",
    "generate_uds_field_quality_gate_report",
    "generate_uds_delta_report",
    "build_uds_view_payload",
    "generate_uds_constraints_report",
    "generate_asil_related_confidence_report",
]
