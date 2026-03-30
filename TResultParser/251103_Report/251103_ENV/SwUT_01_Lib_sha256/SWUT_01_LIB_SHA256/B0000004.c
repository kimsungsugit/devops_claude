/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
#include "S0000002.h"
#include "S0000007.h"
#include "B4_switch.h"

#ifdef VCAST_CPP_ENVIRONMENT
vCAST_boolean vcast_initializing;
#endif

/* INSERT USER_CODE_DEPENDENCIES */
/* INSERT USER_CODE_OBJECTS */

void vCAST_INITIALIZE_PARAMETERS(void) {
  } /* INITIALIZE_PARAMETERS */

void vCAST_USER_CODE_INITIALIZE (int vcast_slot_index)
   {
     /* INSERT USER_CODE_INITIALIZE */;
     vCAST_USER_CODE( VCAST_UCT_VALUE, vcast_slot_index );

   } /* end vCAST_USER_CODE_INITIALIZE */

#ifdef VCAST_ENABLE_TIMER_USER_CODE
void vCAST_USER_CODE_TIMER_START (void)
{
   /* BEGIN USER_CODE_TIMER_START */
   /* DONE USER_CODE_TIMER_START */

}

void vCAST_USER_CODE_TIMER_STOP (void)
{
   /* BEGIN USER_CODE_TIMER_STOP */
   /* DONE USER_CODE_TIMER_STOP */
}
#endif

void vCAST_USER_CODE_CAPTURE (void)
   {

   /*
   This procedure should be used as defined
   in the CCAST User Guide to capture
   any test-specific results after the
   test case is executed. 
   */

   /* insert any calls to fprintf to write data
      e.g. vectorcast_fprint_string ( vcast_user_file, "My Value:");
      e.g. vectorcast_fprint_integer( vcast_user_file, P009_001_001 );
      e.g. vectorcast_fprint_string ( vcast_user_file, "\n");
   */

   /* INSERT USER_CODE_CAPTURE */
     vCAST_USER_CODE( VCAST_UCT_EXPECTED, 0 );

   } /* end CAPTURE */

void vCAST_USER_CODE_CAPTURE_GLOBALS (void)
   {

     vCAST_USER_CODE( VCAST_UCT_EXPECTED_GLOBALS, 0 );

   } /* end CAPTURE */


void vCAST_ONE_SHOT_INIT(void)
{


   /*
    * This procedure is executed first during
    * an execution and should be used for any
    * initialization that may be necessary.
    */

   /* INSERT USER_CODE_ONE_SHOT_INIT */

}

void vCAST_ONE_SHOT_TERM(void)
{
   /*
    * This procedure is executed last during
    * execution and should be used for any
    * processing that may be necessary here.
    */
   /* INSERT USER_CODE_ONE_SHOT_TERM */

}

void vCAST_GLOBAL_STUB_PROCESSING(void) {
   /* INSERT USER_CODE_STUB_PROCESSING */

   /* INSERT STUB_EXIT_USER_CODE */
}

void vCAST_GLOBAL_BEGINNING_OF_STUB_PROCESSING(void) {
   /* INSERT STUB_ENTRY_USER_CODE */
}

void vCAST_USER_CODE( VCAST_USER_CODE_TYPE uct, int vcast_slot_index ) {
   vcast_B4_switch( 0, uct, vcast_slot_index ); /* call for all units */
}

