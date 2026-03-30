/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
/***********************************************
 * VectorCAST Unit Information
 *
 * Name: Sys_UDS_LinComp_PDS
 *
 * Path: C:/workspace/NE1AW_PORTING/Sources/SYSTEM/Sys_UDS_LinComp_PDS.c
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
#include "Sys_UDS_LinComp_PDS_inst_prefix.c"
#else
#include "Sys_UDS_LinComp_PDS_vcast_prefix.c"
#endif
#ifdef VCAST_COVERAGE
/* If coverage is enabled, include the instrumented UUT */
#include "Sys_UDS_LinComp_PDS_inst.c"
#else
/* If coverage is not enabled, include the original UUT */
#include "Sys_UDS_LinComp_PDS_vcast.c"
#endif
#ifdef VCAST_COVERAGE
#include "Sys_UDS_LinComp_PDS_inst_appendix.c"
#else
#include "Sys_UDS_LinComp_PDS_vcast_appendix.c"
#endif
#endif /* VCAST_DRIVER_ONLY */
#include "Sys_UDS_LinComp_PDS_driver_prefix.c"
#ifdef VCAST_HEADER_EXPANSION
#ifdef VCAST_COVERAGE
#include "Sys_UDS_LinComp_PDS_exp_inst_driver.c"
#else
#include "Sys_UDS_LinComp_PDS_expanded_driver.c"
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
      /* U16  u16s_Pwm2Spd_Conv(U8  u8t_PwmData) */
      vCAST_SET_HISTORY_FLAGS ( 9, 7 );
      vCAST_USER_CODE_TIMER_START();
      R_9_7 = 
      ( u16s_Pwm2Spd_Conv(
        ( P_9_7_1 ) ) );
      break; }
    case 8: {
      /* void  g_UDS_RDBI_Paser(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 8 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_RDBI_Paser( ) );
      break; }
    case 9: {
      /* void  s_UDS_RDBI_ExtractParams(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 9 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ExtractParams( ) );
      break; }
    case 10: {
      /* void  s_UDS_RDBI_ProcessDatePartInfo(U16  u16t_DidLsb) */
      vCAST_SET_HISTORY_FLAGS ( 9, 10 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessDatePartInfo(
        ( P_9_10_1 ) ) );
      break; }
    case 11: {
      /* void  s_UDS_RDBI_ProcessVersionInfo(U16  u16t_DidLsb) */
      vCAST_SET_HISTORY_FLAGS ( 9, 11 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessVersionInfo(
        ( P_9_11_1 ) ) );
      break; }
    case 12: {
      /* void  s_UDS_RDBI_ProcessSystemInfo(U16  u16t_DidLsb) */
      vCAST_SET_HISTORY_FLAGS ( 9, 12 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessSystemInfo(
        ( P_9_12_1 ) ) );
      break; }
    case 13: {
      /* void  s_UDS_RDBI_ProcessSystemStatus(U16  u16t_DidLsb) */
      vCAST_SET_HISTORY_FLAGS ( 9, 13 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessSystemStatus(
        ( P_9_13_1 ) ) );
      break; }
    case 14: {
      /* void  s_UDS_RDBI_ProdDate(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 14 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProdDate( ) );
      break; }
    case 15: {
      /* void  s_UDS_RDBI_PartNumber(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 15 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_PartNumber( ) );
      break; }
    case 16: {
      /* void  s_UDS_RDBI_SW_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 16 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Version( ) );
      break; }
    case 17: {
      /* void  s_UDS_RDBI_HW_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 17 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_HW_Version( ) );
      break; }
    case 18: {
      /* void  s_UDS_RDBI_DB_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 18 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_DB_Version( ) );
      break; }
    case 19: {
      /* void  s_UDS_RDBI_SW_Unit1_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 19 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Unit1_Version( ) );
      break; }
    case 20: {
      /* void  s_UDS_RDBI_SW_Unit1_IVD(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 20 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Unit1_IVD( ) );
      break; }
    case 21: {
      /* void  s_UDS_RDBI_StatusCheck1(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 21 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck1( ) );
      break; }
    case 22: {
      /* void  s_UDS_RDBI_StatusCheck2(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 22 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck2( ) );
      break; }
    case 23: {
      /* void  s_UDS_RDBI_StatusCheck3(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 23 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck3( ) );
      break; }
    case 24: {
      /* void  g_UDS_WDBI_Paser(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 24 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_WDBI_Paser( ) );
      break; }
    case 25: {
      /* void  s_UDS_WDBI_UserOptRecordId(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 25 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UserOptRecordId( ) );
      break; }
    case 26: {
      /* void  s_UDS_WDBI_UsOptMain(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 26 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOptMain( ) );
      break; }
    case 27: {
      /* void  s_UDS_WDBI_UsOpt_F1G(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 27 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_F1G( ) );
      break; }
    case 28: {
      /* void  s_UDS_WDBI_UsOpt_E2G_1(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 28 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_1( ) );
      break; }
    case 29: {
      /* void  s_UDS_WDBI_UsOpt_E2G_2(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 29 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2( ) );
      break; }
    case 30: {
      /* void  s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup1(U8  u8t_ServiceId) */
      vCAST_SET_HISTORY_FLAGS ( 9, 30 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup1(
        ( P_9_30_1 ) ) );
      break; }
    case 31: {
      /* void  s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup2(U8  u8t_ServiceId) */
      vCAST_SET_HISTORY_FLAGS ( 9, 31 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup2(
        ( P_9_31_1 ) ) );
      break; }
    case 32: {
      /* void  s_UDS_WDBI_UsOpt_E2G_3(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 32 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_3( ) );
      break; }
    case 33: {
      /* void  s_UDS_WDBI_ProdDate(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 33 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_ProdDate( ) );
      break; }
    case 34: {
      /* void  s_UDS_WDBI_PartNumber(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 34 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_PartNumber( ) );
      break; }
    case 35: {
      /* void  s_UDS_WDBI_HW_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 35 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_HW_Version( ) );
      break; }
    case 36: {
      /* void  s_UDS_WDBI_DB_Version(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 36 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_DB_Version( ) );
      break; }
    case 37: {
      /* void  s_UDS_WDBI_US_ReadEeprom(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 37 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ReadEeprom( ) );
      break; }
    case 38: {
      /* void  s_UDS_WDBI_US_WiteEeprom(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 38 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_WiteEeprom( ) );
      break; }
    case 39: {
      /* void  s_UDS_WDBI_US_ApplyParam(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 39 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ApplyParam( ) );
      break; }
    case 40: {
      /* void  s_UDS_WDBI_US_ClearEeprom(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 40 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ClearEeprom( ) );
      break; }
    case 41: {
      /* void  s_UDS_WDBI_US_ReadSysSts(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 41 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ReadSysSts( ) );
      break; }
    case 42: {
      /* void  s_UDS_WDBI_US_UserCtrl(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 42 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_UserCtrl( ) );
      break; }
    case 43: {
      /* void  s_UDS_WDBI_US_OpDataRead(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 43 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_OpDataRead( ) );
      break; }
    case 44: {
      /* void  s_UDS_WDBI_US_SysOpt(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 44 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_SysOpt( ) );
      break; }
    case 45: {
      /* void  s_UDS_WDBI_US_BuzzTest(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 45 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_BuzzTest( ) );
      break; }
    case 46: {
      /* void  s_UDS_WDBI_US_Reprogram(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 46 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Reprogram( ) );
      break; }
    case 47: {
      /* void  s_UDS_WDBI_US_Write_Checksum(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 47 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Write_Checksum( ) );
      break; }
    case 48: {
      /* void  s_UDS_WDBI_US_Read_Checksum(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 48 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Read_Checksum( ) );
      break; }
    case 49: {
      /* void  g_UDS_SessionCtrl(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 49 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_SessionCtrl( ) );
      break; }
    case 50: {
      /* void  s_UDS_DSC_ProgSession(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 50 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_DSC_ProgSession( ) );
      break; }
    case 51: {
      /* void  s_UDS_SendNRC22_ConditionsNotCorrect(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 51 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_SendNRC22_ConditionsNotCorrect( ) );
      break; }
    case 52: {
      /* void  g_UDS_LinComp_Reset(void) */
      vCAST_SET_HISTORY_FLAGS ( 9, 52 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_LinComp_Reset( ) );
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
    case 17: {
      SBF_9_17 = 0;
      break; }
    case 18: {
      SBF_9_18 = 0;
      break; }
    case 19: {
      SBF_9_19 = 0;
      break; }
    case 20: {
      SBF_9_20 = 0;
      break; }
    case 21: {
      SBF_9_21 = 0;
      break; }
    case 22: {
      SBF_9_22 = 0;
      break; }
    case 23: {
      SBF_9_23 = 0;
      break; }
    case 24: {
      SBF_9_24 = 0;
      break; }
    case 25: {
      SBF_9_25 = 0;
      break; }
    case 26: {
      SBF_9_26 = 0;
      break; }
    case 27: {
      SBF_9_27 = 0;
      break; }
    case 28: {
      SBF_9_28 = 0;
      break; }
    case 29: {
      SBF_9_29 = 0;
      break; }
    case 30: {
      SBF_9_30 = 0;
      break; }
    case 31: {
      SBF_9_31 = 0;
      break; }
    case 32: {
      SBF_9_32 = 0;
      break; }
    case 33: {
      SBF_9_33 = 0;
      break; }
    case 34: {
      SBF_9_34 = 0;
      break; }
    case 35: {
      SBF_9_35 = 0;
      break; }
    case 36: {
      SBF_9_36 = 0;
      break; }
    case 37: {
      SBF_9_37 = 0;
      break; }
    case 38: {
      SBF_9_38 = 0;
      break; }
    case 39: {
      SBF_9_39 = 0;
      break; }
    case 40: {
      SBF_9_40 = 0;
      break; }
    case 41: {
      SBF_9_41 = 0;
      break; }
    case 42: {
      SBF_9_42 = 0;
      break; }
    case 43: {
      SBF_9_43 = 0;
      break; }
    case 44: {
      SBF_9_44 = 0;
      break; }
    case 45: {
      SBF_9_45 = 0;
      break; }
    case 46: {
      SBF_9_46 = 0;
      break; }
    case 47: {
      SBF_9_47 = 0;
      break; }
    case 48: {
      SBF_9_48 = 0;
      break; }
    case 49: {
      SBF_9_49 = 0;
      break; }
    case 50: {
      SBF_9_50 = 0;
      break; }
    case 51: {
      SBF_9_51 = 0;
      break; }
    case 52: {
      SBF_9_52 = 0;
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
        case 18: /* for global object u8g_Lib_Sha256_Hash */
          VCAST_TI_9_1 ( u8g_Lib_Sha256_Hash);
          break;
        case 19: /* for global object lin_tl_rx_queue */
          VCAST_TI_9_3 ( &(lin_tl_rx_queue));
          break;
        case 20: /* for global object u16g_SysDiag_SystemStatus */
          VCAST_TI_9_10 ( &(u16g_SysDiag_SystemStatus));
          break;
        case 21: /* for global object u16g_SysDiag_BuzzerLevelMax */
          VCAST_TI_9_10 ( &(u16g_SysDiag_BuzzerLevelMax));
          break;
        case 22: /* for global object u8g_SysDiag_MotorOverHeatActiveHold_F */
          VCAST_TI_9_2 ( &(u8g_SysDiag_MotorOverHeatActiveHold_F));
          break;
        case 23: /* for global object u8g_SysEepromCtrl_SleepMode */
          VCAST_TI_9_2 ( &(u8g_SysEepromCtrl_SleepMode));
          break;
        case 24: /* for global object u8g_SysEepromCtrl_MotorA1A2Output */
          VCAST_TI_9_2 ( &(u8g_SysEepromCtrl_MotorA1A2Output));
          break;
        case 25: /* for global object u16g_SysOptCtrl_OverOpenDeg */
          VCAST_TI_9_10 ( &(u16g_SysOptCtrl_OverOpenDeg));
          break;
        case 26: /* for global object s16g_SysOptCtrl_OverPos */
          VCAST_TI_9_11 ( &(s16g_SysOptCtrl_OverPos));
          break;
        case 27: /* for global object u8g_ApiIn_MotorDirection */
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorDirection));
          break;
        case 28: /* for global object u8g_ApiIn_MotorCountSpeed */
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorCountSpeed));
          break;
        case 29: /* for global object u8g_ApiIn_MotorRps */
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorRps));
          break;
        case 30: /* for global object u16g_ApiIn_MotorLevel_A1 */
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorLevel_A1));
          break;
        case 31: /* for global object u16g_ApiIn_MotorLevel_A2 */
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorLevel_A2));
          break;
        case 32: /* for global object s16g_ApiIn_MotorCurrLvl */
          VCAST_TI_9_11 ( &(s16g_ApiIn_MotorCurrLvl));
          break;
        case 33: /* for global object u16g_ApiIn_MotorTempLvl */
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorTempLvl));
          break;
        case 34: /* for global object u16g_ApiIn_HallSnsrLevel */
          VCAST_TI_9_10 ( &(u16g_ApiIn_HallSnsrLevel));
          break;
        case 35: /* for global object u16g_ApiIn_Vsup */
          VCAST_TI_9_10 ( &(u16g_ApiIn_Vsup));
          break;
        case 36: /* for global object u16g_ApiIn_BandGap */
          VCAST_TI_9_10 ( &(u16g_ApiIn_BandGap));
          break;
        case 37: /* for global object s16g_ApiIn_MotorPosition */
          VCAST_TI_9_11 ( &(s16g_ApiIn_MotorPosition));
          break;
        case 38: /* for global object u8g_ApiOut_DoorAngle */
          VCAST_TI_9_2 ( &(u8g_ApiOut_DoorAngle));
          break;
        case 39: /* for global object u8g_ApiOut_DoorState */
          VCAST_TI_9_2 ( &(u8g_ApiOut_DoorState));
          break;
        case 40: /* for global object u8g_ApiOut_MotorCurrent */
          VCAST_TI_9_2 ( &(u8g_ApiOut_MotorCurrent));
          break;
        case 41: /* for global object u8g_ApiOut_Vsup */
          VCAST_TI_9_2 ( &(u8g_ApiOut_Vsup));
          break;
        case 42: /* for global object u8g_DoorPreCtrl_MotorOverHeat_F */
          VCAST_TI_9_2 ( &(u8g_DoorPreCtrl_MotorOverHeat_F));
          break;
        case 1: /* for global object u8g_SysUds_UsDoorCtrl */
          VCAST_TI_9_2 ( &(u8g_SysUds_UsDoorCtrl));
          break;
        case 2: /* for global object u8g_SysUds_UsAutoOpenEn_F */
          VCAST_TI_9_2 ( &(u8g_SysUds_UsAutoOpenEn_F));
          break;
        case 3: /* for global object u8g_SysUds_UsDir */
          VCAST_TI_9_2 ( &(u8g_SysUds_UsDir));
          break;
        case 4: /* for global object u8g_SysUds_UsStepMsb */
          VCAST_TI_9_2 ( &(u8g_SysUds_UsStepMsb));
          break;
        case 5: /* for global object u8g_SysUds_UsStepLsb */
          VCAST_TI_9_2 ( &(u8g_SysUds_UsStepLsb));
          break;
        case 6: /* for global object u8g_SysUds_WdbiCmd */
          VCAST_TI_9_2 ( &(u8g_SysUds_WdbiCmd));
          break;
        case 7: /* for global object u8g_SysUds_BuzzerTest_F */
          VCAST_TI_9_2 ( &(u8g_SysUds_BuzzerTest_F));
          break;
        case 8: /* for global object u8g_SysUds_WriteData */
          VCAST_TI_9_12 ( u8g_SysUds_WriteData);
          break;
        case 9: /* for global object u16g_SysUds_UsMotorPwm */
          VCAST_TI_9_10 ( &(u16g_SysUds_UsMotorPwm));
          break;
        case 10: /* for global object u16g_SysUds_UsStep */
          VCAST_TI_9_10 ( &(u16g_SysUds_UsStep));
          break;
        case 11: /* for global object u8s_UdsSid */
          VCAST_TI_9_2 ( &(u8s_UdsSid));
          break;
        case 12: /* for global object u8s_DidMsb */
          VCAST_TI_9_2 ( &(u8s_DidMsb));
          break;
        case 13: /* for global object u8s_DidLsb */
          VCAST_TI_9_2 ( &(u8s_DidLsb));
          break;
        case 14: /* for global object u8s_SwIntVer */
          VCAST_TI_9_2 ( &(u8s_SwIntVer));
          break;
        case 15: /* for global object u8s_DataBuffer */
          VCAST_TI_9_13 ( u8s_DataBuffer);
          break;
        case 16: /* for global object u8s_UserServiceIdMsb */
          VCAST_TI_9_2 ( &(u8s_UserServiceIdMsb));
          break;
        case 17: /* for global object u8s_UserServiceIdLsb */
          VCAST_TI_9_2 ( &(u8s_UserServiceIdLsb));
          break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      } /* switch( VCAST_PARAM_INDEX ) */
      break; /* case 0 (global objects) */
    case 1: /* function g_Lib_u8bit_ArrayClear */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_14 ( &(P_9_1_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_1_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_1_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_1 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_u8bit_ArrayClear */
    case 2: /* function g_Lib_u16bit_ArrayClear */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_15 ( &(P_9_2_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_9_2_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_2_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_2 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_u16bit_ArrayClear */
    case 3: /* function u8g_Lib_u8bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_3_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_3_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_3_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_3));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_3 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_u8bit_RangeCheck */
    case 4: /* function u8g_Lib_u16bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_4_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_9_4_2));
          break;
        case 3:
          VCAST_TI_9_10 ( &(P_9_4_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_4));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_4 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_u16bit_RangeCheck */
    case 5: /* function u8g_Lib_s16bit_RangeCheck */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_11 ( &(P_9_5_1));
          break;
        case 2:
          VCAST_TI_9_11 ( &(P_9_5_2));
          break;
        case 3:
          VCAST_TI_9_11 ( &(P_9_5_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_5));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_5 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_Lib_s16bit_RangeCheck */
    case 53: /* function g_Lib_Sha256_Nb_GetState */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_16 ( &(R_10_1));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_Lib_Sha256_Nb_GetState */
    case 54: /* function ld_send_message */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_5 ( &(P_10_2_1));
          break;
        case 2:
          VCAST_TI_9_14 ( &(P_10_2_2));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function ld_send_message */
    case 55: /* function u8g_SysEepromCtrl_ReadInlineData */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_3_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_3));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadInlineData */
    case 56: /* function u8g_SysEepromCtrl_ReadDiagData */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_4_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_4));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadDiagData */
    case 57: /* function u8g_SysEepromCtrl_ReadProdDate */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_5_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_5));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadProdDate */
    case 58: /* function u8g_SysEepromCtrl_ReadPartNo */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_6_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_6));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadPartNo */
    case 59: /* function u8g_SysEepromCtrl_ReadHwVer */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_7_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_7));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadHwVer */
    case 60: /* function u8g_SysEepromCtrl_ReadDbVer */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_8_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_8));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadDbVer */
    case 61: /* function u8g_SysEepromCtrl_ReadCrcByte */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_9_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_9));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadCrcByte */
    case 62: /* function u8g_SysEepromCtrl_ReadUdsData */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_10_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_10_10_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(R_10_10));
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u8g_SysEepromCtrl_ReadUdsData */
    case 6: /* function u16g_Conv_AngleToPulse */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_6_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(R_9_6));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_6 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u16g_Conv_AngleToPulse */
    case 7: /* function u16s_Pwm2Spd_Conv */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_7_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(R_9_7));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_7 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function u16s_Pwm2Spd_Conv */
    case 8: /* function g_UDS_RDBI_Paser */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_8 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_UDS_RDBI_Paser */
    case 9: /* function s_UDS_RDBI_ExtractParams */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_9 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ExtractParams */
    case 10: /* function s_UDS_RDBI_ProcessDatePartInfo */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_10_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_10 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ProcessDatePartInfo */
    case 11: /* function s_UDS_RDBI_ProcessVersionInfo */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_11_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_11 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ProcessVersionInfo */
    case 12: /* function s_UDS_RDBI_ProcessSystemInfo */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_12_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_12 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ProcessSystemInfo */
    case 13: /* function s_UDS_RDBI_ProcessSystemStatus */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_13_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_13 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ProcessSystemStatus */
    case 14: /* function s_UDS_RDBI_ProdDate */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_14 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_ProdDate */
    case 15: /* function s_UDS_RDBI_PartNumber */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_15 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_PartNumber */
    case 16: /* function s_UDS_RDBI_SW_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_16 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_SW_Version */
    case 17: /* function s_UDS_RDBI_HW_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_17 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_HW_Version */
    case 18: /* function s_UDS_RDBI_DB_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_18 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_DB_Version */
    case 19: /* function s_UDS_RDBI_SW_Unit1_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_19 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_SW_Unit1_Version */
    case 20: /* function s_UDS_RDBI_SW_Unit1_IVD */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_20 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_SW_Unit1_IVD */
    case 21: /* function s_UDS_RDBI_StatusCheck1 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_21 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_StatusCheck1 */
    case 22: /* function s_UDS_RDBI_StatusCheck2 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_22 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_StatusCheck2 */
    case 23: /* function s_UDS_RDBI_StatusCheck3 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_23 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_RDBI_StatusCheck3 */
    case 24: /* function g_UDS_WDBI_Paser */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_24 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_UDS_WDBI_Paser */
    case 25: /* function s_UDS_WDBI_UserOptRecordId */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_25 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UserOptRecordId */
    case 26: /* function s_UDS_WDBI_UsOptMain */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_26 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOptMain */
    case 27: /* function s_UDS_WDBI_UsOpt_F1G */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_27 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_F1G */
    case 28: /* function s_UDS_WDBI_UsOpt_E2G_1 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_28 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_E2G_1 */
    case 29: /* function s_UDS_WDBI_UsOpt_E2G_2 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_29 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_E2G_2 */
    case 30: /* function s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup1 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_30_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_30 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup1 */
    case 31: /* function s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup2 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_31_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_31 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup2 */
    case 32: /* function s_UDS_WDBI_UsOpt_E2G_3 */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_32 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_UsOpt_E2G_3 */
    case 33: /* function s_UDS_WDBI_ProdDate */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_33 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_ProdDate */
    case 34: /* function s_UDS_WDBI_PartNumber */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_34 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_PartNumber */
    case 35: /* function s_UDS_WDBI_HW_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_35 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_HW_Version */
    case 36: /* function s_UDS_WDBI_DB_Version */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_36 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_DB_Version */
    case 37: /* function s_UDS_WDBI_US_ReadEeprom */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_37 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_ReadEeprom */
    case 38: /* function s_UDS_WDBI_US_WiteEeprom */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_38 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_WiteEeprom */
    case 39: /* function s_UDS_WDBI_US_ApplyParam */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_39 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_ApplyParam */
    case 40: /* function s_UDS_WDBI_US_ClearEeprom */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_40 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_ClearEeprom */
    case 41: /* function s_UDS_WDBI_US_ReadSysSts */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_41 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_ReadSysSts */
    case 42: /* function s_UDS_WDBI_US_UserCtrl */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_42 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_UserCtrl */
    case 43: /* function s_UDS_WDBI_US_OpDataRead */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_43 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_OpDataRead */
    case 44: /* function s_UDS_WDBI_US_SysOpt */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_44 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_SysOpt */
    case 45: /* function s_UDS_WDBI_US_BuzzTest */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_45 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_BuzzTest */
    case 46: /* function s_UDS_WDBI_US_Reprogram */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_46 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_Reprogram */
    case 47: /* function s_UDS_WDBI_US_Write_Checksum */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_47 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_Write_Checksum */
    case 48: /* function s_UDS_WDBI_US_Read_Checksum */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_48 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_WDBI_US_Read_Checksum */
    case 49: /* function g_UDS_SessionCtrl */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_49 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_UDS_SessionCtrl */
    case 50: /* function s_UDS_DSC_ProgSession */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_50 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_DSC_ProgSession */
    case 51: /* function s_UDS_SendNRC22_ConditionsNotCorrect */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_51 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function s_UDS_SendNRC22_ConditionsNotCorrect */
    case 52: /* function g_UDS_LinComp_Reset */
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_52 );
          break;
      } /* switch ( VCAST_PARAM_INDEX ) */
      break; /* function g_UDS_LinComp_Reset */
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  } /* switch ( VCAST_SUB_INDEX ) */
}


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_1 ( unsigned char  vcast_param[(U8 )32U] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_1 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_1 ( unsigned char  vcast_param[(U8 )32U] ) 
{
  {
    int VCAST_TI_9_1_array_index = 0;
    int VCAST_TI_9_1_index = 0;
    int VCAST_TI_9_1_first, VCAST_TI_9_1_last;
    int VCAST_TI_9_1_local_field = 0;
    int VCAST_TI_9_1_value_printed = 0;
    int VCAST_TI_9_1_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_1_first, &VCAST_TI_9_1_last);
    VCAST_TI_9_1_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_1_upper = 32;
      for (VCAST_TI_9_1_array_index=0; VCAST_TI_9_1_array_index< VCAST_TI_9_1_upper; VCAST_TI_9_1_array_index++){
        if ( (VCAST_TI_9_1_index >= VCAST_TI_9_1_first) && ( VCAST_TI_9_1_index <= VCAST_TI_9_1_last)){
          if ( VCAST_TI_9_1_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_1_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_1_index]));
          VCAST_TI_9_1_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_1_local_field;
        } /* if */
        if (VCAST_TI_9_1_index >= VCAST_TI_9_1_last)
          break;
        VCAST_TI_9_1_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_1_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_1 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_3 ( lin_transport_layer_queue  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_3 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_3 ( lin_transport_layer_queue  *vcast_param ) 
{
#if (defined(VCAST_NO_TYPE_SUPPORT))
  /* User code: type is not supported */
  vcast_not_supported();
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
  {
    switch ( vcast_get_param () ) { /* Choose field member */
      /* Setting member variable vcast_param->queue_header */
      case 1: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_header));
        break; /* end case 1*/
      } /* end case */
      /* Setting member variable vcast_param->queue_tail */
      case 2: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_tail));
        break; /* end case 2*/
      } /* end case */
      /* Setting member variable vcast_param->queue_status */
      case 3: { 
        VCAST_TI_9_6 ( &(vcast_param->queue_status));
        break; /* end case 3*/
      } /* end case */
      /* Setting member variable vcast_param->queue_current_size */
      case 4: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_current_size));
        break; /* end case 4*/
      } /* end case */
      /* Setting member variable vcast_param->queue_max_size */
      case 5: { 
        /* User code: Unsupported type qualifier */
        vcast_not_supported();
        break; /* end case 5*/
      } /* end case */
      /* Setting member variable vcast_param->tl_pdu */
      case 6: { 
        VCAST_TI_9_8 ( &(vcast_param->tl_pdu));
        break; /* end case 6*/
      } /* end case */
      default:
        vCAST_TOOL_ERROR = vCAST_true;
    } /* end switch */ 
  }
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

} /* end VCAST_TI_9_3 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_10 ( unsigned  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_10 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_10 ( unsigned  *vcast_param ) 
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
} /* end VCAST_TI_9_10 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_2 ( unsigned char  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_2 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_2 ( unsigned char  *vcast_param ) 
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
} /* end VCAST_TI_9_2 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_11 ( signed int  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_11 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_11 ( signed int  *vcast_param ) 
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
} /* end VCAST_TI_9_11 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_12 ( unsigned char  vcast_param[10] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_12 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_12 ( unsigned char  vcast_param[10] ) 
{
  {
    int VCAST_TI_9_12_array_index = 0;
    int VCAST_TI_9_12_index = 0;
    int VCAST_TI_9_12_first, VCAST_TI_9_12_last;
    int VCAST_TI_9_12_local_field = 0;
    int VCAST_TI_9_12_value_printed = 0;
    int VCAST_TI_9_12_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_12_first, &VCAST_TI_9_12_last);
    VCAST_TI_9_12_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_12_upper = 10;
      for (VCAST_TI_9_12_array_index=0; VCAST_TI_9_12_array_index< VCAST_TI_9_12_upper; VCAST_TI_9_12_array_index++){
        if ( (VCAST_TI_9_12_index >= VCAST_TI_9_12_first) && ( VCAST_TI_9_12_index <= VCAST_TI_9_12_last)){
          if ( VCAST_TI_9_12_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_12_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_12_index]));
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


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_13 ( unsigned char  vcast_param[60] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_13 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_13 ( unsigned char  vcast_param[60] ) 
{
  {
    int VCAST_TI_9_13_array_index = 0;
    int VCAST_TI_9_13_index = 0;
    int VCAST_TI_9_13_first, VCAST_TI_9_13_last;
    int VCAST_TI_9_13_local_field = 0;
    int VCAST_TI_9_13_value_printed = 0;
    int VCAST_TI_9_13_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_13_first, &VCAST_TI_9_13_last);
    VCAST_TI_9_13_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_13_upper = 60;
      for (VCAST_TI_9_13_array_index=0; VCAST_TI_9_13_array_index< VCAST_TI_9_13_upper; VCAST_TI_9_13_array_index++){
        if ( (VCAST_TI_9_13_index >= VCAST_TI_9_13_first) && ( VCAST_TI_9_13_index <= VCAST_TI_9_13_last)){
          if ( VCAST_TI_9_13_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_13_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_13_index]));
          VCAST_TI_9_13_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_13_local_field;
        } /* if */
        if (VCAST_TI_9_13_index >= VCAST_TI_9_13_last)
          break;
        VCAST_TI_9_13_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_13_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_13 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_14 ( unsigned char  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_14 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_14 ( unsigned char  **vcast_param ) 
{
  {
    int VCAST_TI_9_14_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_14_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_14_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_14_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_14_array_size*(sizeof(unsigned char  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_14_array_size*(sizeof(unsigned char  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_14_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        if (VCAST_FIND_INDEX() == -1 )
          VCAST_TI_STRING ( (char**)vcast_param, 0,-1);
        else {
          VCAST_TI_9_14_index = vcast_get_param();
          VCAST_TI_9_2 ( &((*vcast_param)[VCAST_TI_9_14_index]));
        }
      }
    }
  }
} /* end VCAST_TI_9_14 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_15 ( unsigned  **vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_15 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_15 ( unsigned  **vcast_param ) 
{
  {
    int VCAST_TI_9_15_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_15_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_15_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_15_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_15_array_size*(sizeof(unsigned  )));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_15_array_size*(sizeof(unsigned  )));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_15_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_15_index = vcast_get_param();
        VCAST_TI_9_10 ( &((*vcast_param)[VCAST_TI_9_15_index]));
      }
    }
  }
} /* end VCAST_TI_9_15 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_16 ( E_LIB_SHA256_NB_STATE  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_16 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_16 ( E_LIB_SHA256_NB_STATE  *vcast_param ) 
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

} /* end VCAST_TI_9_16 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An integer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_5 ( unsigned short  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_5 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_5 ( unsigned short  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_short(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break; /* KEEP doesn't do anything */
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned short   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = USHRT_MIN;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (USHRT_MIN / 2) + (USHRT_MAX / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = USHRT_MAX;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = USHRT_MIN;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = USHRT_MAX;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
} /* end switch */
} /* end VCAST_TI_9_5 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A typedef */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_6 ( ld_queue_status  *vcast_param ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_6 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_6 ( ld_queue_status  *vcast_param ) 
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
    *vcast_param = (ld_queue_status  )VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL:
    *vcast_param = LD_NO_DATA;
    break; /* end case vCAST_FIRST_VAL */
  case vCAST_LAST_VAL:
    *vcast_param = LD_TRANSMIT_ERROR;
    break; /* end case vCAST_LAST_VAL */
  default:
    vCAST_TOOL_ERROR = vCAST_true;
    break; /* end case default */
} /* end switch */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/

} /* end VCAST_TI_9_6 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* A pointer */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_8 ( unsigned char  (**vcast_param)[8] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_8 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_8 ( unsigned char  (**vcast_param)[8] ) 
{
  {
    int VCAST_TI_9_8_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_8_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_8_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_8_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_8_array_size*(sizeof(unsigned char  [8])));
          VCAST_memset((void*)*vcast_param, 0x0, VCAST_TI_9_8_array_size*(sizeof(unsigned char  [8])));
#ifndef VCAST_NO_MALLOC
          VCAST_Add_Allocated_Data(*VCAST_TI_9_8_memory_ptr);
#endif
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_8_index = vcast_get_param();
        VCAST_TI_9_9 ( (*vcast_param)[VCAST_TI_9_8_index]);
      }
    }
  }
} /* end VCAST_TI_9_8 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


/* An array */
#if (defined(VCAST_NO_TYPE_SUPPORT))
void VCAST_TI_9_9 ( unsigned char  vcast_param[8] ) 
{
  /* User code: type is not supported */
  vcast_not_supported();
} /* end VCAST_TI_9_9 */
#else /*(defined(VCAST_NO_TYPE_SUPPORT))*/
void VCAST_TI_9_9 ( unsigned char  vcast_param[8] ) 
{
  {
    int VCAST_TI_9_9_array_index = 0;
    int VCAST_TI_9_9_index = 0;
    int VCAST_TI_9_9_first, VCAST_TI_9_9_last;
    int VCAST_TI_9_9_local_field = 0;
    int VCAST_TI_9_9_value_printed = 0;
    int VCAST_TI_9_9_is_string = (VCAST_FIND_INDEX()==-1);

    vcast_get_range_value (&VCAST_TI_9_9_first, &VCAST_TI_9_9_last);
    VCAST_TI_9_9_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_9_upper = 8;
      for (VCAST_TI_9_9_array_index=0; VCAST_TI_9_9_array_index< VCAST_TI_9_9_upper; VCAST_TI_9_9_array_index++){
        if ( (VCAST_TI_9_9_index >= VCAST_TI_9_9_first) && ( VCAST_TI_9_9_index <= VCAST_TI_9_9_last)){
          if ( VCAST_TI_9_9_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_9_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_9_index]));
          VCAST_TI_9_9_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_9_local_field;
        } /* if */
        if (VCAST_TI_9_9_index >= VCAST_TI_9_9_last)
          break;
        VCAST_TI_9_9_index++;
      } /* loop */
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_9_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
} /* end VCAST_TI_9_9 */
#endif /*(defined(VCAST_NO_TYPE_SUPPORT))*/


