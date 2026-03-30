/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/

/*
---------------------------------------------
-- Copyright 2019 Vector Informatik, GmbH. --
---------------------------------------------
*/



/* define configuration bits for pic24 target  */
#ifdef VCAST_PIC24_LMCO_TGT
  /* Flash Configuration Word 1 */
  __set_config_word(0x2ABFE, 0x3F7F);
  /* Flash Configuration Word 2  */
  __set_config_word(0x2ABFC, 0x12CC);
  /* Flash Configuration Word 3  */
  __set_config_word(0x2ABFA, 0xFFFF);
#endif


/*************************************************************************************/
/* This initializes the target for program execution on NEC v850 (but not 3378/3359) */
/* Init_Clock() and Init_Batt_Data_Set() may be required by your program             */
/* If it is, simply uncomment these lines                                            */
/*************************************************************************************/
#ifdef VCAST_NEC_V850
  _rcopy(&_S_romp, -1);
  __asm("di");    /* disable interrupt */
  reset_flag = RESF;
  /*Init_Clock();
    Init_Batt_Data_Set();*/
#endif


#ifdef VCAST_NO_EXIT
#ifndef VCAST_NO_SETJMP
  int jmp_exit_status = setjmp(jmp_exit);
  if( jmp_exit_status  != 0 ) {
    #ifndef VCAST_MAIN_NO_ARGS
       return ( jmp_exit_status );
    #else
       return;
    #endif
  }
#endif
#endif

#ifdef GRUNDIG_C51_TGT
  DisableWatchdog();
#endif

#ifdef VCAST_PARADIGM
  HwTimerAlarmmStop(); /* stop timer 2 for ease of debugging */
PARADIGM_BEGIN:  
  SerialPortBegin();

#endif

#ifdef VCAST_PARADIGM_SC520
   /* serial port initialization for the Paradigm 586-Drive */
   sc_init();
   c1 = &ser1_com;
   s1_init(baud,ser1_in_buf,MAXISIZE,ser1_out_buf,MAXOSIZE,c1);
#endif
#if defined(VCAST_KEIL) && !defined(__cplusplus)
  vcast_keil_setup();
#endif

#ifdef VCAST_INTEGRITY
  if (&INDRTConnected && !INDRTConnected)
      HaltTask(CurrentTask());
#endif



  /* Initialize I/O */
#if defined (__HC12__) && defined (__PRODUCT_HICROSS_PLUS__)
  TERMIO_Init();
#ifdef VCAST_CW_HC12_SIM
  TERM_Direct(TERM_TO_BOTH, "VCAST_STDOUT.DAT");
#endif
#endif


/* by default, we shut off the buffering of stdout when we are in TRACE mode */
#if defined (VCAST_TEST_HARNESS_TRACE) && !defined (VCAST_NO_STD_FILES)
  /* This call will force the stdout to be unbuffered, this will get rid
  of the need to ever flush stdout, and more importantly means that calls
  to printf will not need any heap.  Which is important to be able
  to log malloc errors!  We only do this in the TRACE case since 
  never buffering might slow down test execution in the general case. */
  setbuf (stdout, VCAST_NULL);
#elif defined (VCAST_STDOUT_BUFFER_OFF)
  setbuf (stdout, VCAST_NULL);
#endif


  /* Startup all profiling processing */
  vcastStartProfiling();

