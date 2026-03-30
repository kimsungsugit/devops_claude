/****************************************************************************/
/*	DoxyGen Style Format												 	*/
/****************************************************************************/
/*! 
	\file		 Ap_BuzzerCtrl_PDS.c
	\brief		 Application Buzzer Control Function
	\date		 2022/03/18
	\author		 SH Baek
	\section prod Product
				 Power Door System
	\section cpu CPU
				 NXP MC9S12ZVL
	\section doc Design Document
				 NONE
	\section rev Revision History
				 22-03-18 SH BAEK \n new create
*/
/****************************************************************************/

/*--------------------------------------------------------------------------*/
/*	Include Files. External Linkage											*/
/*--------------------------------------------------------------------------*/
#include "include_file_management.h"

/*--------------------------------------------------------------------------*/
/*	Static Macro Definition													*/
/*--------------------------------------------------------------------------*/
#define u8s_CYCLE_UNIT                  ( ( U8 )( 2U ) )
#define u8s_BUZZER_FLASHING_TWICE       ( ( U8 )( 2U * u8s_CYCLE_UNIT ) )
#define u8s_BUZZER_FLASHING_TRIPLE      ( ( U8 )( 3U * u8s_CYCLE_UNIT ) )
#define u16s_BUZZER_ON_TM               ( ( U16 )( 100U / u8g_T_MAIN ) )     /* Buzzer duty turn on time: 100ms */
#define u16s_BUZZER_OFF_TM              ( ( U16 )( 100U / u8g_T_MAIN ) )     /* Buzzer duty turn off time: 100ms */

/*--------------------------------------------------------------------------*/
/*	Global Variable Declaration												*/
/*--------------------------------------------------------------------------*/
enum en_g_BuzzerCtrl g_BuzzerCtrl_BuzzerOperation;
U8 u8g_BuzzerCtrl_State;
U8 u8g_BuzzerCtrl_BuzzerCtrl;
U16 u16g_BuzzerCtrl_BuzzerDuty;

/*--------------------------------------------------------------------------*/
/*	Local Variable Declaration												*/
/*--------------------------------------------------------------------------*/
static enum
{
    en_s_Buzzer_Stop            = 0x01U,
    en_s_Buzzer_2_Flashing      = 0x02U,
    en_s_Buzzer_3_Flashing      = 0x03U

}   s_BuzzerState;

static U8 u8s_BuzzerActCnt;        /* Count up every 100ms */
static U8 u8s_BuzzerOnTimer;
static U8 u8s_BuzzerOffTimer;
static U8 u8s_BuzzerStsChg_F;
static U16 u16s_BuzzerOnTm;
static U16 u16s_BuzzerOffTm;

/*--------------------------------------------------------------------------*/
/*	Function Prototype Declaration									        */
/*--------------------------------------------------------------------------*/
static void s_BuzzerStateCtrl( void );
static void s_BuzzerStateStop( void );
static void s_BuzzerStateFlashing_Twice( void );
static void s_BuzzerStateFlashing_Triple( void );
static void s_BuzzerOnOffCtrl( void );
static void s_BuzzerCtrl_On( void );
static void s_BuzzerCtrl_Off( void );
static void s_BuzzerTimerCtrl( void );

