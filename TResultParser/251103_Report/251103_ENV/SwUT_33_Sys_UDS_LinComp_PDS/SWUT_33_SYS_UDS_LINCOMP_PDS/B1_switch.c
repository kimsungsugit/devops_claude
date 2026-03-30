void VCAST_RUN_DATA_IF_8( int, int );
void VCAST_RUN_DATA_IF_9( int, int );
void VCAST_TI_RANGE_DATA_8(void);
void VCAST_TI_RANGE_DATA_9(void);
#include "B0000001.h"
#include "S0000002.h"
void vcast_B1_switch( int VCAST_UNIT_INDEX, int VCAST_SUB_INDEX, int VCAST_PARAM_INDEX, const char *work )
{
switch( VCAST_UNIT_INDEX ) {
case 0:
  switch( VCAST_PARAM_INDEX ) {
  case 0:
    vCAST_SUBPROGRAM = (int)VCAST_PARAM_AS_LONGEST_INT();
    break;
  case 2:      /* deprecated */ 
    break;
  case 3:
    vCAST_UNIT = (int)VCAST_PARAM_AS_LONGEST_INT();
    break;
  case 4:
    vCAST_SET_TESTCASE_CONFIGURATION_OPTIONS( VCAST_SUB_INDEX, VCAST_atoi(work), 0 );
    break;
  case 5:
    vcastIsCodeBasedTest = (vCAST_boolean)VCAST_PARAM_AS_LONGEST_INT();
    break;
  case 9:
    vCAST_SET_TESTCASE_OPTIONS ( work );
    break;
  default:
    vCAST_TOOL_ERROR = vCAST_true;
    break;
  } /* switch VCAST_PARAM_INDEX */
  break; /* case 0 */
case 1: /* TI RANGE DATA */
  VCAST_TI_RANGE_DATA_8();
  VCAST_TI_RANGE_DATA_9();
  break;
case 8:
  VCAST_RUN_DATA_IF_8(VCAST_SUB_INDEX, VCAST_PARAM_INDEX);
  break;
case 9:
  VCAST_RUN_DATA_IF_9(VCAST_SUB_INDEX, VCAST_PARAM_INDEX);
  break;
case 10: /* PROTOTYPES */
  switch( VCAST_SUB_INDEX ) {
    case 0: /* Defined externs */
      switch( VCAST_PARAM_INDEX ) {
            case 1:
              /* For u8g_Lib_Sha256_Hash */
              VCAST_RUN_DATA_IF_9( 0, 18 );
              break;
            case 2:
              /* For lin_tl_rx_queue */
              VCAST_RUN_DATA_IF_9( 0, 19 );
              break;
            case 3:
              /* For u16g_SysDiag_SystemStatus */
              VCAST_RUN_DATA_IF_9( 0, 20 );
              break;
            case 4:
              /* For u16g_SysDiag_BuzzerLevelMax */
              VCAST_RUN_DATA_IF_9( 0, 21 );
              break;
            case 5:
              /* For u8g_SysDiag_MotorOverHeatActiveHold_F */
              VCAST_RUN_DATA_IF_9( 0, 22 );
              break;
            case 6:
              /* For u8g_SysEepromCtrl_SleepMode */
              VCAST_RUN_DATA_IF_9( 0, 23 );
              break;
            case 7:
              /* For u8g_SysEepromCtrl_MotorA1A2Output */
              VCAST_RUN_DATA_IF_9( 0, 24 );
              break;
            case 8:
              /* For u16g_SysOptCtrl_OverOpenDeg */
              VCAST_RUN_DATA_IF_9( 0, 25 );
              break;
            case 9:
              /* For s16g_SysOptCtrl_OverPos */
              VCAST_RUN_DATA_IF_9( 0, 26 );
              break;
            case 10:
              /* For u8g_ApiIn_MotorDirection */
              VCAST_RUN_DATA_IF_9( 0, 27 );
              break;
            case 11:
              /* For u8g_ApiIn_MotorCountSpeed */
              VCAST_RUN_DATA_IF_9( 0, 28 );
              break;
            case 12:
              /* For u8g_ApiIn_MotorRps */
              VCAST_RUN_DATA_IF_9( 0, 29 );
              break;
            case 13:
              /* For u16g_ApiIn_MotorLevel_A1 */
              VCAST_RUN_DATA_IF_9( 0, 30 );
              break;
            case 14:
              /* For u16g_ApiIn_MotorLevel_A2 */
              VCAST_RUN_DATA_IF_9( 0, 31 );
              break;
            case 15:
              /* For s16g_ApiIn_MotorCurrLvl */
              VCAST_RUN_DATA_IF_9( 0, 32 );
              break;
            case 16:
              /* For u16g_ApiIn_MotorTempLvl */
              VCAST_RUN_DATA_IF_9( 0, 33 );
              break;
            case 17:
              /* For u16g_ApiIn_HallSnsrLevel */
              VCAST_RUN_DATA_IF_9( 0, 34 );
              break;
            case 18:
              /* For u16g_ApiIn_Vsup */
              VCAST_RUN_DATA_IF_9( 0, 35 );
              break;
            case 19:
              /* For u16g_ApiIn_BandGap */
              VCAST_RUN_DATA_IF_9( 0, 36 );
              break;
            case 20:
              /* For s16g_ApiIn_MotorPosition */
              VCAST_RUN_DATA_IF_9( 0, 37 );
              break;
            case 21:
              /* For u8g_ApiOut_DoorAngle */
              VCAST_RUN_DATA_IF_9( 0, 38 );
              break;
            case 22:
              /* For u8g_ApiOut_DoorState */
              VCAST_RUN_DATA_IF_9( 0, 39 );
              break;
            case 23:
              /* For u8g_ApiOut_MotorCurrent */
              VCAST_RUN_DATA_IF_9( 0, 40 );
              break;
            case 24:
              /* For u8g_ApiOut_Vsup */
              VCAST_RUN_DATA_IF_9( 0, 41 );
              break;
            case 25:
              /* For u8g_DoorPreCtrl_MotorOverHeat_F */
              VCAST_RUN_DATA_IF_9( 0, 42 );
              break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      } /* switch */
      break;
        case 1:
          /* For g_Lib_Sha256_Nb_GetState */
          VCAST_RUN_DATA_IF_9( 53, VCAST_PARAM_INDEX );
          break;
        case 2:
          /* For ld_send_message */
          VCAST_RUN_DATA_IF_9( 54, VCAST_PARAM_INDEX );
          break;
        case 3:
          /* For u8g_SysEepromCtrl_ReadInlineData */
          VCAST_RUN_DATA_IF_9( 55, VCAST_PARAM_INDEX );
          break;
        case 4:
          /* For u8g_SysEepromCtrl_ReadDiagData */
          VCAST_RUN_DATA_IF_9( 56, VCAST_PARAM_INDEX );
          break;
        case 5:
          /* For u8g_SysEepromCtrl_ReadProdDate */
          VCAST_RUN_DATA_IF_9( 57, VCAST_PARAM_INDEX );
          break;
        case 6:
          /* For u8g_SysEepromCtrl_ReadPartNo */
          VCAST_RUN_DATA_IF_9( 58, VCAST_PARAM_INDEX );
          break;
        case 7:
          /* For u8g_SysEepromCtrl_ReadHwVer */
          VCAST_RUN_DATA_IF_9( 59, VCAST_PARAM_INDEX );
          break;
        case 8:
          /* For u8g_SysEepromCtrl_ReadDbVer */
          VCAST_RUN_DATA_IF_9( 60, VCAST_PARAM_INDEX );
          break;
        case 9:
          /* For u8g_SysEepromCtrl_ReadCrcByte */
          VCAST_RUN_DATA_IF_9( 61, VCAST_PARAM_INDEX );
          break;
        case 10:
          /* For u8g_SysEepromCtrl_ReadUdsData */
          VCAST_RUN_DATA_IF_9( 62, VCAST_PARAM_INDEX );
          break;
        case 11:
          /* For g_SysEepromCtrl_Reset */
          VCAST_RUN_DATA_IF_9( 63, VCAST_PARAM_INDEX );
          break;
        case 12:
          /* For g_SysOptionCtrl */
          VCAST_RUN_DATA_IF_9( 64, VCAST_PARAM_INDEX );
          break;
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  } /* switch */
  break; /* case 10 */
} /* switch */
} /* vcast_B1_switch */

int vCAST_ITERATION_COUNTER_SWITCH( int VCAST_UNIT_INDEX)
{
  return VCAST_UNIT_INDEX - 8;
} /* vCAST_ITERATION_COUNTER_SWITCH */
