/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
/***********************************************
 * VectorCAST Unit Information
 *
 * Name: Lib_sha256
 *
 * Path: C:/workspace/NE1AW_PORTING/Lib/Lib_sha256.c
 *
 * Type: stub-by-function
 *
 * Unit Number: 9
 *
 ***********************************************/
#ifndef VCAST_DRIVER_ONLY
/* Include the file which contains function prototypes
for stub processing and value/expected user code */
#include "vcast_uc_prototypes.h"
#include "vcast_basics.h"
/* STUB_DEPENDENCY_USER_CODE */
/* STUB_DEPENDENCY_USER_CODE_END */
#else
#include "vcast_env_defines.h"
#define __VCAST_BASICS_H__
#endif /* VCAST_DRIVER_ONLY */
#ifndef VCAST_DRIVER_ONLY
#ifndef VCAST_DONT_RENAME_EXIT
#ifdef __cplusplus
extern "C" {
#endif
void exit (int status);
#ifdef __cplusplus
}
#endif
/* used to capture the exit call */
#define exit VCAST_exit
#endif /* VCAST_DONT_RENAME_EXIT */
#endif /* VCAST_DRIVER_ONLY */
#ifndef VCAST_DRIVER_ONLY
#define VCAST_HEADER_EXPANSION
#ifdef VCAST_COVERAGE
#include "Lib_sha256_inst_prefix.c"
#else
#include "Lib_sha256_vcast_prefix.c"
#endif
#ifdef VCAST_COVERAGE
/* If coverage is enabled, include the instrumented UUT */
#include "Lib_sha256_inst.c"
#else
/* If coverage is not enabled, include the original UUT */
#include "Lib_sha256_vcast.c"
#endif
#ifdef VCAST_COVERAGE
#include "Lib_sha256_inst_appendix.c"
#else
#include "Lib_sha256_vcast_appendix.c"
#endif
#endif /* VCAST_DRIVER_ONLY */
#include "Lib_sha256_driver_prefix.c"
#ifdef VCAST_HEADER_EXPANSION
#ifdef VCAST_COVERAGE
#include "Lib_sha256_exp_inst_driver.c"
#else
#include "Lib_sha256_expanded_driver.c"
#endif /*VCAST_COVERAGE*/
#else
#include "S0000009.h"
#include "vcast_undef_9.h"
/* Include the file which contains function prototypes
for stub processing and value/expected user code */
#include "vcast_uc_prototypes.h"
#include "vcast_objs_9.c"
#include "vcast_stubs_9.c"
/* begin declarations of inlined friends */
/* end declarations of inlined friends */
void VCAST_DRIVER_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 0:
      vCAST_SET_HISTORY_FLAGS ( 9, 0);
      vCAST_USER_CODE_TIMER_START();
      break;
    case 7: {
      /* U32  s_safe_rotr(U32  value, U8  bits) */
      vCAST_SET_HISTORY_FLAGS ( 9, 7 );
      vCAST_USER_CODE_TIMER_START();
      R_9_7 = 
      ( s_safe_rotr(
        ( P_9_7_1 ),
        ( P_9_7_2 ) ) );
      break; }
    case 8: {
      /* void  s_sha256_transform(SHA256_CTX  * ctx, const U8   data[]) */
      vCAST_SET_HISTORY_FLAGS ( 9, 8 );
      vCAST_USER_CODE_TIMER_START();
      ( s_sha256_transform(
        ( P_9_8_1 ),
        ( P_9_8_2 ) ) );
      break; }
    case 9: {
      /* void  s_sha256_init(SHA256_CTX  * ctx) */
      vCAST_SET_HISTORY_FLAGS ( 9, 9 );
      vCAST_USER_CODE_TIMER_START();
      ( s_sha256_init(
        ( P_9_9_1 ) ) );
      break; }
    case 10: {
      /* void  s_sha256_update(SHA256_CTX  * ctx, const U8  * data, U32  len) */
      vCAST_SET_HISTORY_FLAGS ( 9, 10 );
      vCAST_USER_CODE_TIMER_START();
      ( s_sha256_update(
        ( P_9_10_1 ),
        ( ((const unsigned char  *)(P_9_10_2)) ),
        ( P_9_10_3 ) ) );
      break; }
    case 11: {
      /* void  s_sha256_final(SHA256_CTX  * ctx, U8  * hash) */
      vCAST_SET_HISTORY_FLAGS ( 9, 11 );
      vCAST_USER_CODE_TIMER_START();
      ( s_sha256_final(
        ( P_9_11_1 ),
        ( P_9_11_2 ) ) );
      break; }
    case 12: {
      /* void  s_Sha256_Hash_Init(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 12 );
      vCAST_USER_CODE_TIMER_START();
      ( s_Sha256_Hash_Init( ) );
      break; }
    case 13: {
      /* void  g_Lib_Sha256_Nb_Start(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 13 );
      vCAST_USER_CODE_TIMER_START();
      ( g_Lib_Sha256_Nb_Start( ) );
      break; }
    case 14: {
      /* void  g_Lib_Sha256_Nb_Process(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 14 );
      vCAST_USER_CODE_TIMER_START();
      ( g_Lib_Sha256_Nb_Process( ) );
      break; }
    case 15: {
      /* E_LIB_SHA256_NB_STATE  g_Lib_Sha256_Nb_GetState(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 15 );
      vCAST_USER_CODE_TIMER_START();
      R_9_15 = 
      ( g_Lib_Sha256_Nb_GetState( ) );
      break; }
    case 16: {
      /* void  g_Lib_Sha256_Nb_Reset(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 16 );
      vCAST_USER_CODE_TIMER_START();
      ( g_Lib_Sha256_Nb_Reset( ) );
      break; }
    default:
      vectorcast_print_string("ERROR: Internal Tool Error\n");
      break;
  } /* switch */
  vCAST_USER_CODE_TIMER_STOP();
}

