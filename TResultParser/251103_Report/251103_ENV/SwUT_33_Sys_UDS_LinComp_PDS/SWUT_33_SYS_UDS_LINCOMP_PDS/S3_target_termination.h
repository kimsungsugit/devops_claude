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
#if defined (VCAST_PARADIGM)
  return;
#elif defined(VCAST_PARADIGM_SC520) && defined(__cplusplus)
  return;
#elif defined (VCAST_NEC_V850)
  return;
#elif defined (VCAST_THREADX)
  return;
#elif defined (VCAST_MAIN_NO_ARGS)
  return;
#else
  return(0);
#endif