/****************************************************************************
* Function  | Executes the buzzer control main function.
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
void g_Ap_BuzzerCtrl_Func( void )
{
    s_BuzzerTimerCtrl( );
    s_BuzzerStateCtrl( );
    
	return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerStateCtrl( void )
{
    switch( s_BuzzerState )
	{
        case en_s_Buzzer_Stop:
            s_BuzzerStateStop( );
            break;        
        case en_s_Buzzer_2_Flashing:
            s_BuzzerStateFlashing_Twice( );
            break;
        case en_s_Buzzer_3_Flashing:
            s_BuzzerStateFlashing_Triple( );
            break;

        default:
            s_BuzzerState = en_s_Buzzer_Stop;
            break;
	}

    u8g_BuzzerCtrl_State = ( U8 )s_BuzzerState;
    
	return;
}

/****************************************************************************
* Function  | #4: Obstacle Detection
              #5: Enforced Closing
              #6: Error Detection
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerStateStop( void )
{
    if( ( ( u8g_Ap_AntiPinchState_Old != u8g_DoorPreCtrl_AntiPinchSts )
      &&  ( u8g_DoorPreCtrl_AntiPinchSts == u8g_DR_PRE_ANTIPINCH_CLOSE_DETECED ) )
    ||  ( ( u8g_ApiIn_LinRx_LatchState == u8g_LATCH_CLOSED )
      &&  ( u8g_DoorCtrl_DoorState == u8g_DR_STS_UNKNOWN )
      &&  ( u8g_DoorPreCtrl_FullLatchMv_F == u8g_ON )
      &&  ( u8g_DoorPreCtrl_FullLatchMv_F_Old != u8g_DoorPreCtrl_FullLatchMv_F ) )
    ||  ( ( ( ( u8g_DoorPreCtrl_PlayProtectLvl ==  u8g_DR_PRE_PP_ACTIVATED )
           && ( u8g_DoorPreCtrl_PlayProtectLvl != u8g_DoorPreCtrl_PlayProtectLvl ) )
     // ||  ( ( E2E_mismatch == 1U ) && ( E2E_mismatchOld != E2E_mismatch ) )
        ||  ( ( ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_BATT_LOW ) == u16g_DIAG_ERR_STS_BATT_LOW )
            ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_BATT_HIGH ) == u16g_DIAG_ERR_STS_BATT_HIGH )
            ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_HALLPOWER ) == u16g_DIAG_ERR_STS_HALLPOWER )
            ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_ENCODER ) == u16g_DIAG_ERR_STS_ENCODER ) ) ) )
      &&  ( ( ( g_DoorState == ST_AUTO_STOP ) 
          &&  ( u8g_DoorCtrl_DoorState_old == ( U8 )ST_AUTO_CLOSE ) )
        ||  ( ( ( g_DoorState == ST_AUTO_STOP )
            ||  ( g_DoorState == ST_FULL_CLOSE ) )
          &&  ( u8g_Ap_LinRx_MovementReq_Old == u8g_MOVEMENTREQ_IDLE ) 
          &&  ( u8g_ApiIn_LinRx_MovementReq != u8g_MOVEMENTREQ_IDLE ) ) ) ) )
    {
        s_BuzzerState = en_s_Buzzer_3_Flashing;
    }
    else
    {
        if( ( u8g_ApiIn_LinRx_USM_DRBuzzerOpt == u8g_BUZZER_ENABLED )
        &&  ( u16g_SysEepromCtrl_AutoOperationBuzzerActMode == u8g_ON ) )
        {
            if( ( ( u8g_Ap_LinRx_MovementReq_Old != u8g_MOVEMENTREQ_CLOSING )
              &&  ( u8g_ApiIn_LinRx_MovementReq == u8g_MOVEMENTREQ_CLOSING ) )
            ||  ( ( u8g_Ap_DoorState_Old != u8g_DR_STS_MOVG_IN_TIP2RUN )
              &&  ( u8g_DoorCtrl_DoorState == u8g_DR_STS_MOVG_IN_TIP2RUN ) ) )
            {
                s_BuzzerState = en_s_Buzzer_2_Flashing;
            }
        }
    }

    if( u8g_SysUds_BuzzerTest_F == u8g_ON )
    {
        u8g_SysUds_BuzzerTest_F = u8g_OFF;
        s_BuzzerState = en_s_Buzzer_3_Flashing;
    }

    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerStateFlashing_Twice( void )
{
    if( ( u8s_BuzzerStsChg_F == u8g_ON )
    &&  ( u16s_BuzzerOffTm == u16s_BUZZER_OFF_TM ) )
    {
        u8s_BuzzerStsChg_F = u8g_OFF;
        u8s_BuzzerOnTimer = u8g_OFF;
        u8s_BuzzerOffTimer = u8g_OFF;
        u8s_BuzzerActCnt = u8g_CLR;
        s_BuzzerState = en_s_Buzzer_3_Flashing;            
    }    
    else if( u8s_BuzzerActCnt < u8s_BUZZER_FLASHING_TWICE )
    {
        s_BuzzerOnOffCtrl( );
        
        if( ( ( u8g_Ap_AntiPinchState_Old != u8g_DoorPreCtrl_AntiPinchSts )
          &&  ( u8g_DoorPreCtrl_AntiPinchSts == u8g_DR_PRE_ANTIPINCH_CLOSE_DETECED ) )
        ||  ( ( u8g_ApiIn_LinRx_LatchState == u8g_LATCH_CLOSED )
          &&  ( u8g_DoorCtrl_DoorState == u8g_DR_STS_UNKNOWN )
          &&  ( u8g_DoorPreCtrl_FullLatchMv_F == u8g_ON )
          &&  ( u8g_DoorPreCtrl_FullLatchMv_F_Old != u8g_DoorPreCtrl_FullLatchMv_F ) )
        ||  ( ( ( ( u8g_DoorPreCtrl_PlayProtectLvl ==  u8g_DR_PRE_PP_ACTIVATED )
               && ( u8g_DoorPreCtrl_PlayProtectLvl != u8g_DoorPreCtrl_PlayProtectLvl ) )
        // ||  ( ( E2E_mismatch == 1U ) && ( E2E_mismatchOld != E2E_mismatch ) )
            ||  ( ( ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_BATT_LOW ) == u16g_DIAG_ERR_STS_BATT_LOW )
                ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_BATT_HIGH ) == u16g_DIAG_ERR_STS_BATT_HIGH )
                ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_HALLPOWER ) == u16g_DIAG_ERR_STS_HALLPOWER )
                ||  ( ( u16g_SysDiag_SystemStatus &u16g_DIAG_ERR_STS_ENCODER ) == u16g_DIAG_ERR_STS_ENCODER ) ) ) )
          &&  ( ( ( g_DoorState == ST_AUTO_STOP ) 
              &&  ( u8g_DoorCtrl_DoorState_old == ( U8 )ST_AUTO_CLOSE ) )
            ||  ( ( ( g_DoorState == ST_AUTO_STOP )
                ||  ( g_DoorState == ST_FULL_CLOSE ) )
              &&  ( u8g_Ap_LinRx_MovementReq_Old == u8g_MOVEMENTREQ_IDLE ) 
              &&  ( u8g_ApiIn_LinRx_MovementReq != u8g_MOVEMENTREQ_IDLE ) ) ) ) )
        {
            u8s_BuzzerStsChg_F = u8g_ON;
        }
    }
    else
    {
        u8s_BuzzerOnTimer = u8g_OFF;
        u8s_BuzzerOffTimer = u8g_OFF;
        u8s_BuzzerActCnt = u8g_CLR;
        s_BuzzerState = en_s_Buzzer_Stop;
    }

    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerStateFlashing_Triple( void )
{
    if( ( u8s_BuzzerStsChg_F == u8g_ON )
    &&  ( u16s_BuzzerOffTm == u16s_BUZZER_OFF_TM ) )
    {
        u8s_BuzzerStsChg_F = u8g_OFF;
        u8s_BuzzerOnTimer = u8g_OFF;
        u8s_BuzzerOffTimer = u8g_OFF;
        u8s_BuzzerActCnt = u8g_CLR;
        s_BuzzerState = en_s_Buzzer_2_Flashing;
    }
    else if( u8s_BuzzerActCnt < u8s_BUZZER_FLASHING_TRIPLE )
    {
        s_BuzzerOnOffCtrl( );

        if( ( u8g_ApiIn_LinRx_USM_DRBuzzerOpt == u8g_BUZZER_ENABLED )
        &&  ( u16g_SysEepromCtrl_AutoOperationBuzzerActMode == u8g_ON ) )
        {
            if( ( ( u8g_Ap_LinRx_MovementReq_Old != u8g_MOVEMENTREQ_CLOSING )
                &&  ( u8g_ApiIn_LinRx_MovementReq == u8g_MOVEMENTREQ_CLOSING ) )
            ||  ( ( u8g_Ap_DoorState_Old != u8g_DR_STS_MOVG_IN_TIP2RUN )
                &&  ( u8g_DoorCtrl_DoorState == u8g_DR_STS_MOVG_IN_TIP2RUN ) ) )
            {
                u8s_BuzzerStsChg_F = u8g_ON;
            }
        }
    }
    else
    {
        u8s_BuzzerOnTimer = u8g_OFF;
        u8s_BuzzerOffTimer = u8g_OFF;
        u8s_BuzzerActCnt = u8g_CLR;
        s_BuzzerState = en_s_Buzzer_Stop;
    }

    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerOnOffCtrl( void )
{
    switch( g_BuzzerCtrl_BuzzerOperation )
	{      
	case en_g_Buzzer_Off:
    	s_BuzzerCtrl_Off( );
		break;
	case en_g_Buzzer_On:
		s_BuzzerCtrl_On( );
		break;          
	default:
		g_BuzzerCtrl_BuzzerOperation = en_g_Buzzer_Off;
		break;
	}

    if( g_BuzzerCtrl_BuzzerOperation == en_g_Buzzer_On )
    {
        u16g_BuzzerCtrl_BuzzerDuty = u16g_BUZZ_DUTY_SET;
        u8g_BuzzerCtrl_BuzzerCtrl = u8g_ON;
    }
	else
	{
		u16g_BuzzerCtrl_BuzzerDuty = u16g_BUZZ_DUTY_CLR;
    	u8g_BuzzerCtrl_BuzzerCtrl = u8g_OFF;
	}

	return;    
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerCtrl_Off( void )
{
    if( u16s_BuzzerOffTm < u16s_BUZZER_OFF_TM )
    {
        u8s_BuzzerOffTimer = u8g_ON;
    }
    else
    {
        u8s_BuzzerActCnt++;
        u8s_BuzzerOffTimer = u8g_OFF;
        g_BuzzerCtrl_BuzzerOperation = en_g_Buzzer_On;        
    }

    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerCtrl_On( void )
{
    if( u16s_BuzzerOnTm < u16s_BUZZER_ON_TM )
    {
        u8s_BuzzerOnTimer = u8g_ON;
    }
    else
    {
        u8s_BuzzerActCnt++;
        u8s_BuzzerOnTimer = u8g_OFF;
        g_BuzzerCtrl_BuzzerOperation = en_g_Buzzer_Off;         
    }
    
    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
static void s_BuzzerTimerCtrl( void )
{
    if( u8s_BuzzerOnTimer == u8g_ON )
    {
        u16s_BuzzerOnTm++;
    }
    else
    {
        u16s_BuzzerOnTm = u16g_CLR;
    }

    if( u8s_BuzzerOffTimer == u8g_ON )
    {
        u16s_BuzzerOffTm++;
    }
    else
    {
        u16s_BuzzerOffTm = u16g_CLR;
    }

    return;
}

/****************************************************************************
* Function  | 
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
U8 u8g_BuzzerStateReturn( void )
{
    U8 u8t_Temp;

    u8t_Temp = (U8)s_BuzzerState;

	return( u8t_Temp );
}

/****************************************************************************
* Function  | Executes the buzzer control function reset.
*----------------------------------------------------------------------------
* Parameter | Nothing
* Return    | Nothing
****************************************************************************/
void g_Ap_BuzzerCtrl_Reset( void )
{
    g_BuzzerCtrl_BuzzerOperation = en_g_Buzzer_Off;
    u8g_BuzzerCtrl_State = ( U8 )en_s_Buzzer_Stop;
    u8g_BuzzerCtrl_BuzzerCtrl = u8g_OFF;
    u16g_BuzzerCtrl_BuzzerDuty = u16g_BUZZ_DUTY_CLR;

    s_BuzzerState = en_s_Buzzer_Stop;    
    u8s_BuzzerActCnt = u8g_CLR;
    u8s_BuzzerOnTimer = u8g_OFF;
    u8s_BuzzerOffTimer = u8g_OFF;
    u8s_BuzzerStsChg_F = u8g_OFF;
    u16s_BuzzerOnTm = u16g_CLR;
    u16s_BuzzerOffTm = u16g_CLR;

	return;
}

/* End of File */