void VCAST_SBF_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 7: {
      SBF_9_7 = 0;
      break; }
    case 8: {
      SBF_9_8 = 0;
      break; }
    case 9: {
      SBF_9_9 = 0;
      break; }
    case 10: {
      SBF_9_10 = 0;
      break; }
    case 11: {
      SBF_9_11 = 0;
      break; }
    case 12: {
      SBF_9_12 = 0;
      break; }
    case 13: {
      SBF_9_13 = 0;
      break; }
    case 14: {
      SBF_9_14 = 0;
      break; }
    case 15: {
      SBF_9_15 = 0;
      break; }
    case 16: {
      SBF_9_16 = 0;
      break; }
    default:
      break;
  } /* switch */
}
#include "vcast_ti_decls_9.h"
void VCAST_RUN_DATA_IF_9( int VCAST_SUB_INDEX, int VCAST_PARAM_INDEX ) {
  switch ( VCAST_SUB_INDEX ) {
    case 0: /* for global objects */
      switch( VCAST_PARAM_INDEX ) {
        case 10: /* for global object u16g_SysOptCtrl_OverOpenDeg */
          VCAST_TI_9_3 ( &(u16g_SysOptCtrl_OverOpenDeg));
          break;
        case 11: /* for global object s16g_SysOptCtrl_OverPos */
          VCAST_TI_9_4 ( &(s16g_SysOptCtrl_OverPos));
          break;
        case 1: /* for global object s_progress_callback */
          VCAST_TI_9_5 ( &(s_progress_callback));
          break;
        case 2: /* for global object u8g_Lib_Sha256_Hash */
          VCAST_TI_9_8 ( u8g_Lib_Sha256_Hash);
          break;
        case 3: /* for global object s_nb_ctx */
          VCAST_TI_9_10 ( &(s_nb_ctx));
          break;
        case 4: /* for global object s_nb_state */
          VCAST_TI_9_15 ( &(s_nb_state));
          break;
        case 5: /* for global object s_nb_p_data */
          VCAST_TI_9_2 ( ((unsigned char  **)(&(s_nb_p_data))));
          break;
        case 6: /* for global object s_nb_data_len */
          VCAST_TI_9_7 ( &(s_nb_data_len));
          break;
        case 7: /* for global object s_nb_processed_len */
          VCAST_TI_9_7 ( &(s_nb_processed_len));
          break;
        case 8: /* for global object s_nb_process_count */
          VCAST_TI_9_7 ( &(s_nb_process_count));
          break;
        case 9: /* for global object u16g_Sha256_Hash_Update_Count */
          VCAST_TI_9_3 ( &(u16g_Sha256_Hash_Update_Count));
          break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      } /* switch( VCAST_PARAM_INDEX ) */
      break; /* case 0 (global objects) */
    case 1: /* function g_Lib_u8bit_ArrayClear */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_1_1));
          break;
        case 2:
          VCAST_TI_9_9 ( &(P_9_1_2));
          break;
        case 3:
          VCAST_TI_9_9 ( &(P_9_1_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_1 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_u8bit_ArrayClear */
    case 2: /* function g_Lib_u16bit_ArrayClear */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_17 ( &(P_9_2_1));
          break;
        case 2:
          VCAST_TI_9_3 ( &(P_9_2_2));
          break;
        case 3:
          VCAST_TI_9_9 ( &(P_9_2_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_2 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_u16bit_ArrayClear */
    case 3: /* function u8g_Lib_u8bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_9 ( &(P_9_3_1));
          break;
        case 2:
          VCAST_TI_9_9 ( &(P_9_3_2));
          break;
        case 3:
          VCAST_TI_9_9 ( &(P_9_3_3));
          break;
        case 4:
          VCAST_TI_9_9 ( &(R_9_3));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_3 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_u8bit_RangeCheck */
    case 4: /* function u8g_Lib_u16bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_3 ( &(P_9_4_1));
          break;
        case 2:
          VCAST_TI_9_3 ( &(P_9_4_2));
          break;
        case 3:
          VCAST_TI_9_3 ( &(P_9_4_3));
          break;
        case 4:
          VCAST_TI_9_9 ( &(R_9_4));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_4 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_u16bit_RangeCheck */
    case 5: /* function u8g_Lib_s16bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_4 ( &(P_9_5_1));
          break;
        case 2:
          VCAST_TI_9_4 ( &(P_9_5_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(P_9_5_3));
          break;
        case 4:
          VCAST_TI_9_9 ( &(R_9_5));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_5 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_s16bit_RangeCheck */
    case 6: /* function u16g_Conv_AngleToPulse */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_3 ( &(P_9_6_1));
          break;
        case 2:
          VCAST_TI_9_3 ( &(R_9_6));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_6 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u16g_Conv_AngleToPulse */
    case 7: /* function s_safe_rotr */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_7 ( &(P_9_7_1));
          break;
        case 2:
          VCAST_TI_9_9 ( &(P_9_7_2));
          break;
        case 3:
          VCAST_TI_9_7 ( &(R_9_7));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_7 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_safe_rotr */
    case 8: /* function s_sha256_transform */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_18 ( &(P_9_8_1));
          break;
        case 2:
          if( vCAST_COMMAND == vCAST_SET_VAL )
            P_9_8_2_set = vCAST_true;
          VCAST_TI_9_2 ( &(P_9_8_2));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_8 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_sha256_transform */
    case 9: /* function s_sha256_init */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_18 ( &(P_9_9_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_9 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_sha256_init */
    case 10: /* function s_sha256_update */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_18 ( &(P_9_10_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_10_2));
          break;
        case 3:
          VCAST_TI_9_7 ( &(P_9_10_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_10 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_sha256_update */
    case 11: /* function s_sha256_final */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_18 ( &(P_9_11_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_11_2));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_11 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_sha256_final */
    case 12: /* function s_Sha256_Hash_Init */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_12 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_Sha256_Hash_Init */
    case 13: /* function g_Lib_Sha256_Nb_Start */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_13 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_Sha256_Nb_Start */
    case 14: /* function g_Lib_Sha256_Nb_Process */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_14 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_Sha256_Nb_Process */
    case 15: /* function g_Lib_Sha256_Nb_GetState */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_15 ( &(R_9_15));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_15 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_Sha256_Nb_GetState */
    case 16: /* function g_Lib_Sha256_Nb_Reset */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_16 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_Sha256_Nb_Reset */
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  } /* switch ( VCAST_SUB_INDEX ) */
}


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_3 ( unsigned  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_3 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_3 ( unsigned  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned   ) VCAST_PARAM_AS_LONGEST_UNSIGNED();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = UINT_MIN;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (UINT_MIN / 2) + (UINT_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = UINT_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = UINT_MIN;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = UINT_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_3 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_4 ( signed int  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_4 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_4 ( signed int  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( signed int   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = INT_MIN;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (INT_MIN / 2) + (INT_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = INT_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = INT_MIN;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = INT_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_4 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_5 ( void  (**vcast_param)(void) ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_5 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_5 ( void  (**vcast_param)(void) ) 
{
  unsigned vcast_index;
  void  (*vcast_local_array[])(void) = {
    s_Sha256_Hash_Init,
    g_Lib_Sha256_Nb_Start,
    g_Lib_Sha256_Nb_Process,
    g_Lib_Sha256_Nb_Reset,
    0
  };
  switch ( vCAST_COMMAND ) {
    case vCAST_PRINT:
      if ( !*vcast_param )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "<<null>>\n");
      else {
        for (vcast_index = 0; vcast_index < 4; vcast_index++) {
          if ( *vcast_param == vcast_local_array[ vcast_index ] ) {
            vectorcast_fprint_integer (vCAST_OUTPUT_FILE, vcast_index );
            vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
            break;
          }
        }
        if (vcast_index == 4) {
          vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<unknown>>\n");
        }
      }
      break;
    case vCAST_SET_VAL:
      if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
        return;
      }
      vcast_index = (unsigned) VCAST_PARAM_AS_LONGEST_UNSIGNED();
      if ( vcast_index < 4 ) {
        *vcast_param = vcast_local_array[ vcast_index ];
      }
      break;
    }
} /* end VCAST_TI_9_5 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_8 ( unsigned char  vcast_param[(U8 )32U] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_8 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_8 ( unsigned char  vcast_param[(U8 )32U] ) 
{
  {
    int VCAST_TI_9_8_array_index = 0;
    int VCAST_TI_9_8_index = 0;
    int VCAST_TI_9_8_first, VCAST_TI_9_8_last;
    int VCAST_TI_9_8_local_field = 0;
    int VCAST_TI_9_8_value_printed = 0;
    int VCAST_TI_9_8_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_8_first, &VCAST_TI_9_8_last);
    VCAST_TI_9_8_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_8_upper = 32;
      for (VCAST_TI_9_8_array_index=0; VCAST_TI_9_8_array_index< VCAST_TI_9_8_upper; VCAST_TI_9_8_array_index++){
        if ( (VCAST_TI_9_8_index >= VCAST_TI_9_8_first) && ( VCAST_TI_9_8_index <= VCAST_TI_9_8_last)){
          if ( VCAST_TI_9_8_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_8_upper);
          else
            VCAST_TI_9_9 ( &(vcast_param[VCAST_TI_9_8_index]));
          VCAST_TI_9_8_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_8_local_field;
        } /* if */
        if (VCAST_TI_9_8_index >= VCAST_TI_9_8_last)
          break;
        VCAST_TI_9_8_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_8_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_8 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_10 ( SHA256_CTX  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_10 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_10 ( SHA256_CTX  *vcast_param ) 
{
#if (defined(VCAST_NO_TYPE_SUPPORT))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
  {
    switch ( vcast_get_param () ) { /* Choose field member */
      /* Setting member variable vcast_param->state */
      case 1: { 
        VCAST_TI_9_12 ( vcast_param->state);
        break; /* end case 1*/
      } /* end case */
      /* Setting member variable vcast_param->bitcount */
      case 2: { 
        VCAST_TI_9_13 ( &(vcast_param->bitcount));
        break; /* end case 2*/
      } /* end case */
      /* Setting member variable vcast_param->buffer */
      case 3: { 
        VCAST_TI_9_14 ( vcast_param->buffer);
        break; /* end case 3*/
      } /* end case */
      default:
        vCAST_TOOL_ERROR = vCAST_true;
    } /* end switch */ 
  }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

} /* end VCAST_TI_9_10 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_15 ( E_LIB_SHA256_NB_STATE  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_15 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_15 ( E_LIB_SHA256_NB_STATE  *vcast_param ) 
{
#if (defined(VCAST_NO_TYPE_SUPPORT))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
  switch ( vCAST_COMMAND ) {
    case vCAST_PRINT: {
      if ( vcast_param == 0 )
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_long_long(vCAST_OUTPUT_FILE, (VCAST_LONGEST_INT)*vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      } /* end else */
      } /* end vCAST_PRINT block */
      break; /* end case vCAST_PRINT */
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL:
    *vcast_param = (E_LIB_SHA256_NB_STATE  )VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL:
    *vcast_param = E_LIB_SHA256_NB_STATE_IDLE;
    break; /* end case vCAST_FIRST_VAL */
  case vCAST_LAST_VAL:
    *vcast_param = E_LIB_SHA256_NB_STATE_ERROR;
    break; /* end case vCAST_LAST_VAL */
  default:
    vCAST_TOOL_ERROR = vCAST_true;
    break; /* end case default */
} /* end switch */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

} /* end VCAST_TI_9_15 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_2 ( unsigned char  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_2 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_2 ( unsigned char  **vcast_param ) 
{
  {
    int VCAST_TI_9_2_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_2_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_2_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_2_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_2_array_size*(sizeof(unsigned char  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_2_array_size*(sizeof(unsigned char  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_2_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        if (VCAST_FIND_INDEX() == -1 )
          VCAST_TI_STRING ( (char**)vcast_param, 0,-1);
        else {
          VCAST_TI_9_2_index = vcast_get_param();
          VCAST_TI_9_9 ( &((*vcast_param)[VCAST_TI_9_2_index]));
        }
      }
    }
  }
} /* end VCAST_TI_9_2 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_7 ( unsigned long  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_7 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_7 ( unsigned long  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_long(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned long   ) VCAST_PARAM_AS_LONGEST_UNSIGNED();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = ULONG_MIN;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (ULONG_MIN / 2) + (ULONG_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = ULONG_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = ULONG_MIN;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = ULONG_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_7 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_9 ( unsigned char  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_9 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_9 ( unsigned char  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned char   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = UCHAR_MIN;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (UCHAR_MIN / 2) + (UCHAR_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = UCHAR_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = UCHAR_MIN;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = UCHAR_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_9 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_17 ( unsigned  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_17 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_17 ( unsigned  **vcast_param ) 
{
  {
    int VCAST_TI_9_17_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_17_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_17_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_17_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_17_array_size*(sizeof(unsigned  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_17_array_size*(sizeof(unsigned  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_17_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_17_index = vcast_get_param();
        VCAST_TI_9_3 ( &((*vcast_param)[VCAST_TI_9_17_index]));
      }
    }
  }
} /* end VCAST_TI_9_17 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_18 ( SHA256_CTX  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_18 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_18 ( SHA256_CTX  **vcast_param ) 
{
  {
    int VCAST_TI_9_18_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_18_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_18_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_18_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_18_array_size*(sizeof(SHA256_CTX  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_18_array_size*(sizeof(SHA256_CTX  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_18_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_18_index = vcast_get_param();
        VCAST_TI_9_10 ( &((*vcast_param)[VCAST_TI_9_18_index]));
      }
    }
  }
} /* end VCAST_TI_9_18 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_12 ( unsigned long  vcast_param[8] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_12 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_12 ( unsigned long  vcast_param[8] ) 
{
  {
    int VCAST_TI_9_12_array_index = 0;
    int VCAST_TI_9_12_index = 0;
    int VCAST_TI_9_12_first, VCAST_TI_9_12_last;
    int VCAST_TI_9_12_local_field = 0;
    int VCAST_TI_9_12_value_printed = 0;

    vcast_get_range_value (&VCAST_TI_9_12_first, &VCAST_TI_9_12_last);
    VCAST_TI_9_12_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_12_upper = 8;
      for (VCAST_TI_9_12_array_index=0; VCAST_TI_9_12_array_index< VCAST_TI_9_12_upper; VCAST_TI_9_12_array_index++){
        if ( (VCAST_TI_9_12_index >= VCAST_TI_9_12_first) && ( VCAST_TI_9_12_index <= VCAST_TI_9_12_last)){
          VCAST_TI_9_7 ( &(vcast_param[VCAST_TI_9_12_index]));
          VCAST_TI_9_12_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_12_local_field;
        } /* if */
        if (VCAST_TI_9_12_index >= VCAST_TI_9_12_last)
          break;
        VCAST_TI_9_12_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_12_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_12 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_13 ( unsigned long long  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_13 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_13 ( unsigned long long  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_long(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned long long   ) VCAST_PARAM_AS_LONGEST_UNSIGNED();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = 0;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (ULLONG_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = ULLONG_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = 0;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = ULLONG_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_13 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_14 ( unsigned char  vcast_param[64] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_14 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_14 ( unsigned char  vcast_param[64] ) 
{
  {
    int VCAST_TI_9_14_array_index = 0;
    int VCAST_TI_9_14_index = 0;
    int VCAST_TI_9_14_first, VCAST_TI_9_14_last;
    int VCAST_TI_9_14_local_field = 0;
    int VCAST_TI_9_14_value_printed = 0;
    int VCAST_TI_9_14_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_14_first, &VCAST_TI_9_14_last);
    VCAST_TI_9_14_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_14_upper = 64;
      for (VCAST_TI_9_14_array_index=0; VCAST_TI_9_14_array_index< VCAST_TI_9_14_upper; VCAST_TI_9_14_array_index++){
        if ( (VCAST_TI_9_14_index >= VCAST_TI_9_14_first) && ( VCAST_TI_9_14_index <= VCAST_TI_9_14_last)){
          if ( VCAST_TI_9_14_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_14_upper);
          else
            VCAST_TI_9_9 ( &(vcast_param[VCAST_TI_9_14_index]));
          VCAST_TI_9_14_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_14_local_field;
        } /* if */
        if (VCAST_TI_9_14_index >= VCAST_TI_9_14_last)
          break;
        VCAST_TI_9_14_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_14_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_14 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


#ifdef VCAST_PARADIGM_ADD_SEGMENT
#pragma new_codesegment(1)
#endif
void VCAST_TI_RANGE_DATA_9 ( void ) {
#define VCAST_TI_SCALAR_TYPE "NEW_SCALAR\n"
#define VCAST_TI_ARRAY_TYPE  "NEW_ARRAY\n"
#define VCAST_TI_VECTOR_TYPE "NEW_VECTOR\n"
  /* Range Data for TI (scalar) VCAST_TI_9_3 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900002\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,(UINT_MIN / 2) + (UINT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (scalar) VCAST_TI_9_7 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900007\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,ULONG_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,(ULONG_MIN / 2) + (ULONG_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,ULONG_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_12 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100006\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,8);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (scalar) VCAST_TI_9_13 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900010\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,(ULLONG_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,ULLONG_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_14 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100007\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,64);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (array) VCAST_TI_9_8 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100004\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,32);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (scalar) VCAST_TI_9_9 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900008\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(UCHAR_MIN / 2) + (UCHAR_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (scalar) VCAST_TI_9_4 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,INT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(INT_MIN / 2) + (INT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,INT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_1 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,64);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
}
/* Include the file which contains function implementations
for stub processing and value/expected user code */
#include "Lib_sha256_uc.c"

void vCAST_COMMON_STUB_PROC_9(
            int unitIndex,
            int subprogramIndex,
            int robjectIndex,
            int readEobjectData )
{
   vCAST_BEGIN_STUB_PROC_9(unitIndex, subprogramIndex);
   if ( robjectIndex )
      vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM( unitIndex, subprogramIndex, robjectIndex );
   if ( readEobjectData )
      vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM( unitIndex, subprogramIndex, 0 );
   vCAST_SET_HISTORY( unitIndex, subprogramIndex );
   vCAST_READ_COMMAND_DATA( vCAST_CURRENT_SLOT, unitIndex, subprogramIndex, vCAST_true, vCAST_false );
   vCAST_READ_COMMAND_DATA_FOR_USER_GLOBALS();
   vCAST_STUB_PROCESSING_9(unitIndex, subprogramIndex);
}
#endif /* VCAST_HEADER_EXPANSION */