#ifdef VCAST_PARADIGM_ADD_SEGMENT
#pragma new_codesegment(1)
#endif
void VCAST_TI_RANGE_DATA_9 ( void ) {
#define VCAST_TI_SCALAR_TYPE "NEW_SCALAR\n"
#define VCAST_TI_ARRAY_TYPE  "NEW_ARRAY\n"
#define VCAST_TI_VECTOR_TYPE "NEW_VECTOR\n"
  /* Range Data for TI (scalar) VCAST_TI_9_10 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900006\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,(UINT_MIN / 2) + (UINT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,UINT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_13 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100008\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,60);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (array) VCAST_TI_9_1 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,32);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (array) VCAST_TI_9_12 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100007\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,10);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  /* Range Data for TI (scalar) VCAST_TI_9_2 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900001\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(UCHAR_MIN / 2) + (UCHAR_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,UCHAR_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (scalar) VCAST_TI_9_11 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900007\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,INT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(INT_MIN / 2) + (INT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,INT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (scalar) VCAST_TI_9_5 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_SCALAR_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900003\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,USHRT_MIN );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,(USHRT_MIN / 2) + (USHRT_MAX / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,USHRT_MAX );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  /* Range Data for TI (array) VCAST_TI_9_9 */
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, VCAST_TI_ARRAY_TYPE );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100006\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,8);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
}
/* Include the file which contains function implementations
for stub processing and value/expected user code */
#include "Sys_UDS_LinComp_PDS_uc.c"

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
