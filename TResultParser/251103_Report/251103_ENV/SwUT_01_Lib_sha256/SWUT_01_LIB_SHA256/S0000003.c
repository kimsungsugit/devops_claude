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
#ifndef S0000002
#define S0000002 1
#endif
#define VCAST_DRIVER 1
#include "S0000007.h"
#include "S0000002.h"
#include "S0000009.h"
#include "S3_switch.h"
#include "c_cover.h"

/* this header has common and host only declarations */
#include "S3_extensions.h"

void vcTableBasedDriver (void);
void vcCodeBasedDriver (void);


#if VC_PLATFORM==HOST
int main (int argc, char **argv) {
#else
/* Helper functions for target testing, and conditional declarations of main () */
#include "S3_target_declarations.h"
#endif


/* some of the targets need special setup processing at the start of main() */
#if VC_PLATFORM==TARGET

#ifdef VCAST_COSMIC
/* Some versions of Cosmic refuse to run an executable if the start of main is 
   in a .h file. */
/* @near is not used for STM8 */
#ifdef VCAST_COSMIC_STM8
int main (int argc, char **argv) {
#else
@near int main (int argc, char **argv) {
#endif
#endif

#include "S3_target_initialization.h"
#endif
  
  vcastInitializeS2Data ();
  vcastInitializeB2Data ();
  vcastInitializeB1Data ();
  setupSignalHandlers ();
  
  tracePoint1 ();  /* trace *****************************/
  
  /* Initialize IO sets up the virtual stdin data in stdout mode  */
  vectorcast_initialize_io(vCAST_INST_FILE_OPEN, vCAST_INST_FILE);

  vCAST_ONE_SHOT_INIT();      /* Environment User Code */

  vcastSetHarnessOptionsFromFile(); /* Loads HARNOPTS.DAT */
  
  if (vCAST_DO_DATA_IF) {
     vcastSetTestCaseOptionsToDefault ();
     vCAST_OUTPUT_FILE = vectorcast_fopen (
       vcast_get_filename(VCAST_TEMP_DIF_DAT), "w" );
     /* Command to do DATA_IF processing */
     vCAST_RUN_DATA_IF("1.1.0.0%", vCAST_false);
  } else {
     vCAST_openHarnessFiles ();
    
     vcast_is_in_driver = vCAST_true;

     vCAST_OPEN_TESTORDR_FILE();
     
     tracePoint2 ();  /* trace *****************************/
     
     while ( vCAST_READ_NEXT_ORDER() != vCAST_false ) {  /* for each slot */

       vcastSetTestCaseOptionsToDefault();

       vcastStartOfSlot ();
              
       tracePoint3 ();  /* trace *****************************/
       
       vCAST_HIST_LIMIT = vCAST_ENV_HIST_LIMIT;
       
       /* reads key values from the C- file like: if code-based test, Unit, and Subprogram */
       vcastGetKeyTestValues ();
       VCAST_WRITE_TO_INST_FILE(vCAST_ORDER_OBJECT.testFilename);
       
       if (vcastIsCodeBasedTest)
           vcCodeBasedDriver ();
       else
           vcTableBasedDriver();
       
       vCAST_CURRENT_SLOT = vCAST_CURRENT_SLOT + 1;
       
       /* do we need this explicit close */
       vectorcast_fclose ( vCAST_E0_FILE );
       vCAST_ITERATION_COUNTER_RESET();
     } /* For this Slot */

  }

  VCAST_driver_termination(0,0);
  
/* some of the targets need special teardown processing at the end of main() */
#if VC_HARNESS==TARGET
#include "S3_target_termination.h"
#endif

}

/* -----------------------------------------------------------
   Start of Table Based Driver 
-------------------------------------------------------------*/
void vcTableBasedDriver (void) {
    
   vCAST_boolean vcIsEndOfSlot = vCAST_false;

  
   vCAST_INITIALIZE_PARAMETERS();  /* Environment User Code */
   vCAST_RESET_RANGE_VALUES();  

   tracePoint4a();  /* trace *****************************/

   vCAST_READ_COMMAND_DATA(vCAST_CURRENT_SLOT, 0, 0, vCAST_false, vCAST_false );
   vCAST_INITIALIZE_RANGE_VALUES();
   
   tracePoint4b ();  /* trace *****************************/
 
#ifdef VCAST_SBF_UNITS_AVAILABLE
       vcast_initialize_sbf_flag(vCAST_UNIT, vCAST_SUBPROGRAM);
#endif

   vCAST_OPEN_E0_FILE();

   for (vcSlotIteration=1;vcSlotIteration<=vCAST_ORDER_OBJECT.slotIterations;vcSlotIteration++) {  /* slot iteration */
   
     vcastStartOfSlotIteration ();
     
     vCAST_RANGE_COUNTER = 0;
     
     for (vcRangeIteration=0;vcRangeIteration<vcRangeIterationsForThisTest;++vcRangeIteration) {   /* range iteration */
     
        vcastStartOfRangeIteration ();
       
        ++vCAST_RANGE_COUNTER;
        vCAST_EXECUTE_RANGE_COMMANDS(vcRangeIteration);

        vCAST_USER_CODE_INITIALIZE(vCAST_CURRENT_SLOT);  /* Environment User Code */

        tracePoint5();  /* trace *****************************/

        vcast_S3_switch( vCAST_UNIT, vCAST_SUBPROGRAM);

        vCAST_USER_CODE_CAPTURE(); /* Environment User Code */

        vcIsEndOfSlot = vcastEndOfIteration (vcSlotIteration, vcRangeIteration);

        vCAST_SET_HISTORY_FLAGS ( vCAST_UNIT, vCAST_SUBPROGRAM);

        VCAST_SLOT_SEPARATOR ( vcIsEndOfSlot ); /* compound for batch */
        
        vCAST_RESET_ITERATION_COUNTERS(vCAST_MULTI_RETURN_SPANS_RANGE); 
        
     } /* for this range iteration */
     
     vCAST_RESET_ITERATION_COUNTERS(vCAST_MULTI_RETURN_SPANS_COMPOUND_ITERATIONS);
     vCAST_RANGE_COUNTER = 0;   /* sets the range values to the start */
     vCAST_RESET_LIST_VALUES(); /* sets the list back to the start */
     
   } /* For this slot iteration */

   vcResetRangeDataArray();
   
}   /* end table based driver */


void vcCodeBasedDriver (void) { }

