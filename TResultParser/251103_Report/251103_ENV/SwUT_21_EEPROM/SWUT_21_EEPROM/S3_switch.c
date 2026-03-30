#include "S0000009.h"
void vcast_S3_switch( int VCAST_UNIT_INDEX, int VC_SUBPROGRAM) {
  switch( VCAST_UNIT_INDEX ) {
    case 9:
      VCAST_DRIVER_9( VC_SUBPROGRAM );
      break;
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  } /* switch */
} /* vcast_S3_switch */
#ifdef VCAST_SBF_UNITS_AVAILABLE
void vcast_initialize_sbf_flag( int VCAST_UNIT_INDEX, int VC_SUBPROGRAM ) {
  switch( VCAST_UNIT_INDEX ) {
    case 9:
      VCAST_SBF_9( VC_SUBPROGRAM );
      break;
  } /* switch */ 
} /* vcast_initialize_sbf_flag */
#endif /* VCAST_SBF_UNITS_AVAILABLE */
