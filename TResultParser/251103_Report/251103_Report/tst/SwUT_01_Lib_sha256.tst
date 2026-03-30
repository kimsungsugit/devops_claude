-- VectorCAST 25.sp4 (08/19/25)
-- Test Case Script
--
-- Environment    : SWUT_01_LIB_SHA256
-- Unit(s) Under Test: Lib_sha256
--
-- Script Features
TEST.SCRIPT_FEATURE:C_DIRECT_ARRAY_INDEXING
TEST.SCRIPT_FEATURE:CPP_CLASS_OBJECT_REVISION
TEST.SCRIPT_FEATURE:MULTIPLE_UUT_SUPPORT
TEST.SCRIPT_FEATURE:REMOVED_CL_PREFIX
TEST.SCRIPT_FEATURE:MIXED_CASE_NAMES
TEST.SCRIPT_FEATURE:STATIC_HEADER_FUNCS_IN_UUTS
TEST.SCRIPT_FEATURE:VCAST_MAIN_NOT_RENAMED
--

-- Subprogram: g_Lib_Sha256_Nb_GetState

-- Test Case: SwUFn_0131.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_GetState
TEST.NEW
TEST.NAME:SwUFn_0131.001
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.END

-- Subprogram: g_Lib_Sha256_Nb_Process

-- Test Case: SwUFn_0130.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.001
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.002
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.002
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 5>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X80"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x80000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x80000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x80000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x80000000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x80000000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_ERROR
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x80000000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x80000000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x80000001
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.003
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.003
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 5>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0XFF"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0xFFFFFFFF
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_ERROR
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0xFFFFFFFF
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0xFFFFFFFF
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_ERROR
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.004
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.004
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_INIT
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x1A000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.005
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.005
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_FINAL
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x1
TEST.END

-- Test Case: SwUFn_0130.006
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.006
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:67
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:65
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:67
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:67
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x1
TEST.END

-- Test Case: SwUFn_0130.007
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.007
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_p_data:<<malloc 9>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_p_data:"0xFFF000"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:67
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:67
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:64
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x1
TEST.END

-- Test Case: SwUFn_0130.008
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.008
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_UPDATE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_p_data:<<malloc 1>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_p_data[0]:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0xFFF0000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0xFFA000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_ERROR
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:268369920
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0xFFA000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x1
TEST.END

-- Test Case: SwUFn_0130.009
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.009
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_DONE
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_DONE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.010
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.010
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:-1
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:255
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.011
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.011
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 4>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X0"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_FINAL
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x0
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_DONE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.012
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.012
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 3>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"-1"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:-1
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:-1
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:-1
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:-1
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:-1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:255
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:4294967295
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:4294967295
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Test Case: SwUFn_0130.013
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Process
TEST.NEW
TEST.NAME:SwUFn_0130.013
TEST.NOTES:
REQ/FI

TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:<<malloc 6>>
TEST.VALUE:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash:"0X100"
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0x100000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:6
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0x100000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0x100000000
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x100000000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_ctx.bitcount:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:6
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:4294967295
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:4294967295
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0x0
TEST.END

-- Subprogram: g_Lib_Sha256_Nb_Reset

-- Test Case: SwUFn_0132.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Reset
TEST.NEW
TEST.NAME:SwUFn_0132.001
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_data_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_processed_len:0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_process_count:0
TEST.END

-- Subprogram: g_Lib_Sha256_Nb_Start

-- Test Case: SwUFn_0129.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.001
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_IDLE
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_INIT
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.002
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.002
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_FINAL
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_FINAL
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.003
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.003
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_ERROR
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:E_LIB_SHA256_NB_STATE_INIT
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.004
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.004
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:-1
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:255
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.005
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.005
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:6
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:6
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.006
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.006
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:222
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:222
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Test Case: SwUFn_0129.007
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:g_Lib_Sha256_Nb_Start
TEST.NEW
TEST.NAME:SwUFn_0129.007
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_nb_state:555
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_nb_state:43
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u16g_Sha256_Hash_Update_Count:0
TEST.END

-- Subprogram: s_Sha256_Hash_Init

-- Test Case: SwUFn_0126.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_Sha256_Hash_Init
TEST.NEW
TEST.NAME:SwUFn_0126.001
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[0]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[1]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[2]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[3]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[4]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[5]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[6]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[7]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[8]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[9]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[10]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[11]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[12]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[13]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[14]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[15]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[16]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[17]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[18]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[19]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[20]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[21]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[22]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[23]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[24]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[25]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[26]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[27]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[28]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[29]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[30]:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[31]:0x0
TEST.END

-- Subprogram: s_safe_rotr

-- Test Case: SwUFn_0121.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.001
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0x0
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0x0
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0x0
TEST.END

-- Test Case: SwUFn_0121.002
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.002
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0x7FFFFFFF
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0x7F
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFE
TEST.END

-- Test Case: SwUFn_0121.003
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.003
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0xFFFFFFFF
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0xFF
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFF
TEST.END

-- Test Case: SwUFn_0121.004
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.004
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:-1
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:-1
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFF
TEST.END

-- Test Case: SwUFn_0121.005
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.005
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0x100000000
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0x100
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFF
TEST.END

-- Test Case: SwUFn_0121.006
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.006
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0x10007FFF0
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0x114
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFF
TEST.END

-- Test Case: SwUFn_0121.007
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_safe_rotr
TEST.NEW
TEST.NAME:SwUFn_0121.007
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_safe_rotr.value:0x10001247F
TEST.VALUE:Lib_sha256.s_safe_rotr.bits:0x67A
TEST.EXPECTED:Lib_sha256.s_safe_rotr.return:0xFFFFFFFF
TEST.END

