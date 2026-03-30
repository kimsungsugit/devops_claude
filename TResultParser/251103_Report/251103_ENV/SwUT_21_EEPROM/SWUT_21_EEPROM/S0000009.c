/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
/***********************************************
 * VectorCAST Unit Information
 *
 * Name: EEPROM
 *
 * Path: C:/workspace/NE1AW_PORTING/Generated_Code/EEPROM.c
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
#include "EEPROM_inst_prefix.c"
#else
#include "EEPROM_vcast_prefix.c"
#endif
#ifdef VCAST_COVERAGE
/* If coverage is enabled, include the instrumented UUT */
#include "EEPROM_inst.c"
#else
/* If coverage is not enabled, include the original UUT */
#include "EEPROM_vcast.c"
#endif
#ifdef VCAST_COVERAGE
#include "EEPROM_inst_appendix.c"
#else
#include "EEPROM_vcast_appendix.c"
#endif
#endif /* VCAST_DRIVER_ONLY */
#include "EEPROM_driver_prefix.c"
#ifdef VCAST_HEADER_EXPANSION
#ifdef VCAST_COVERAGE
#include "EEPROM_exp_inst_driver.c"
#else
#include "EEPROM_expanded_driver.c"
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
    case 1: {
      /* void  BackupSector(EEPROM_TAddress_  Addr, word  From, word  To) */
      vCAST_SET_HISTORY_FLAGS ( 9, 1 );
      vCAST_USER_CODE_TIMER_START();
      ( BackupSector(
        ( P_9_1_1 ),
        ( P_9_1_2 ),
        ( P_9_1_3 ) ) );
      break; }
    case 2: {
      /* byte  WriteBlock(EEPROM_TAddress_  Addr, word  From, word  To, word  * Data) */
      vCAST_SET_HISTORY_FLAGS ( 9, 2 );
      vCAST_USER_CODE_TIMER_START();
      R_9_2 = 
      ( WriteBlock(
        ( P_9_2_1 ),
        ( P_9_2_2 ),
        ( P_9_2_3 ),
        ( P_9_2_4 ) ) );
      break; }
    case 3: {
      /* byte  SetupFCCOB(dword  PhraseAddr, word  From, word  To, word  * Data, word  * pIndex) */
      vCAST_SET_HISTORY_FLAGS ( 9, 3 );
      vCAST_USER_CODE_TIMER_START();
      R_9_3 = 
      ( SetupFCCOB(
        ( P_9_3_1 ),
        ( P_9_3_2 ),
        ( P_9_3_3 ),
        ( P_9_3_4 ),
        ( P_9_3_5 ) ) );
      break; }
    case 4: {
      /* byte  EraseSectorInternal(EEPROM_TAddress_  Addr) */
      vCAST_SET_HISTORY_FLAGS ( 9, 4 );
      vCAST_USER_CODE_TIMER_START();
      R_9_4 = 
      ( EraseSectorInternal(
        ( P_9_4_1 ) ) );
      break; }
    case 5: {
      /* byte  WriteWord(EEPROM_TAddress_  AddrRow, word  Data16) */
      vCAST_SET_HISTORY_FLAGS ( 9, 5 );
      vCAST_USER_CODE_TIMER_START();
      R_9_5 = 
      ( WriteWord(
        ( P_9_5_1 ),
        ( P_9_5_2 ) ) );
      break; }
    case 6: {
      /* byte  EEPROM_SetByte(EEPROM_TAddress_Const  Addr, byte  Data) */
      vCAST_SET_HISTORY_FLAGS ( 9, 6 );
      vCAST_USER_CODE_TIMER_START();
      R_9_6 = 
      ( EEPROM_SetByte(
        ( P_9_6_1 ),
        ( P_9_6_2 ) ) );
      break; }
    case 7: {
      /* byte  EEPROM_GetByte(EEPROM_TAddress_Const  Addr, byte  * Data) */
      vCAST_SET_HISTORY_FLAGS ( 9, 7 );
      vCAST_USER_CODE_TIMER_START();
      R_9_7 = 
      ( EEPROM_GetByte(
        ( P_9_7_1 ),
        ( P_9_7_2 ) ) );
      break; }
    case 8: {
      /* void  EEPROM_Init(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 8 );
      vCAST_USER_CODE_TIMER_START();
      ( EEPROM_Init( ) );
      break; }
    default:
      vectorcast_print_string("ERROR: Internal Tool Error\n");
      break;
  } /* switch */
  vCAST_USER_CODE_TIMER_STOP();
}

