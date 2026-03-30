/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
/*
---------------------------------------------
-- Copyright 2020 Vector Informatik, GmbH. --
---------------------------------------------
*/
/* ------------------------------------------------------------------------
   This file has been created to simplify the S3 file, it should contain
   stuff that is used in HOST only mode or in both HOST and TARGET mode.
-------------------------------------------------------------------------*/


#ifndef VCAST_NO_SIGNAL
#include <signal.h>
#endif


/* This function is used for both host and targets --------------------------- */ 
static void commonTerminationProcessing (int status, int eventCode) {
  
  if (vCAST_DO_DATA_IF) {   /* we are doing type (DATA_IF) processing */
     vectorcast_fclose(vCAST_OUTPUT_FILE);
     vCAST_WRITE_END_FILE();
     }
  
  else {   /* this is a real test ... */
  
      /* We don't use calls to vCAST_SET_HISTORY because this can cause recursion 
         By default, we close the HIST file after each event and then open in 
         append mode for the next event.  So we have to call RE_OPEN here.
      */
      vCAST_RE_OPEN_HIST_FILE();
      if (eventCode > 0) {
          vectorcast_fprint_integer (vCAST_THISTORY_FILE, eventCode);
          vectorcast_fprint_string  (vCAST_THISTORY_FILE, ",1\n");
          vectorcast_fprint_string_with_cr ( VCAST_EXP_FILE, "-- Event" );
      }      
      vectorcast_fprint_string (vCAST_THISTORY_FILE, "0,0\n");
      vectorcast_fprint_string_with_cr ( VCAST_EXP_FILE, "-- Event" );
      /* if the source code being tested called exit() */
      if (eventCode == 1008) {
          vCAST_STORE_GLOBAL_ASCII_DATA ();
      }
      vectorcast_fclose(vCAST_ORDER_FILE);

#ifndef VCAST_DUMP_COVERAGE_AT_EXIT
     VCAST_DUMP_COVERAGE_DATA();
#endif /* VCAST_DUMP_COVERAGE_AT_EXIT */    

     /* Exit Codes of 4,5 and 6 are malloc errors, so just exit */
     if (status >= 4 && status <= 6) {
         vectorcast_write_to_std_out ("Harness Memory Error: skipping normal termination processing!\n");
         vectorcast_write_to_std_out ("VCAST is Done!\n");
         } 
     else {
        vCAST_ONE_SHOT_TERM(); /* Environment User Code */
        vectorcast_write_to_std_out ("VCAST is Done!\n");
        vCAST_WRITE_END_FILE();
        vcast_is_in_driver = vCAST_false;
        }
      } /* end of real test */
      vCAST_closeHarnessFiles();

} /* end of function */

/* Signal stuff is for host or targets ---------------------------------- */ 
static void setupSignalHandlers (void) {
    
#ifndef VCAST_NO_SIGNAL
#ifdef SIGSEGV
  signal ( SIGSEGV, vCAST_signal );
#endif
#ifdef SIGABRT
  signal ( SIGABRT, vCAST_signal );
#endif
#ifdef SIGBUS
  signal ( SIGBUS, vCAST_signal );
#endif
#ifdef SIGILL
  signal ( SIGILL, vCAST_signal );
#endif
#ifdef SIGFPE
  signal ( SIGFPE, vCAST_signal );
#endif
#endif

}


#if VC_PLATFORM==HOST

/* Trace Stuff is not implemented for HOST testing ---------------------- */ 
#define tracePoint1()
#define tracePoint2()
#define tracePoint3()
#define tracePoint4a()
#define tracePoint4b()
#define tracePoint5()
#define tracePoint6()


void VCAST_driver_termination(int status, int eventCode) {
   commonTerminationProcessing (status, eventCode);
}

#endif