-- Subprogram: s_sha256_final

-- Test Case: SwUFn_0125.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.001
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x0
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].bitcount:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.002
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.002
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x80000000
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.003
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.003
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0xFFFFFFFF
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.004
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.004
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..6]:-1
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[7]:-1
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:INPUT_BASE=16,EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.005
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.005
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x100000000
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.006
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.006
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x100000041
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.007
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.007
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x1FA094640
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0x0
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Test Case: SwUFn_0125.008
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_final
TEST.NEW
TEST.NAME:SwUFn_0125.008
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.VALUE:Lib_sha256.s_sha256_final.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].state[0..7]:0x0
TEST.VALUE:Lib_sha256.s_sha256_final.ctx[0].bitcount:456
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[56]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[57]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[58]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[59]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[60]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[61]:0x0
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[62]:0x1
TEST.EXPECTED:Lib_sha256.s_sha256_final.ctx[0].buffer[63]:0xC8
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_final.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Subprogram: s_sha256_init

-- Test Case: SwUFn_0123.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_init
TEST.NEW
TEST.NAME:SwUFn_0123.001
TEST.VALUE:Lib_sha256.s_sha256_init.ctx:<<malloc 1>>
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[0]:0x6A09E667
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[1]:0xBB67AE85
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[2]:0x3C6EF372
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[3]:0xA54FF53A
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[4]:0x510E527F
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[5]:0x9B05688C
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[6]:0x1F83D9AB
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].state[7]:0x5BE0CD19
TEST.EXPECTED:Lib_sha256.s_sha256_init.ctx[0].bitcount:0
TEST.END

-- Subprogram: s_sha256_transform

-- Test Case: SwUFn_0122.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_transform
TEST.NEW
TEST.NAME:SwUFn_0122.001
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_update
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:<<OPTIONS>>.EVENT_LIMIT:5
TEST.VALUE:Lib_sha256.s_sha256_transform.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_transform.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_transform.data[0]:0
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[7]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[8]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[9]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[10]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[11]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[12]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[13]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[14]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[15]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[16]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[17]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[18]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[19]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[20]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[21]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[22]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[23]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[24]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[25]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[26]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[27]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[28]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[29]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[30]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.<<GLOBAL>>.u8g_Lib_Sha256_Hash[31]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[0]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[1]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[2]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[3]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[4]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[5]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[6]:EXPECTED_BASE=16
TEST.ATTRIBUTES:Lib_sha256.s_sha256_transform.ctx[0].state[7]:EXPECTED_BASE=16
TEST.END

-- Subprogram: s_sha256_update

-- Test Case: SwUFn_0124.001
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.001
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x0
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x0
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x0
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x0
TEST.END

-- Test Case: SwUFn_0124.002
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.002
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x7FFF
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x7F
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x7F
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x83F7
TEST.END

-- Test Case: SwUFn_0124.003
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.003
TEST.NOTES:
REQ/BA
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0xFFFF
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0xFF
TEST.VALUE:Lib_sha256.s_sha256_update.len:0xFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x107F7
TEST.END

-- Test Case: SwUFn_0124.004
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.004
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x7FFF
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x7F
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x1FFF
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x17FF7
TEST.END

-- Test Case: SwUFn_0124.005
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.005
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_progress_callback:g_Lib_Sha256_Nb_Start
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x7FFF
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x7F
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x2000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:g_Lib_Sha256_Nb_Start
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x17FFF
TEST.END

-- Test Case: SwUFn_0124.006
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.006
TEST.NOTES:
REQ/EC
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x7FFF
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x7F
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x2000
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x17FFF
TEST.END

-- Test Case: SwUFn_0124.007
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.007
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x10000
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x100
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x100
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x10800
TEST.END

-- Test Case: SwUFn_0124.009
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.009
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x68430
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x416
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x409
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x6A478
TEST.END

-- Test Case: SwUFn_0124.010
TEST.UNIT:Lib_sha256
TEST.SUBPROGRAM:s_sha256_update
TEST.NEW
TEST.NAME:SwUFn_0124.010
TEST.NOTES:
REQ/FI
TEST.END_NOTES:
TEST.STUB:Lib_sha256.g_Lib_u8bit_ArrayClear
TEST.STUB:Lib_sha256.g_Lib_u16bit_ArrayClear
TEST.STUB:Lib_sha256.u8g_Lib_u8bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_u16bit_RangeCheck
TEST.STUB:Lib_sha256.u8g_Lib_s16bit_RangeCheck
TEST.STUB:Lib_sha256.u16g_Conv_AngleToPulse
TEST.STUB:Lib_sha256.s_safe_rotr
TEST.STUB:Lib_sha256.s_sha256_transform
TEST.STUB:Lib_sha256.s_sha256_init
TEST.STUB:Lib_sha256.s_sha256_final
TEST.STUB:Lib_sha256.s_Sha256_Hash_Init
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Start
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Process
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_GetState
TEST.STUB:Lib_sha256.g_Lib_Sha256_Nb_Reset
TEST.VALUE:Lib_sha256.s_sha256_update.ctx:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x18974
TEST.VALUE:Lib_sha256.s_sha256_update.data:<<malloc 1>>
TEST.VALUE:Lib_sha256.s_sha256_update.data[0]:0x150
TEST.VALUE:Lib_sha256.s_sha256_update.len:0x259
TEST.EXPECTED:Lib_sha256.<<GLOBAL>>.s_progress_callback:<<null>>
TEST.EXPECTED:Lib_sha256.s_sha256_update.ctx[0].bitcount:0x19C3C
TEST.END