void VCAST_SBF_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 1: {
      SBF_9_1 = 0;
      break; }
    case 2: {
      SBF_9_2 = 0;
      break; }
    case 3: {
      SBF_9_3 = 0;
      break; }
    case 4: {
      SBF_9_4 = 0;
      break; }
    case 5: {
      SBF_9_5 = 0;
      break; }
    case 6: {
      SBF_9_6 = 0;
      break; }
    case 7: {
      SBF_9_7 = 0;
      break; }
    case 8: {
      SBF_9_8 = 0;
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
        case 2: /* for global object _FCLKDIV */
          VCAST_TI_9_1 ( ((volatile FCLKDIVSTR  *)(&(_FCLKDIV))));
          break;
        case 3: /* for global object _FCCOBIX */
          VCAST_TI_9_7 ( ((volatile FCCOBIXSTR  *)(&(_FCCOBIX))));
          break;
        case 4: /* for global object _FSTAT */
          VCAST_TI_9_12 ( ((volatile FSTATSTR  *)(&(_FSTAT))));
          break;
        case 5: /* for global object _FCCOB0 */
          VCAST_TI_9_17 ( ((volatile FCCOB0STR  *)(&(_FCCOB0))));
          break;
        case 6: /* for global object _FCCOB1 */
          VCAST_TI_9_27 ( ((volatile FCCOB1STR  *)(&(_FCCOB1))));
          break;
        case 7: /* for global object _FCCOB2 */
          VCAST_TI_9_36 ( ((volatile FCCOB2STR  *)(&(_FCCOB2))));
          break;
        case 1: /* for global object BackupArray */
          VCAST_TI_9_45 ( BackupArray);
          break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      } /* switch( VCAST_PARAM_INDEX ) */
      break; /* case 0 (global objects) */
    case 1: /* function BackupSector */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_1_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_1_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_1_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_1 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function BackupSector */
    case 2: /* function WriteBlock */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_2_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_2_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_2_3));
          break;
        case 4:
          VCAST_TI_9_46 ( &(P_9_2_4));
          break;
        case 5:
          VCAST_TI_9_4 ( &(R_9_2));
          break;
        case 6:
          VCAST_TI_SBF_OBJECT( &SBF_9_2 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function WriteBlock */
    case 3: /* function SetupFCCOB */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_47 ( &(P_9_3_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_3_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_3_3));
          break;
        case 4:
          VCAST_TI_9_46 ( &(P_9_3_4));
          break;
        case 5:
          VCAST_TI_9_46 ( &(P_9_3_5));
          break;
        case 6:
          VCAST_TI_9_4 ( &(R_9_3));
          break;
        case 7:
          VCAST_TI_SBF_OBJECT( &SBF_9_3 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function SetupFCCOB */
    case 4: /* function EraseSectorInternal */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_4_1));
          break;
        case 2:
          VCAST_TI_9_4 ( &(R_9_4));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_4 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function EraseSectorInternal */
    case 5: /* function WriteWord */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_5_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_5_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_5));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_5 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function WriteWord */
    case 6: /* function EEPROM_SetByte */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_6_1));
          break;
        case 2:
          VCAST_TI_9_4 ( &(P_9_6_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_6));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_6 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function EEPROM_SetByte */
    case 7: /* function EEPROM_GetByte */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_7_1));
          break;
        case 2:
          VCAST_TI_9_48 ( &(P_9_7_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_7));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_7 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function EEPROM_GetByte */
    case 8: /* function EEPROM_Init */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_8 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function EEPROM_Init */
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  } /* switch ( VCAST_SUB_INDEX ) */
}


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_1 ( volatile FCLKDIVSTR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_1 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_1 ( volatile FCLKDIVSTR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_3_jmpval;
    VCAST_TI_9_3_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_3_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Byte */
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.FDIV0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIV1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIV2 */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIV3 */
              case 4: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 4*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIV4 */
              case 5: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 5*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIV5 */
              case 6: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIV5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 6*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIVLCK */
              case 7: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIVLCK;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIVLCK = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 7*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FDIVLD */
              case 8: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FDIVLD;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIVLD = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 8*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->MergedBits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->MergedBits.grpFDIV */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->MergedBits.grpFDIV;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 6, vCAST_false );
                vcast_param->MergedBits.grpFDIV = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_1 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_7 ( volatile FCCOBIXSTR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_7 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_7 ( volatile FCCOBIXSTR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_9_jmpval;
    VCAST_TI_9_9_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_9_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Byte */
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.CCOBIX0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOBIX0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOBIX1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOBIX1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOBIX2 */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOBIX2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->MergedBits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->MergedBits.grpCCOBIX */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->MergedBits.grpCCOBIX;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 3, vCAST_false );
                vcast_param->MergedBits.grpCCOBIX = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_7 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_12 ( volatile FSTATSTR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_12 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_12 ( volatile FSTATSTR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_14_jmpval;
    VCAST_TI_9_14_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_14_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Byte */
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.MGSTAT0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.MGSTAT0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGSTAT0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.MGSTAT1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.MGSTAT1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGSTAT1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.MGBUSY */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.MGBUSY;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGBUSY = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.FPVIOL */
              case 4: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.FPVIOL;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FPVIOL = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 4*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.ACCERR */
              case 5: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.ACCERR;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.ACCERR = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 5*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCIF */
              case 6: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCIF;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCIF = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 6*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->MergedBits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->MergedBits.grpMGSTAT */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->MergedBits.grpMGSTAT;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 2, vCAST_false );
                vcast_param->MergedBits.grpMGSTAT = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_12 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_17 ( volatile FCCOB0STR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_17 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_17 ( volatile FCCOB0STR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_19_jmpval;
    VCAST_TI_9_19_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_19_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Word */
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Overlap_STR */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR */
              case 1: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_22_jmpval;
                  VCAST_TI_9_22_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_22_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB0HISTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB8 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB9 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB10 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB11 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB12 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB13 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB14 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB15 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR */
              case 2: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_24_jmpval;
                  VCAST_TI_9_24_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_24_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB0LOSTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB0 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB1 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB2 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB3 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB4 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB5 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB6 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB7 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 2*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.CCOB0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB2 */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB3 */
              case 4: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 4*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB4 */
              case 5: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 5*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB5 */
              case 6: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 6*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB6 */
              case 7: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 7*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB7 */
              case 8: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 8*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB8 */
              case 9: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 9*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB9 */
              case 10: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 10*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB10 */
              case 11: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 11*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB11 */
              case 12: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 12*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB12 */
              case 13: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 13*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB13 */
              case 14: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 14*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB14 */
              case 15: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 15*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB15 */
              case 16: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 16*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_17 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_27 ( volatile FCCOB1STR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_27 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_27 ( volatile FCCOB1STR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_29_jmpval;
    VCAST_TI_9_29_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_29_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Word */
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Overlap_STR */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR */
              case 1: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_31_jmpval;
                  VCAST_TI_9_31_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_31_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB1HISTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB8 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB9 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB10 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB11 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB12 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB13 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB14 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB15 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR */
              case 2: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_33_jmpval;
                  VCAST_TI_9_33_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_33_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB1LOSTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB0 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB1 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB2 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB3 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB4 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB5 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB6 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB7 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 2*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.CCOB0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB2 */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB3 */
              case 4: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 4*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB4 */
              case 5: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 5*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB5 */
              case 6: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 6*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB6 */
              case 7: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 7*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB7 */
              case 8: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 8*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB8 */
              case 9: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 9*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB9 */
              case 10: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 10*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB10 */
              case 11: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 11*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB11 */
              case 12: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 12*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB12 */
              case 13: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 13*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB13 */
              case 14: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 14*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB14 */
              case 15: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 15*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB15 */
              case 16: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 16*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_27 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_36 ( volatile FCCOB2STR  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_36 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_36 ( volatile FCCOB2STR  *vcast_param ) 
{
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
  {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    int VCAST_TI_9_38_jmpval;
    VCAST_TI_9_38_jmpval = setjmp ( VCAST_env );
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_38_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
      switch ( vcast_get_param () ) { /* Choose field member */
        /* Setting member variable vcast_param->Word */
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break; /* end case 1*/
        } /* end case */
        /* Setting member variable vcast_param->Overlap_STR */
        case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR */
              case 1: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_40_jmpval;
                  VCAST_TI_9_40_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_40_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB2HISTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB8 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB9 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB10 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB11 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB12 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB13 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB14 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB15 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR */
              case 2: { 
#if ((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))
                /* User code: type is not supported */
                vcast_not_supported();
#else /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/
                {
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  int VCAST_TI_9_42_jmpval;
                  VCAST_TI_9_42_jmpval = setjmp ( VCAST_env );
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_42_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                    switch ( vcast_get_param () ) { /* Choose field member */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Byte */
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB2LOSTR.Byte));
                        break; /* end case 1*/
                      } /* end case */
                      /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits */
                      case 2: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
                        /* User code: type is not supported */
                        vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
                        {
                          switch ( vcast_get_param () ) { /* Choose field member */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB0 */
                            case 1: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 1*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB1 */
                            case 2: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 2*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB2 */
                            case 3: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 3*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB3 */
                            case 4: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 4*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB4 */
                            case 5: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 5*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB5 */
                            case 6: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 6*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB6 */
                            case 7: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 7*/
                            } /* end case */
                            /* Setting member variable vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB7 */
                            case 8: { 
                              VCAST_LONGEST_INT VCAST_TI_9_4_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break; /* end case 8*/
                            } /* end case */
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          } /* end switch */ 
                        }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

                        break; /* end case 2*/
                      } /* end case */
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
                }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

                break; /* end case 2*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 2*/
        } /* end case */
        /* Setting member variable vcast_param->Bits */
        case 3: { 
#if (defined(VCAST_NO_TYPE_SUPPORT))
          /* User code: type is not supported */
          vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
          {
            switch ( vcast_get_param () ) { /* Choose field member */
              /* Setting member variable vcast_param->Bits.CCOB0 */
              case 1: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 1*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB1 */
              case 2: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 2*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB2 */
              case 3: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 3*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB3 */
              case 4: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 4*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB4 */
              case 5: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 5*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB5 */
              case 6: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 6*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB6 */
              case 7: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 7*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB7 */
              case 8: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 8*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB8 */
              case 9: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 9*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB9 */
              case 10: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 10*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB10 */
              case 11: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 11*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB11 */
              case 12: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 12*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB12 */
              case 13: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 13*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB13 */
              case 14: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 14*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB14 */
              case 15: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 15*/
              } /* end case */
              /* Setting member variable vcast_param->Bits.CCOB15 */
              case 16: { 
                VCAST_LONGEST_INT VCAST_TI_9_20_ti_bitfield_placeholder = (VCAST_LONGEST_INT) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break; /* end case 16*/
              } /* end case */
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            } /* end switch */ 
          }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

          break; /* end case 3*/
        } /* end case */
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      } /* end switch */ 
#ifndef VCAST_VXWORKS
#ifndef VCAST_NO_SETJMP
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
#endif /* VCAST_VXWORKS */
#endif /* VCAST_NO_SETJMP */
  }
#endif /*((defined(VCAST_NO_TYPE_SUPPORT))||(defined(VCAST_NO_UNION_SUPPORT)))*/

} /* end VCAST_TI_9_36 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_45 ( unsigned  vcast_param[0x2] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_45 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_45 ( unsigned  vcast_param[0x2] ) 
{
  {
    int VCAST_TI_9_45_array_index = 0;
    int VCAST_TI_9_45_index = 0;
    int VCAST_TI_9_45_first, VCAST_TI_9_45_last;
    int VCAST_TI_9_45_local_field = 0;
    int VCAST_TI_9_45_value_printed = 0;

    vcast_get_range_value (&VCAST_TI_9_45_first, &VCAST_TI_9_45_last);
    VCAST_TI_9_45_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_45_upper = 2;
      for (VCAST_TI_9_45_array_index=0; VCAST_TI_9_45_array_index< VCAST_TI_9_45_upper; VCAST_TI_9_45_array_index++){
        if ( (VCAST_TI_9_45_index >= VCAST_TI_9_45_first) && ( VCAST_TI_9_45_index <= VCAST_TI_9_45_last)){
          VCAST_TI_9_20 ( &(vcast_param[VCAST_TI_9_45_index]));
          VCAST_TI_9_45_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_45_local_field;
        } /* if */
        if (VCAST_TI_9_45_index >= VCAST_TI_9_45_last)
          break;
        VCAST_TI_9_45_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_45_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_45 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_46 ( unsigned  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_46 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_46 ( unsigned  **vcast_param ) 
{
  {
    int VCAST_TI_9_46_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_46_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_46_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_46_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_46_array_size*(sizeof(unsigned  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_46_array_size*(sizeof(unsigned  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_46_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_46_index = vcast_get_param();
        VCAST_TI_9_20 ( &((*vcast_param)[VCAST_TI_9_46_index]));
      }
    }
  }
} /* end VCAST_TI_9_46 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_20 ( unsigned  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_20 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_20 ( unsigned  *vcast_param ) 
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
} /* end VCAST_TI_9_20 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_4 ( unsigned char  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_4 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_4 ( unsigned char  *vcast_param ) 
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
} /* end VCAST_TI_9_4 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_47 ( unsigned long  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_47 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_47 ( unsigned long  *vcast_param ) 
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
} /* end VCAST_TI_9_47 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_48 ( unsigned char  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_48 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_48 ( unsigned char  **vcast_param ) 
{
  {
    int VCAST_TI_9_48_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_48_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_48_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_48_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_48_array_size*(sizeof(unsigned char  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_48_array_size*(sizeof(unsigned char  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_48_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        if (VCAST_FIND_INDEX() == -1 )
          VCAST_TI_STRING ( (char**)vcast_param, 0,-1);
        else {
          VCAST_TI_9_48_index = vcast_get_param();
          VCAST_TI_9_4 ( &((*vcast_param)[VCAST_TI_9_48_index]));
        }
      }
    }
  }
} /* end VCAST_TI_9_48 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


#ifdef VCAST_PARADIGM_ADD_SEGMENT
#pragma new_codesegment(1)
#endif
void VCAST_TI_RANGE_DATA_9 ( void ) {
#define VCAST_TI_SCALAR_TYPE "NEW_SCALAR\n"
#define VCAST_TI_ARRAY_TYPE  "NEW_ARRAY\n"
#define VCAST_TI_VECTOR_TYPE "NEW_VECTOR\n"
  /* Range Data for TI (scalar) VCAST_TI_9_20 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900010\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,(UINT_MIN / 2) + (UINT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_45 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100033\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,2);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (scalar) VCAST_TI_9_47 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900017\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,ULONG_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,(ULONG_MIN / 2) + (ULONG_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,ULONG_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (scalar) VCAST_TI_9_4 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(UCHAR_MIN / 2) + (UCHAR_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
}
/* Include the file which contains function implementations
for stub processing and value/expected user code */
#include "EEPROM_uc.c"

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
