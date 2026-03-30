/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
#include "S0000007.h"
#include "S0000002.h"

#ifndef VCAST_NO_LIMITS
#include <limits.h>
#ifndef VCAST_NO_FLOAT
#include <float.h>
#endif
#endif
#ifndef LONG_MAX
#define LONG_MAX 2147483647L
#endif
#include "c_cover_io.c"

#ifdef VCAST_PARADIGM
extern void dprintf (char *format,...);
void            SerialPortEnd(void);
#endif

#ifdef VCAST_PARADIGM_SC520

#ifdef __cplusplus
extern "C" {
#endif 

#include "586.h"
#include "ser1.h"

#ifdef __cplusplus
}
#endif 

extern COM ser1_com;
#endif

#define sizeOfEventFlagObject 6
static char eventFlagObject [sizeOfEventFlagObject];

void vcastStartOfSlot (void) {
   eventFlagObject[0] = 'S'; 
}

void vcastStartOfSlotIteration (void) {
   eventFlagObject[1] = 'I'; 
   eventFlagObject[2] = ' '; 

}
   
void vcastStartOfRangeIteration (void) {
   if ( vCAST_HAS_RANGE == vCAST_true ) {
       eventFlagObject[2] = 'R';
   }
   /* these characters are used for 'N' and 'P' */
   eventFlagObject[3] = ' ';
   eventFlagObject[4] = ' ';
}


#ifdef VCAST_CODE_BASED_TESTS_ALLOWED

/* For code-based, we track the monitored variables and expected values 
   that the user defines as part of the code-based test CBT.
   The E-*.DAT files have the expected values, and the E0*.DAT files have
   the values that are captured by the harness for each slot.
   
   Since we only support CBT for C++ we could use a C++ vector here
   if we wanted this to be more flexible for now!
*/

 
/* This is used for code-based test temporary storage */
#ifndef VC_MAX_CBT_LIST_SIZE
#define VC_MAX_CBT_LIST_SIZE 200
#endif

/* Storage for E0000001.DAT file data, one per slot*/
char   vc_E0_FILE_COMMANDS[VC_MAX_CBT_LIST_SIZE][VCAST_MAX_STRING_LENGTH];
int    vc_E0_FILE_LENGTH = 0;
/* Storage for E-0000001.DAT file data, one per test case */
char   vc_E_DASH_FILE_COMMANDS[VC_MAX_CBT_LIST_SIZE][VCAST_MAX_STRING_LENGTH];
int    vc_E_DASH_FILE_LENGTH = 0;
/* Storage for C-.DAT file data */
char   vc_C_DASH_FILE_COMMANDS[VC_MAX_CBT_LIST_SIZE][VCAST_MAX_STRING_LENGTH];
int    vc_C_DASH_FILE_LENGTH = 0;

#endif



/* Since we call SET_HISTORY after each call to the UUT, we need
   to figure out if we are at the end of a range iteration, or the
   end of a slot iteration, because we put out different flags 
*/
vCAST_boolean vcastEndOfIteration (int slotIteration, int rangeIteration) {
    
    vCAST_boolean endOfSlot = vCAST_false;
           
    eventFlagObject [0] = ' ';
    eventFlagObject [1] = ' ';
    /* end of range iteration output 'i' */
    if ( rangeIteration >= vcRangeIterationsForThisTest-1 ) {
       eventFlagObject [1] = 'i';
       /* end of slot output 's' */
       if ( slotIteration >= vCAST_ORDER_OBJECT.slotIterations ) {
          eventFlagObject [0] = 's';
          endOfSlot = vCAST_true;
       }
    }
          
    /* unconditionally set r */
    eventFlagObject[2]='r';
    
    return endOfSlot;
}        
     
         

/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0
void vCAST_GET_RANGE_OR_LIST_VAL(char *command, struct vcRangeDataType *rd, int position);
#endif

static void vcast_get_position (const char *vcast_command, int pos, char *vdata)
{
   int vc_numPos = 0;
   int vc_begin = 0;
   int vc_cur;

   for (vc_cur = 0; vcast_command[vc_cur] != '\0'; ++vc_cur) {
      if (vcast_command[vc_cur] == '.' || vcast_command[vc_cur] == '%') {
         if (vc_numPos == pos) {
            int vc_ncur;
            /* volatile added to work-around an optimization bug in TI CC 4.1 
               see FB case: 27789 for more info */
            volatile int vc_count = 0;
            for (vc_ncur = vc_begin; vc_ncur != vc_cur; ++vc_ncur) {
               vdata[vc_count++] = vcast_command[vc_ncur];
            }
            vdata[vc_count] = '\0';
            break;
         }

         vc_numPos++;
         vc_begin = vc_cur+1;
      }
   }
}



int
vcast_get_hc_id (char *vcast_command)
{
   char vc_hc[VCAST_LARGEST_COMMAND_FIELD];
   vcast_get_position (vcast_command, 0, vc_hc);
   return VCAST_atoi (vc_hc);
}

void
vcast_get_unit_id_str (char *vcast_command, char *vcast_unit)
{
   vcast_get_position (vcast_command, 1, vcast_unit);
}

int
vcast_get_unit_id (char *vcast_command)
{
   char vc_unit[VCAST_LARGEST_COMMAND_FIELD];
   vcast_get_position (vcast_command, 1, vc_unit);
   return VCAST_atoi (vc_unit);
}

void
vcast_get_subprogram_id_str (char *vcast_command, char *vcast_subprogram)
{
   vcast_get_position (vcast_command, 2, vcast_subprogram);
}

int
vcast_get_subprogram_id (char *vcast_command)
{
   char vc_subprogram[VCAST_LARGEST_COMMAND_FIELD];
   vcast_get_position (vcast_command, 2, vc_subprogram);
   return VCAST_atoi (vc_subprogram);
}

void
vcast_get_parameter_id_str (char *vcast_command, char *vcast_subprogram)
{
   vcast_get_position (vcast_command, 3, vcast_subprogram);
}

int
vcast_get_parameter_id (char *vcast_command)
{
   char vc_parameter[VCAST_LARGEST_COMMAND_FIELD];
   vcast_get_position (vcast_command, 3, vc_parameter);
   return VCAST_atoi (vc_parameter);
}

/* The format is
 *  0.9.1.2.0
 * where 0 represents the kind of command, it's pos is 0
 * 9 represents the unit. it's positiion is 1.
 * 1 represents the subprogram/global, it's pos is 2
 * 2 represents the parameter, it's pos is 3
 * 0 is the next level, it's pos is 4
 * Be careful calling this. It currently only handles 
 * strings of size 64.
 */
int
vcast_get_nth_parameter_id (char *vcast_command, int pos)
{
   char vc_parameter[VCAST_LARGEST_COMMAND_FIELD];
   vcast_get_position (vcast_command, pos, vc_parameter);
   return VCAST_atoi (vc_parameter);
}

/* find the start of the value part of the command, we start 
   the loop at 7 because that is the smallest that the command 
   part of 0.9.1.1% can be!    */
int vcast_get_percent_pos (const char *command) {
   int i;
   int commandLength = VCAST_strlen(command);
   int firstPercent = commandLength;

   for (i=7;i<=commandLength;i++){
      if (command[i] == '%'){
          firstPercent = i;
          break;   
      }
   }
   return firstPercent;
}

/**************************************************************************
Function: vCAST_slice
Parameters: vcast_target - destination of new string
      vcast_source - string to take a portion of
      vcast_first - first index of desired portion
      vcast_last - last index of desired portion
Description: This function takes a string source and copies a portion of
  it into the string vcast_target.
 *************************************************************************/
void vCAST_slice ( char vcast_target[], const char vcast_source[], int vcast_first, int vcast_last )
{
  int vcast_i;
  int end_of_slice = vcast_last;

  /* make sure the last index desired is not past the end of source string */
  if (VCAST_strlen(vcast_source) < vcast_last)
    end_of_slice = VCAST_strlen(vcast_source);

  /* copy the portion of the string */
  for (vcast_i=vcast_first;vcast_i<=end_of_slice;vcast_i++)
    vcast_target[vcast_i-vcast_first] = vcast_source[vcast_i];

  /* set the character after the last coped to zero to terminate the string */
  vcast_target[vcast_i-vcast_first] = 0;
}




#if !defined(VCAST_USE_STRTOLL)
/** This function converts a string to an integer **/
VCAST_LONGEST_INT VCAST_atoi ( const char *vcast_str )
{
   VCAST_LONGEST_INT ret;
   VCAST_LONGEST_INT sgn;
   int idx;

   ret = 0;
   sgn = 1;

   idx = 0;
   while ( vcast_str[idx] != 0 )
   {
     if (vcast_str[idx] == '+')
       sgn = 1;
     else if (vcast_str[idx] == '-')
       sgn = -1;
     else if ( ( vcast_str[idx] >= '0' ) && ( vcast_str[idx] <= '9' ) )
       ret = ret * 10 + vcast_str[idx] - '0';
     else if ( vcast_str[idx] != ' ' )
       break;
    idx++;
   }

   return ( ret * sgn );
}
#endif

#ifndef VCAST_USE_STRTOULL
/** This function converts a string to an unsigned integer.  It is used by 
    the harness when strtoull is not available.  It assumes that the base
    of the unsigned integer is always ten.  **/
VCAST_LONGEST_UNSIGNED VCAST_strtoul(const char *vcast_nptr, char **vcast_endptr, int vcast_base){
  VCAST_LONGEST_UNSIGNED ret = 0;
  int idx = 0;

  while ( vcast_nptr[idx] != 0 )
    {	
      if ( ( vcast_nptr[idx] >= '0' ) && ( vcast_nptr[idx] <= '9' ) )
	ret = ret * 10 + vcast_nptr[idx] - '0';
      else if ( vcast_nptr[idx] != ' ' )
	break;
      idx++;
    }

  return ( ret);
}
#endif

#ifndef VCAST_USE_STD_STRING
/** This function copies string VC_T to string VC_S */
void VCAST_strcpy ( char *VC_S, const char *VC_T )
{
  vectorcast_strcpy(VC_S, VC_T);
}

void VCAST_unsigned_strcpy ( unsigned char *VC_S, const unsigned char *VC_T )
{
   int vcast_i = 0;
   while ( (VC_S[vcast_i] = VC_T[vcast_i]) != 0 )
      vcast_i++;
}

/** This function compares string VC_T to string VC_S */
int VCAST_strcmp ( const char *VC_S, const char *VC_T )
{
   int vcast_i;
   for (vcast_i=0;VC_S[vcast_i]==VC_T[vcast_i];vcast_i++)
     if ( VC_S[vcast_i] == 0 )
       return 0;
   return VC_S[vcast_i] - VC_T[vcast_i];
}

void VCAST_unsigned_strcat ( unsigned char VC_S[], const unsigned char VC_T[] )
{
   int vcast_i,vc_j;
   vcast_i = vc_j = 0;
   while ( VC_S[vcast_i] != 0 )
      vcast_i++;           /* find end of VC_S */
   while ( (VC_S[vcast_i++] = VC_T[vc_j++]) != 0 ) ; /* copy VC_T */
}

/** This function compares string VC_T to string VC_S */
int VCAST_strncmp ( const char *VC_S, const char *VC_T, int VC_N )
{
   int vcast_i;
   for (vcast_i=0;VC_S[vcast_i]==VC_T[vcast_i];vcast_i++)
      {
      if ( VC_S[vcast_i] == 0 )
         return 0;
      if ( VC_N == vcast_i+1 )
         break;
      }
   return VC_S[vcast_i] - VC_T[vcast_i];
}

/* memxxx functions used when vCAST_FULL_STRINGS is turned on.  Instead of
 * using NULL termination, they take a length, and copy all data in the
 * strings, including NULLs. */

void* VCAST_memset ( void *vcast_dest, int vcast_value, int vcast_n ) {
   typedef unsigned char vcastBYTE;
   vcastBYTE *vc_d = (vcastBYTE *) vcast_dest;
   int vcast_i;

   for (vcast_i = 0; vcast_i < vcast_n; vcast_i++)
      vc_d[vcast_i] = vcast_value;

   return vcast_dest;
}

/* Compares vcast_n bytes of vcast_s1 and vcast_s2 and returns an 
 * integer less than, equal to, or greater than zero, according to 
 * whether vcast_s1 is less than, equal to, or greater than vcast_s2 
 * when taken to be unsigned characters (bytes). */
int VCAST_memcmp(const void *vcast_s1, const void *vcast_s2, int vcast_n)
{
   typedef unsigned char vcastBYTE;
   vcastBYTE *vcast_b1 = (vcastBYTE *) vcast_s1;
   vcastBYTE *vcast_b2 = (vcastBYTE *) vcast_s2;
   int vcast_i;

   for (vcast_i = 0; vcast_i < vcast_n; vcast_i++){
      if (vcast_b1[vcast_i] < vcast_b2[vcast_i])
         return -1;
      else if (vcast_b1[vcast_i] > vcast_b2[vcast_i])
         return 1;
   }

   return 0;
}

#endif /* VCAST_USE_STD_STRING */

/* Copies vcast_n bytes from vcast_source to vcast_dest.  It returns a 
   pointer to vcast_dest */
void *VCAST_memcpy(void *vcast_dest, const void *vcast_source, int vcast_n)
{
#ifdef VCAST_USE_STD_STRING
   return memcpy(vcast_dest, vcast_source, vcast_n);
#else
   typedef unsigned char vcastBYTE;
   vcastBYTE *vc_s = (vcastBYTE *) vcast_source;
   vcastBYTE *vc_d = (vcastBYTE *) vcast_dest;
   int vcast_i;

   for (vcast_i = 0; vcast_i < vcast_n; vcast_i++)
      vc_d[vcast_i] = vc_s[vcast_i];

   return vcast_dest;
#endif
}

/** This function copies string VC_T to string VC_S */
void VCAST_strncpy ( char *VC_S, char *VC_T, int VC_N )
{
#ifdef VCAST_USE_STD_STRING
   strncpy(VC_S, VC_T, VC_N);
#else
   int VC_tmp;
   for (VC_tmp = 0; VC_tmp < VC_N && (VC_S[VC_tmp] = VC_T[VC_tmp]); VC_tmp++){}
#endif
}



void VCAST_signed_strcpy ( signed char *VC_S, const signed char *VC_T )
{
   int vcast_i = 0;
   while ( (VC_S[vcast_i] = VC_T[vcast_i]) != 0 )
      vcast_i++;
}

#ifdef VCAST_NO_MALLOC

#ifdef VCAST_EVP
__DataAlign(32)
#endif
static union {
  void* vcast_align_pointer;
  vCAST_double vcast_align_double;
  char vcast_heap[VCAST_MAX_HEAP_SIZE];
} vcast_malloc_union;

static int vcast_heap_size = 0;

#ifndef VCAST_HEAP_ALIGNMENT
#ifdef VCAST_EIGHT_BYTE_ALIGNMENT
#define VCAST_HEAP_ALIGNMENT 8
#else
#define VCAST_HEAP_ALIGNMENT 4
#endif
#endif

void * VCAST_malloc( unsigned int vcast_size )
{
  char * start = VCAST_NULL;

  if( vcast_size > 0 ) {
    VCAST_LONGEST_UNSIGNED vcast_address;
    start = &vcast_malloc_union.vcast_heap[vcast_heap_size];
    vcast_address = (VCAST_LONGEST_UNSIGNED)start;

    if (vcast_address % VCAST_HEAP_ALIGNMENT) {
      vcast_heap_size += (VCAST_HEAP_ALIGNMENT - (vcast_address % VCAST_HEAP_ALIGNMENT));
      start = &vcast_malloc_union.vcast_heap[vcast_heap_size];
    }

    vcast_heap_size += vcast_size;

    if( vcast_heap_size > VCAST_MAX_HEAP_SIZE ) {
      start = VCAST_NULL;
      vectorcast_print_string( "VCAST_malloc() failed\n" );
      VCAST_driver_termination( 4, 1009 );
    }
  }

  return (void *)start;
}

void VCAST_free( void * vcast_aptr )
{
  /* nothing to do - VCAST_malloc is a naive implementation
      (when we're out of room, we're done) */
}

void VCAST_reset_vcast_heap () {
/* Since the VCAST_NO_MALLOC case "VCAST_free" does not really
   "free" memory, this can be used to reset the vcast_heap 
   Note that this IS NOT CURRENTLY USED by the VC harness
*/
  vcast_heap_size = 0;
}


#else /* VCAST_NO_MALLOC */

void * VCAST_malloc( unsigned int vcast_size )
{
  void * result;

  result = (void *)malloc( vcast_size );

  if( result == VCAST_NULL ) {
    vectorcast_print_string( "malloc() failed\n" );
    VCAST_driver_termination( 5, 1012 );
  }

  return result;

}

#endif /* VCAST_NO_MALLOC */

#ifndef VCAST_NO_EXIT
#ifdef __cplusplus
extern "C" {
#endif
void VCAST_exit (int vcast_status)
{
  VCAST_driver_termination (0, 1008);
}
#ifdef __cplusplus
}
#endif
#endif

/* Compares string vcast_tn to the currently executing test case name */
int VCAST_test_name_cmp(const char *vcast_tn)
{
   return VCAST_strcmp(vcast_tn, vCAST_ORDER_OBJECT.testName);
}


#define PACKET_INDEX_LAST 100

#ifndef VCAST_NO_FLOAT
void vCAST_SET_FLOAT_FORMAT ( int   VCAST_option,
                              int   VCAST_value,
                              int  *VCAST_width,
                              int  *VCAST_precision,
                              char *VCAST_format )
{
   char vcWork[5];
        
   if ( VCAST_option == 4 && (VCAST_value >= 0 || VCAST_value < 1000))
      *VCAST_width = VCAST_value;
   else if ( VCAST_option == 1 && (VCAST_value >= 0 || VCAST_value < 18))
      *VCAST_precision = VCAST_value;

   VCAST_strcpy ( VCAST_format, "%" );
   if ( !(*VCAST_precision) && !(*VCAST_width) ) {
      VCAST_strcat ( VCAST_format, VCAST_PRINTF_LONG_DOUBLE );

   } else if ( !(*VCAST_precision) && *VCAST_width ) {
      vcast_signed_to_string ( vcWork, *VCAST_width );
      VCAST_strcat ( VCAST_format, vcWork );
      VCAST_strcat ( VCAST_format, VCAST_PRINTF_LONG_DOUBLE );

   } else if ( *VCAST_precision && !(*VCAST_width) ) {
      char vcWork[5];
      VCAST_strcat ( VCAST_format, "." );
      vcast_signed_to_string ( vcWork, *VCAST_precision );
      VCAST_strcat ( VCAST_format, vcWork );
      VCAST_strcat ( VCAST_format, VCAST_PRINTF_LONG_DOUBLE );

   } else {
      char vcWork[5];
      vcast_signed_to_string ( vcWork, *VCAST_width );
      VCAST_strcat ( VCAST_format, vcWork );
      VCAST_strcat ( VCAST_format, "." );
      vcast_signed_to_string ( vcWork, *VCAST_precision );
      VCAST_strcat ( VCAST_format, vcWork );
      VCAST_strcat ( VCAST_format, VCAST_PRINTF_LONG_DOUBLE );
   }
}
#endif /* VCAST_NO_FLOAT */ 


/* Sets option option to be the value value.  */
void vCAST_SET_TESTCASE_CONFIGURATION_OPTIONS( int VCAST_option,
                                               int VCAST_value,
                                               int VCAST_set_default) {
   /* Current options are as follows:
    *    option: 1 is VCAST_FLOAT_PRECISION
    *            VCAST_value can be any value from 0 and 17
    *              1 -> 17 is "%.Nlg"
    *              0 is the default which is "%lg"
    *    option: 2 is vCAST_FULL_STRINGS
    *             VCAST_value can be 0 -> off or 1 -> on
    *             VCAST_value is 0 on default
    *    option: 3 is vCAST_HEX_NOTATION
    *             VCAST_value can be 0 -> off or 1 -> on
    *             VCAST_value is 0 on default
    *    option: 4 is VCAST_FLOAT_FIELD_WIDTH
    *            VCAST_value can be any number >= 0
    *            when 0, no number put in the field width location
    *            otherwise, VCAST_value will be put in the field width location
    *    option: 5 is VCAST_GLOBALS_DISPLAY
    *            Controls when data is captured for global objects
    *    option: 6 is EVENT_LIMIT
    *            per-testcase override of environment option EVENT_LIMIT
    *    option: 7 is vCAST_MULTI_RETURN_SPANS_RANGE
    *    option: 8 is vCAST_MULTI_RETURN_SPANS_TESTCASE
    *    option: 9 is vCAST_MULTI_RETURN_SPANS_ITERATIONS
    *    option: 10 is vCAST_HEX_INTEGERS
    *    option: 12 is vCAST_DO_COMBINATION
    *    option: 14 is DATA_PARTITIONS
    *    option: 19 is vCAST_PROBE_POINTS_AS_EVENTS
    */
    switch ( VCAST_option ) {
         case 4:  /* VCAST_FLOAT_FIELD_WIDTH */
         case 1:  /* VCAST_FLOAT_PRECISION */
		 
#ifndef VCAST_NO_FLOAT
            if ( VCAST_set_default ) {
               vCAST_SET_FLOAT_FORMAT ( VCAST_option,
                                        VCAST_value,
                                        &VCAST_DEFAULT_FLOAT_FIELD_WIDTH,
                                        &VCAST_DEFAULT_FLOAT_PRECISION,
                                        VCAST_DEFAULT_FLOAT_FORMAT );
			}
            else {
               vCAST_SET_FLOAT_FORMAT ( VCAST_option,
                                        VCAST_value,
                                        &VCAST_FLOAT_FIELD_WIDTH,
                                        &VCAST_FLOAT_PRECISION,
                                        VCAST_FLOAT_FORMAT );
            }
#endif
            break;
			
         case 2:  /* vCAST_FULL_STRINGS */
            if ( (VCAST_value == 0) || (VCAST_value == 1)) {
			   if ( VCAST_set_default ) 
                  VCAST_DEFAULT_FULL_STRINGS = VCAST_value;
			   else
                  vCAST_FULL_STRINGS= VCAST_value;
		    }
            break;
			
         case 3:  /* vCAST_HEX_NOTATION */
            if ( (VCAST_value == 0) || (VCAST_value == 1)) {
			   if ( VCAST_set_default ) 
                  VCAST_DEFAULT_HEX_NOTATION = VCAST_value;
			   else
                  vCAST_HEX_NOTATION= VCAST_value;
            }
            break;
			
         case 5: /* VCAST_GLOBALS_DISPLAY */
         case 11: /* VCAST_GLOBALS_DISPLAY */
            VCAST_GLOBALS_DISPLAY = VCAST_value;
            break;

         case 6: /* EVENT_LIMIT */
            vCAST_HIST_LIMIT = VCAST_value;
            break;
			
         case 7: /* MULTI_RETURN_SPANS_RANGE */
            vCAST_TESTCASE_OPTIONS[vCAST_MULTI_RETURN_SPANS_RANGE] =
                  VCAST_value == 1 ? vCAST_true : vCAST_false;
            break;
			
         case 9: /* MULTI_RETURN_SPANS_COMPOUND_ITERATIONS */
            vCAST_TESTCASE_OPTIONS[vCAST_MULTI_RETURN_SPANS_COMPOUND_ITERATIONS] =
                  VCAST_value == 1 ? vCAST_true : vCAST_false;
            break;
			
         case 12: /* Generate combination */
            if ( (VCAST_value == 0) || (VCAST_value == 1) ) {
			   if ( VCAST_set_default ) 
                  VCAST_DEFAULT_DO_COMBINATION = VCAST_value;
	           else		   
                  vCAST_DO_COMBINATION_TESTING = VCAST_value;
            }
            break;
			
         case 14: /* Data Partitions */
            if ( VCAST_value > 1 )
               vCAST_PARTITIONS = (vCAST_long_double)VCAST_value;
            break;

         case 19:  /* vCAST_PROBE_POINTS_AS_EVENTS */
            if ( (VCAST_value == 0) || (VCAST_value == 1)) {
			   if ( VCAST_set_default ) 
                  VCAST_DEFAULT_PROBE_POINTS_AS_EVENTS = VCAST_value;
			   else
                  vCAST_PROBE_POINTS_AS_EVENTS = VCAST_value;
		    }
            break;
			
         default:
            break;
		
      } /* end switch */
}

void vCAST_SET_TESTCASE_OPTIONS ( const char vcast_options[] )
{
   enum vCAST_testcase_options_type option_enum[3] = {
       vCAST_MULTI_RETURN_SPANS_RANGE,
       vCAST_MULTI_RETURN_SPANS_COMPOUND_ITERATIONS };

   int vcast_i;
   int vc_j = 0;

   for (vcast_i=VCAST_strlen(vcast_options)-1; vcast_i>=0; vcast_i--) {
      if (vcast_options[vcast_i] == '1')
         vCAST_TESTCASE_OPTIONS[option_enum[vc_j]] = vCAST_true;
      else
         vCAST_TESTCASE_OPTIONS[option_enum[vc_j]] = vCAST_false;

      vc_j++;
      if (vc_j > vCAST_testcase_options_count)
              break;
   }
}

/*************************************************************
-- The function vCAST_range takes the number of bits and
-- calculates the largest value that will fit
*************************************************************/
vCAST_double vCAST_power( short vcast_bits )
{
  vCAST_double ret = VCAST_FLOAT_ONE;
  short vcast_i;
  for (vcast_i=0;vcast_i<vcast_bits;vcast_i++)
    ret = VCAST_FLOAT_TWO * ret;
  return(ret);
}



/* Return 1 if is an integer, otherwise 0 */
vCAST_boolean vCAST_IS_INTEGER_RANGE (char *value)
{
   while (value && *value) {
     if ((*value >= '0' && *value <= '9') || *value == '-')
       value++;
     else
       return 0;
   }

   return 1;
}

/*-----------------------------------------------------------------*/
/*  Returns the correct value from Param at position POSITION.
    This will return the correct value if vcast_PARAM is a command
    formatted in either the form of a range, list or primitive.
    If you want this to work for other formats, this function
    must be edited. 
	
	This function gets called with a command that looks like:
	9.1.1.2%3, or 9.1.1.2%3%4%5%6%7, 0.9.2.1%#RANGE#1/4/1
	
	So it takes everything up to the first % and then appends the 
	correct value onto the end.  If it is a simple case, it is just
	the command, if it is a list, it has to grab the correct item
	from the list, if it is a RANGE, it has to compute the correct
	iteration.
	
*/
void vCAST_EXTRACT_DATA_FROM_COMMAND_LINE(char *vcast_buf, char VCAST_PARAM[], int VC_POSITION)
{
   int FIRST_MARK;
   int VC_J;
  
   vcast_buf[0] = '\0';

/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0
   
   {
   /* define this here, to reduce stack usage when range processing is not used */
   char slice1[VCAST_MAX_STRING_LENGTH];

       /* Find first delimeter */
       FIRST_MARK = vcast_get_percent_pos (VCAST_PARAM);

       /* slice1 now contains the parameter field of the command VCAST_PARAM */
       vCAST_slice(slice1,VCAST_PARAM,0,FIRST_MARK);

       /* traverse all range and list types */
       for (VC_J = 0;
            VC_J < VCAST_MAX_RANGE && vcRangeCommands[VC_J].rangeType != VCAST_NULL_TYPE;
            VC_J++)
       {
          /* get the object who has the same command as the one passed in */
          if(VCAST_strcmp(vcRangeCommands[VC_J].vCAST_COMMAND, slice1) == 0){
            VCAST_strcat(vcast_buf, vcRangeCommands[VC_J].vCAST_COMMAND);
            vCAST_GET_RANGE_OR_LIST_VAL(vcast_buf, &vcRangeCommands[VC_J], VC_POSITION-1);
            return;
          } /* end if-else */
       } /* end for */
   }

#endif /* VCAST_MAX_RANGE>0 */

   /* Neither range nor a list, just return the variable */
   VCAST_strcat(vcast_buf, VCAST_PARAM);
 
} /* vCAST_EXTRACT_DATA_FROM_COMMAND_LINE */



vCAST_long_double VCAST_itod ( char vcastStringParam[] )
{
   vCAST_long_double VCAST_number;
   vCAST_long_double VCAST_sign;
   int VCAST_idx;

   VCAST_number = VCAST_FLOAT_ZERO;
   VCAST_sign   = VCAST_FLOAT_ONE;
   VCAST_idx = 0;

   /* Advance past leading whitespace */
   while (vcastStringParam[VCAST_idx] == ' ')
            VCAST_idx++;

   while ( vcastStringParam[VCAST_idx] != 0 )
   {
      if (vcastStringParam[VCAST_idx] == '+')
         VCAST_sign = VCAST_FLOAT_ONE;
      else
         if (vcastStringParam[VCAST_idx] == '-')
         VCAST_sign = -(VCAST_FLOAT_ONE);

         else
            if ( ( vcastStringParam[VCAST_idx] >= '0' ) &&
                 ( vcastStringParam[VCAST_idx] <= '9' ) )
               VCAST_number = VCAST_number * 10 +
                              ( vcastStringParam[VCAST_idx] - '0' );
            else
               break;
      VCAST_idx++;
   }

   VCAST_number = ( VCAST_sign * VCAST_number );

   return VCAST_number;
}

/* This function takes the first number in string vcastStringParam and 
   returns it in vcastFloatParam. */
void vCAST_STR_TO_LONG_DOUBLE ( char vcastStringParam[], vCAST_long_double * vcastFloatParam)
{
#ifdef VCAST_NO_FLOAT
   *vcastFloatParam = (vCAST_long_double)VCAST_atoi (vcastStringParam);
#elif defined(VCAST_USE_STRTOD)
   *vcastFloatParam = strtod (vcastStringParam, NULL);
#elif defined(VCAST_USE_STRTOLD)
   *vcastFloatParam = strtold (vcastStringParam, NULL);
#else
   int VCAST_length;
   int VCAST_decimal = 0;
   int VCAST_exponent = 0;
   int VCAST_endOfNumber;
   int VCAST_endOfDecimal;
   int VCAST_i;

   char VCAST_work[VCAST_MAX_STRING_LENGTH];
   vCAST_long_double VCAST_right = VCAST_FLOAT_ZERO;

   vCAST_long_double VCAST_sign = VCAST_FLOAT_ONE;
   vCAST_long_double VCAST_retVal;

   /* look for decimal place and exponent */
   VCAST_length = VCAST_strlen(vcastStringParam);
   for (VCAST_i=0;VCAST_i<VCAST_length;VCAST_i++)
      if ( vcastStringParam[VCAST_i] == '.' )
         VCAST_decimal = VCAST_i;
      else if ( vcastStringParam[VCAST_i] == 'E' || vcastStringParam[VCAST_i] == 'e' )
         VCAST_exponent = VCAST_i;
      else if ( vcastStringParam[VCAST_i] == '-' )
        {
        if ( VCAST_exponent == 0 ) 
         VCAST_sign = -(VCAST_FLOAT_ONE);
        }
      else if (vcastStringParam[VCAST_i] == '+'){}
      else if ((vcastStringParam[VCAST_i] < '0') ||
               (vcastStringParam[VCAST_i] > '9'))
        /* if this is a list of values, stop at the list separator */
        VCAST_length = VCAST_i - 1;
   
   if ( VCAST_decimal > 0 )
      VCAST_endOfNumber = VCAST_decimal-1;
   else if ( VCAST_exponent > 0 )
      VCAST_endOfNumber = VCAST_exponent-1;
   else
      VCAST_endOfNumber = VCAST_length;

   if ( VCAST_exponent > 0 )
      VCAST_endOfDecimal = VCAST_exponent-1;
   else
      VCAST_endOfDecimal = VCAST_length;
           
   /* left of decimal */
   vCAST_slice ( VCAST_work, vcastStringParam, 0, VCAST_endOfNumber );
   VCAST_retVal = VCAST_itod ( VCAST_work );
   if ( VCAST_retVal < 0 )
      {
      VCAST_sign = -(VCAST_FLOAT_ONE);
      VCAST_retVal = VCAST_retVal * VCAST_sign;
      }

   /* right of decimal */
   if ( VCAST_decimal > 0 )
      {
      vCAST_slice ( VCAST_work, vcastStringParam, VCAST_decimal+1, VCAST_endOfDecimal );
      VCAST_right = VCAST_itod ( VCAST_work );
      for (VCAST_i=0;VCAST_i<VCAST_strlen(VCAST_work);VCAST_i++)
      VCAST_right = VCAST_right / VCAST_FLOAT_TEN;
      VCAST_retVal = VCAST_retVal + VCAST_right;
      }

   /* exponent */
   if ( VCAST_exponent > 0 )
      {
      vCAST_slice ( VCAST_work, vcastStringParam, VCAST_exponent+1, VCAST_length );
      VCAST_exponent = VCAST_atoi ( VCAST_work );
      if ( VCAST_exponent < 0 )
         for (VCAST_i=0;VCAST_i<-(VCAST_exponent);VCAST_i++)
            VCAST_retVal = VCAST_retVal / VCAST_FLOAT_TEN;
      else
         for (VCAST_i=0;VCAST_i<VCAST_exponent;VCAST_i++)
            VCAST_retVal = VCAST_retVal * VCAST_FLOAT_TEN;
      }

   *vcastFloatParam = VCAST_sign * VCAST_retVal;
#endif /* VCAST_NO_FLOAT */
}

void vCAST_DOUBLE_TO_STR(vCAST_long_double VC_F, char VC_S[], int VC_AS_INT)
{
   if (VC_AS_INT) {
     if (VC_F < 0) {
       vcast_signed_to_string(VC_S, (VCAST_SIGNED_CONVERSION_TYPE)VC_F);
     } else {
       vcast_unsigned_to_string(VC_S, (VCAST_UNSIGNED_CONVERSION_TYPE)VC_F);
     }
   } else {
     vcast_float_to_string ( VC_S, VC_F );
   }
}

void vCAST_ITERATION_COUNTER_RESET()
{
   int item_size, index2, index1, idx1, idx2, temp;
   /* initialize iteration counters */
   item_size = sizeof vCAST_ITERATION_COUNTERS[0][0];
   index2    = sizeof vCAST_ITERATION_COUNTERS[0] / item_size;
   temp      = (item_size * index2);
   index1    = sizeof vCAST_ITERATION_COUNTERS / temp;
   for (idx1=0;idx1<index1;idx1++)
      for (idx2=0;idx2<index2;idx2++)
         vCAST_ITERATION_COUNTERS[idx1][idx2] = 0;
}

void vCAST_RESET_ITERATION_COUNTERS(enum vCAST_testcase_options_type OPTION)
{
   if (!vCAST_TESTCASE_OPTIONS[OPTION])
      vCAST_ITERATION_COUNTER_RESET();
}

int vCAST_GET_ITERATION_COUNTER_VALUE(int UNIT, int SUB)
{
   int index = vCAST_ITERATION_COUNTER_SWITCH(UNIT);
   return vCAST_ITERATION_COUNTERS[index][SUB];
}

void vCAST_INCREMENT_ITERATION_COUNTER(int UNIT, int SUB)
{
   int index = vCAST_ITERATION_COUNTER_SWITCH(UNIT);
   vCAST_ITERATION_COUNTERS[index][SUB]++;
}

/*
 * vCAST_getListValue parses a data item from a list
 *     list  - pointer to value string "%1%2" (starts with %)
 *     index - item we are looking for (starts at 0)
 *     piece  - where to store the return
 */
#if VCAST_MAX_RANGE>0
void vCAST_getListValue(char *list, int index, char* piece) {
   
   int i;
   int length;
   int countIndex=-1;
   int start=0;
   int end;
   
   length = VCAST_strlen(list);

   for (i=0; i < length; i++) {
      if (list[i] == '%') {
          countIndex++;
          if (countIndex==index) {
              start = i+1;
              break;
          }
        }
      }
   
   if (countIndex==index) {
       /* if we found the start index, we just
       need to find the end, which is either the
       next % or the end of the string */
       end = length-1;
       for (i=start;i<length;i++) {
         if (list[i] == '%') {
            end=i-1;
            break;
         }
       }
   }
   else {
      /* If we ran out of values, then find the last value.
      End will be the last character in the string 
      and start will be the first % reading from the right*/
      end = length-1;
      for (i=length-1;i>=0;i--) {
          if (list[i]=='%') {
              start = i+1;
              break;
          }
      }
   }
   
   vCAST_slice (piece, list, start, end);
}

#endif /* VCAST_MAX_RANGE>0 */



/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0
void vCAST_GET_RANGE_OR_LIST_VAL(char *command, struct vcRangeDataType *rd, int position) {
  char flStr[VCAST_MAX_STRING_LENGTH];
  char list_item [VCAST_MAX_STRING_LENGTH];

  vCAST_long_double val;
  /* Did this to work around a cosmic bug */
  vCAST_long_double first_range_value = rd->vCAST_MIN;
  vCAST_long_double last_range_value = rd->vCAST_MAX;
 
  
  if(rd->rangeType == VCAST_RANGE_TYPE) {
    val = first_range_value + (rd->vCAST_INC * position);
    if (rd->vCAST_INC > 0){
      if (val > last_range_value) {
        /* possible for a stub which returns a range */
        val = last_range_value;
      }
    } else {
      if (val < last_range_value){
        val = last_range_value;
      }
    }
    vCAST_DOUBLE_TO_STR(val, flStr, rd->isInteger);
    VCAST_strcat(command, flStr);
  } else { /* VCAST_LIST_TYPE */
    vCAST_getListValue(rd->vCAST_list, position, list_item);
    VCAST_strcat (command, list_item);
  }
}
#endif /* VCAST_MAX_RANGE>0 */

/*  determines if a given command is on the UUT
    or on a global variable */
static vCAST_boolean uutOrGlobalCommand(char *vcast_command) {
   int unitId;
   int subId;
   if(vcast_command != VCAST_NULL && VCAST_strlen(vcast_command) >= 8) {
      unitId = vcast_get_unit_id(vcast_command);
      subId = vcast_get_subprogram_id(vcast_command);
      if ( subId == 0 )
        return vCAST_true;
      if ( unitId == vCAST_UNIT && subId == vCAST_SUBPROGRAM )
        return vCAST_true;
  }
  return vCAST_false;
} /* end uutOrGlobalCommand */

void vCAST_EXECUTE_RANGE_COMMANDS(int iteration)
{
/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0

  int VC_I = 0;
  int index;
  char tmpStr[VCAST_MAX_STRING_LENGTH];
  
  
  for (VC_I=0; VC_I<VCAST_MAX_RANGE; VC_I++) {
    if (vcRangeCommands[VC_I].rangeType != VCAST_NULL_TYPE) {
        if(uutOrGlobalCommand(vcRangeCommands[VC_I].vCAST_COMMAND)) {
            if (vCAST_DO_COMBINATION_TESTING) {
               index = (iteration/vcRangeCommands[VC_I].vCAST_COMBO_GROUPING) %
                          vcRangeCommands[VC_I].vCAST_NUM_VALS;
            } 
            else {
                if(iteration > vcRangeCommands[VC_I].vCAST_NUM_VALS-1) {
                    /* we have exhausted the values for this object, use the last */
                    index = vcRangeCommands[VC_I].vCAST_NUM_VALS-1;
                } 
                else {
                   index = iteration;
                }
            }
            VCAST_strcpy(tmpStr, vcRangeCommands[VC_I].vCAST_COMMAND);
            vCAST_GET_RANGE_OR_LIST_VAL(tmpStr, &vcRangeCommands[VC_I], index);
            vCAST_RUN_DATA_IF (tmpStr, vCAST_false);
        }
    }
    else {
        break;
    }
  }
  
#endif

}



void vcResetRangeDataArray(void) {

/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0
  int index;

  for(index = 0; index < VCAST_MAX_RANGE; index++)
    if(vcRangeCommands[index].rangeType == VCAST_LIST_TYPE &&
       vcRangeCommands[index].vCAST_list != VCAST_NULL) {
      VCAST_free(vcRangeCommands[index].vCAST_COMMAND);
      VCAST_free(vcRangeCommands[index].vCAST_list);
      vcRangeCommands[index].vCAST_COMMAND = VCAST_NULL;
      vcRangeCommands[index].vCAST_list = VCAST_NULL;
    } else if(vcRangeCommands[index].rangeType == VCAST_RANGE_TYPE) {
      VCAST_free(vcRangeCommands[index].vCAST_COMMAND);
      vcRangeCommands[index].vCAST_COMMAND = VCAST_NULL;
    } 
  vcRangeDataIndex=0;
#endif   /* VCAST_MAX_RANGE>0 */
      
} /* end vcResetRangeDataArray */


/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0
void vCAST_GET_RANGE_VALUES(char *vcast_S,
                            struct vcRangeDataType *vcast_range_data)
{
  int VC_I;
  int len = VCAST_strlen(vcast_S);
  char tmpStr[VCAST_MAX_STRING_LENGTH];
  int count = 0,
      index = 0;
  vCAST_boolean isInteger = 1;

  for (VC_I=0;VC_I<len;VC_I++) {
    if (vcast_S[VC_I] == '/') {
      count++;
      if (count == 1) {
        vCAST_slice(tmpStr, vcast_S, 0, VC_I-1);

        if (isInteger)
           isInteger = vCAST_IS_INTEGER_RANGE(tmpStr);

        vCAST_STR_TO_LONG_DOUBLE(tmpStr, &vcast_range_data->vCAST_MIN);
        index = VC_I+1;
      }
      else
  if (count == 2) {
    vCAST_slice(tmpStr, vcast_S, index, VC_I-1);
    if (isInteger)
       isInteger = vCAST_IS_INTEGER_RANGE(tmpStr);
    vCAST_STR_TO_LONG_DOUBLE(tmpStr, &vcast_range_data->vCAST_MAX);
    index = VC_I+1;
  }
    }
  }
  vCAST_slice(tmpStr, vcast_S, index, len-1);
  if ( VCAST_strcmp ( tmpStr, "<<PARTITION>>" ) == 0 ) {
    vcast_range_data->vCAST_INC =
          ( vcast_range_data->vCAST_MAX - vcast_range_data->vCAST_MIN ) /
          ( vCAST_PARTITIONS );
  } else {
    if (isInteger)
       isInteger = vCAST_IS_INTEGER_RANGE(tmpStr);
    vCAST_STR_TO_LONG_DOUBLE(tmpStr, &vcast_range_data->vCAST_INC);
  }

  /* If all min/max/inc were integers, use integer mode */
  /* This avoids sprintf with %f later, and uses %d instead */
  vcast_range_data->isInteger = isInteger;

  { /* calculate vCAST_NUM_VALS for RANGE */
    vCAST_long_double val = vcast_range_data->vCAST_MIN;
    if(vcast_range_data->vCAST_INC > 0) {
      while(val <= vcast_range_data->vCAST_MAX) {
        vcast_range_data->vCAST_NUM_VALS++;
        val = vcast_range_data->vCAST_MIN + (vcast_range_data->vCAST_NUM_VALS * vcast_range_data->vCAST_INC);
      }
    } else {
      while(val >= vcast_range_data->vCAST_MAX) {
        vcast_range_data->vCAST_NUM_VALS++;
        val = vcast_range_data->vCAST_MIN + (vcast_range_data->vCAST_NUM_VALS * vcast_range_data->vCAST_INC);
      }
    }
  }
}

#endif  /* VCAST_MAX_RANGE>0 */


void vCAST_RESET_LIST_VALUES(void){

/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0

  int VC_I;
  for (VC_I=0;VC_I<VCAST_MAX_RANGE;VC_I++) {
    /* there are no more Ranges or lists, this is done */
    if(vcRangeCommands[VC_I].rangeType == VCAST_NULL_TYPE){
      break;
    /* if it is a range */
    } else if(vcRangeCommands[VC_I].rangeType == VCAST_LIST_TYPE) {   /* Its a list */
    }
  }
#endif /* VCAST_MAX_RANGE>0 */
}

void vCAST_RESET_RANGE_VALUES(void)
{
/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0

  int  VC_J;
  for (VC_J=0;VC_J<VCAST_MAX_RANGE;VC_J++) {
    vcRangeCommands[VC_J].vCAST_COMMAND = VCAST_NULL;
    vcRangeCommands[VC_J].rangeType = VCAST_NULL_TYPE;
    vcRangeCommands[VC_J].vCAST_MIN = VCAST_FLOAT_ZERO;
    vcRangeCommands[VC_J].vCAST_MAX = VCAST_FLOAT_ZERO;
    vcRangeCommands[VC_J].vCAST_INC = VCAST_FLOAT_ZERO;
    vcRangeCommands[VC_J].vCAST_list = VCAST_NULL;
    vcRangeCommands[VC_J].isInteger = 0;
    vcRangeCommands[VC_J].vCAST_NUM_VALS = 0;
    vcRangeCommands[VC_J].vCAST_COMBO_GROUPING = 1;
  }
  vCAST_HAS_RANGE = vCAST_false;
#endif   /* VCAST_MAX_RANGE>0 */
}


void vcGetCommandDetails (const char* vcCommand, int* vcStartOfValue, int* vcNumberOfValues) {

   int  i;
   int  commandLength = VCAST_strlen(vcCommand);

   *vcStartOfValue = vcast_get_percent_pos(vcCommand);

   /* Check if there are additional %'s in the value string */
   *vcNumberOfValues = 1;
   for (i=*vcStartOfValue+1;i<commandLength;i++) {
      if (vcCommand [i]=='%') {
         (*vcNumberOfValues)++;
      }
   }
}


/*
This function will take a test value command, and if
the command value is a range or list command, it will
store the details into the vcRangeCommands array and return
True.  Otherwise, it will return False
*/
vCAST_boolean vcProcessCommandForRangeExpression (const char* command) {
                      

/* if range processing is disabled, no need to do this stuff!*/                     
#if VCAST_MAX_RANGE>0
                          
   char tempString [VCAST_MAX_STRING_LENGTH];
   int  commandLength = VCAST_strlen(command);
   int  startOfValue;
   int  numberOfValues;
   
   vcGetCommandDetails (command, &startOfValue, &numberOfValues);
   
   /* if the command is long enough to contain the range expression flag */
   if (commandLength > startOfValue+8){
      vCAST_slice(tempString, command, startOfValue+1, startOfValue+7);
      /* if the value part of the command starts with the range flag */
      if (VCAST_strcmp(tempString, "#RANGE#") == 0) {
          vcRangeCommands[vcRangeDataIndex].rangeType = VCAST_RANGE_TYPE;
          
          vCAST_slice(tempString, command, 0, startOfValue);
          vcRangeCommands[vcRangeDataIndex].vCAST_COMMAND =
            (char *)VCAST_malloc(sizeof(char)*VCAST_strlen(tempString) + 1);
          VCAST_strcpy( vcRangeCommands[vcRangeDataIndex].vCAST_COMMAND, tempString);
          
          vCAST_slice(tempString, command, startOfValue+8, commandLength);
          vCAST_GET_RANGE_VALUES(tempString, &vcRangeCommands[vcRangeDataIndex]);
          
          vcRangeDataIndex++;
          return vCAST_true;
      }
   }
       
   
   if (numberOfValues>1) {
       vcRangeCommands[vcRangeDataIndex].rangeType = VCAST_LIST_TYPE;
  
      vCAST_slice(tempString,command,0,startOfValue);
      vcRangeCommands[vcRangeDataIndex].vCAST_COMMAND =
         (char *)VCAST_malloc(sizeof(char)*VCAST_strlen(tempString) + 1);
      VCAST_strcpy( vcRangeCommands[vcRangeDataIndex].vCAST_COMMAND, tempString);
 
      vCAST_slice(tempString, command, startOfValue, commandLength);
      vcRangeCommands[vcRangeDataIndex].vCAST_list =
         (char *)VCAST_malloc(sizeof(char)*VCAST_strlen(tempString) + 1);
      VCAST_strcpy( vcRangeCommands[vcRangeDataIndex].vCAST_list, tempString);
      vcRangeCommands[vcRangeDataIndex].vCAST_NUM_VALS = numberOfValues;
      
      vcRangeDataIndex++;
      return vCAST_true;

   }
   
#endif /* VCAST_MAX_RANGE>0 */

   return vCAST_false;

}


/* This function is called at the start of each test to initialize
   the vcRangeCommands array with any range commands for this test 
   As the test runs, this data is used to call the DATA_IF  */
void vCAST_INITIALIZE_RANGE_VALUES(void) {

/* if range processing is disabled, no need to do this stuff!*/
#if VCAST_MAX_RANGE>0

  char fileName[VCAST_FILENAME_LENGTH];
  char param[VCAST_MAX_STRING_LENGTH];
  int  VC_F, last_num = 1, last_grouping = 1;
  int  VC_J;

  vCAST_boolean hasRange;

  vcRangeIterationsForThisTest = 1;
  vcRangeDataIndex=0;

  VCAST_strcpy(fileName, vCAST_ORDER_OBJECT.testFilename);

  VC_F = vectorcast_fopen(fileName, "r");
  while (!vectorcast_feof(VC_F)){
    vectorcast_readline(param, VC_F);
    hasRange = vcProcessCommandForRangeExpression (param);
    
    if (hasRange==vCAST_true) {
        /* This call increments the vcRangeDataIndex, so the just-added struct
           is vcRangeDataIndex-1 */
        if(uutOrGlobalCommand(vcRangeCommands[vcRangeDataIndex-1].vCAST_COMMAND)){
            vCAST_HAS_RANGE = vCAST_true;
        }
    }
    if (vcRangeDataIndex == VCAST_MAX_RANGE)
      break;
  } /* end while */
  vectorcast_fclose(VC_F);
  
  /* if there is one varied object, combination testing doesn't mean anything */
  if (vcRangeDataIndex > 1 && vCAST_DO_COMBINATION_TESTING) {
    for (VC_J=vcRangeDataIndex-1; VC_J>=0; --VC_J) {
      if (uutOrGlobalCommand(vcRangeCommands[VC_J].vCAST_COMMAND)) {
        vcRangeCommands[VC_J].vCAST_COMBO_GROUPING = last_num * last_grouping;
        last_num = vcRangeCommands[VC_J].vCAST_NUM_VALS;
        last_grouping = vcRangeCommands[VC_J].vCAST_COMBO_GROUPING;
      }
    }
    
    for (VC_J=0;VC_J<vcRangeDataIndex;++VC_J) {
      if (uutOrGlobalCommand(vcRangeCommands[VC_J].vCAST_COMMAND)) {
        vcRangeIterationsForThisTest = vcRangeIterationsForThisTest *
                                     vcRangeCommands[VC_J].vCAST_NUM_VALS;
      }
    }
  } else {
    for (VC_J=0;VC_J<vcRangeDataIndex;++VC_J) {
      if (uutOrGlobalCommand(vcRangeCommands[VC_J].vCAST_COMMAND) &&
          vcRangeCommands[VC_J].vCAST_NUM_VALS > vcRangeIterationsForThisTest) {
        vcRangeIterationsForThisTest = vcRangeCommands[VC_J].vCAST_NUM_VALS;
      }
    }
  }
  
#endif /* VCAST_MAX_RANGE>0 */
  
}


#ifdef __cplusplus
/* This handles the calls that are dynamically inserted into the harness
   to add  special characters to the event flag for 
       Null class instance pointers ('N')
       Dereferenced P objects ('P')  
   vcast wants all the flags to be contiguous (no spaces)
   so we loop from the right side of the current eventFlagObject
*/
void vCAST_APPEND_HISTORY_FLAG (char flag){
    /* start at the right, but skip the \0 */
    int i = sizeOfEventFlagObject-2;
    while (eventFlagObject[i]==' ') 
        i--;
    eventFlagObject[i+1] = flag;
}
#endif

void vCAST_CLOSE_HIST_FILE_FOR_EVENT (void);



/* For CBT tests, we have much simpler needs for 
   store_ascii_data so we use these wrappers
*/
void vCAST_STORE_GLOBAL_ASCII_DATA_CBT (void);
void vCAST_STORE_GLOBAL_ASCII_DATA_TABLE (void) {

   char VC_TEXT[VCAST_MAX_STRING_LENGTH];
   int  SUB_ID;

   if (!VCAST_GLOBAL_FIRST_EVENT || 
       (VCAST_GLOBALS_DISPLAY != vCAST_EACH_EVENT))
     vCAST_USER_CODE_CAPTURE_GLOBALS();

   vCAST_OPEN_E0_FILE();
   while (!vectorcast_feof(vCAST_E0_FILE)){
      vectorcast_readline(VC_TEXT, vCAST_E0_FILE);
      if (VCAST_strlen(VC_TEXT) > 7) {
         SUB_ID = vcast_get_subprogram_id (VC_TEXT);
         if (SUB_ID == 0) {
            vCAST_RUN_DATA_IF (VC_TEXT, vCAST_false);
         }
      }
   }
   vectorcast_fclose ( vCAST_E0_FILE );
   VCAST_GLOBAL_FIRST_EVENT = 0;
}
void vCAST_STORE_GLOBAL_ASCII_DATA (void) {
#if VCAST_CODE_BASED_TESTS_ALLOWED
    if (vcastIsCodeBasedTest==vCAST_true)
       vCAST_STORE_GLOBAL_ASCII_DATA_CBT();
    else
#endif
       vCAST_STORE_GLOBAL_ASCII_DATA_TABLE();
}


void vCAST_STORE_PARAMETER_ASCII_DATA (int UN_IT, int SUB_PROG);

void   vCAST_STORE_ASCII_DATA_CBT( int UN_IT, int SUB_PROG);
void   vCAST_STORE_ASCII_DATA_TABLE( int UN_IT, int SUB_PROG,
                                     const char* VC_EVENT_FLAGS) {
    
   /* False means to suppress data for this compound slot */
   if ( vCAST_ORDER_OBJECT.printEventData[0] != 'F' ) {
      vCAST_STORE_PARAMETER_ASCII_DATA (UN_IT, SUB_PROG);

      if ( vCAST_SHOULD_DISPLAY_GLOBALS ( UN_IT, VC_EVENT_FLAGS ) )
         vCAST_STORE_GLOBAL_ASCII_DATA ();
   }
   /* if flag indicates "don't print" we still need to handle global data */
   else if ( vCAST_SHOULD_DISPLAY_GLOBALS ( UN_IT, VC_EVENT_FLAGS ) ) {
      if (!VCAST_GLOBAL_FIRST_EVENT ||
          (VCAST_GLOBALS_DISPLAY != vCAST_EACH_EVENT))
        vCAST_USER_CODE_CAPTURE_GLOBALS();
   }
}
void   vCAST_STORE_ASCII_DATA( int UN_IT, int SUB_PROG,
                               const char* VC_EVENT_FLAGS) {
#if VCAST_CODE_BASED_TESTS_ALLOWED
    if (vcastIsCodeBasedTest==vCAST_true)
        vCAST_STORE_ASCII_DATA_CBT (UN_IT, SUB_PROG);
    else
#endif
        vCAST_STORE_ASCII_DATA_TABLE (UN_IT, SUB_PROG, VC_EVENT_FLAGS);
}




static void setHistory ( int unit, 
                         int subprogram, 
                         const char* eventFlags, 
                        const char* slotDescriptor) {
   /* Do not store the ascii data when history limit is zero. */
   if ((vCAST_HIST_LIMIT != 0) && ((unit > 0) || (subprogram > 0))) {
      if ((unit < 1000 || unit >=2000) && vCAST_HIST_INDEX <= vCAST_HIST_LIMIT)
        vCAST_STORE_ASCII_DATA (unit,subprogram, eventFlags);
   }

   /* if we are not printing slot data, don't print history data */
   if ( vCAST_ORDER_OBJECT.printEventData[0] == 'F' )
      return;

   /* If the maximum number of events has not been reached or if 
    * final event, then write the line. */
   if ((vCAST_HIST_INDEX <= vCAST_HIST_LIMIT) ||
       (unit == 0 && subprogram == 0)) {

      vCAST_RE_OPEN_HIST_FILE();
      vectorcast_fprint_integer (vCAST_THISTORY_FILE, unit);
      vectorcast_fprint_string  (vCAST_THISTORY_FILE, ",");
      vectorcast_fprint_integer (vCAST_THISTORY_FILE, subprogram);
      vectorcast_fprint_string  (vCAST_THISTORY_FILE, " ");
      vectorcast_fprint_string (vCAST_THISTORY_FILE, eventFlags);
      /* print description at beginning of every slot iteration */
      if ( eventFlags[0] && eventFlags[1] == 'I' && slotDescriptor[0] != 0 ) {
        vectorcast_fprint_string (vCAST_THISTORY_FILE, " #" );
        vectorcast_fprint_string (vCAST_THISTORY_FILE, slotDescriptor );
      }
      /* print compound for batch indicator if it's there */
      else if ( vCAST_ORDER_OBJECT.slotDescriptor[0] == 'X' )
        vectorcast_fprint_string (vCAST_THISTORY_FILE, slotDescriptor );
    
      vectorcast_fprint_string_with_cr (vCAST_THISTORY_FILE, "");
      vectorcast_fprint_string_with_cr ( VCAST_EXP_FILE, "-- Event" );

      vectorcast_fflush (vCAST_THISTORY_FILE);
      vCAST_CLOSE_HIST_FILE_FOR_EVENT ();

   } else if (vCAST_HIST_LIMIT != 0) {
      vCAST_RE_OPEN_HIST_FILE();

      vCAST_STORE_ASCII_DATA (unit,subprogram,eventFlags);
      if (VCAST_GLOBALS_DISPLAY != vCAST_EACH_EVENT){
        vCAST_STORE_GLOBAL_ASCII_DATA ();
      }
      vectorcast_fprint_integer (vCAST_THISTORY_FILE, unit);
      vectorcast_fprint_string  (vCAST_THISTORY_FILE, ",");
      vectorcast_fprint_integer (vCAST_THISTORY_FILE, subprogram);
      vectorcast_fprint_string  (vCAST_THISTORY_FILE, " ");
      vectorcast_fprint_string_with_cr (vCAST_THISTORY_FILE, eventFlags);

      vectorcast_fprint_string_with_cr ( VCAST_EXP_FILE, "-- Event" );

      /* If the history limit is not zero then record the fact that 
       * there are too many events */
      vectorcast_fprint_string (vCAST_THISTORY_FILE, "1000,888\n");
      vectorcast_fprint_string (vCAST_THISTORY_FILE, "0,0\n");

      /* and stop running the test case */
      vectorcast_fflush (vCAST_THISTORY_FILE);
      vCAST_CLOSE_HIST_FILE_FOR_EVENT ();

      vcast_is_in_driver = vCAST_false;
      VCAST_driver_termination( 0, 0 );
   }

   vCAST_HIST_INDEX = vCAST_HIST_INDEX + 1;
} /* end setHistory */

/* Normal set history adds the SIR flags at the end of the 9,1
   This call is used for the start and end of a UUT call 
*/
void vCAST_SET_HISTORY_FLAGS ( int VC_U, int VC_S) {
    setHistory (VC_U, VC_S, eventFlagObject, vCAST_ORDER_OBJECT.slotDescriptor );
}

/* All of the other events, just output the 9,1
*/
void vCAST_SET_HISTORY ( int VC_U, int VC_S) {
    setHistory (VC_U, VC_S, "", "" );
}


/* Original write_to_inst_file function.  Currently used by default when
 * coverage optimizations are turned off. */
void VCAST_WRITE_TO_INST_FILE(const char VC_S[])
{
#if !defined(VCAST_DUMP_BINARY_COVERAGE) || !defined(VCAST_COVERAGE_IO_BUFFERED)
   vCAST_CREATE_INST_FILE();
   vectorcast_fprint_string_with_cr(vCAST_INST_FILE, VC_S);
#endif
}


void vCAST_WRITE_END_FILE(void)
{
#ifdef VCAST_PARADIGM_SC520
  COM *c1;  
  c1 = &ser1_com;
#endif

   vectorcast_write_vcast_end ();
   vectorcast_terminate_io ();
   
#ifdef VCAST_PARADIGM
  /*  hit a few dummy dprintf's to flush serial data  */
  dprintf("                                                               \n");
  dprintf("                                                               \n");
  dprintf("                                                               \n");
  dprintf("                                                               \n");
  SerialPortEnd();
#endif
#ifdef VCAST_PARADIGM_SC520
  delay_ms(2000);
  s1_close(c1);
#endif

}

/* This function sets all of the harness options to their default value.
 * It is called before every new test case is run.
 */
void vcastSetTestCaseOptionsToDefault(void)
{
#ifndef VCAST_NO_FLOAT
   VCAST_strncpy(VCAST_FLOAT_FORMAT, VCAST_DEFAULT_FLOAT_FORMAT, VCAST_FLOAT_FORMAT_SIZE);
   VCAST_FLOAT_PRECISION        = VCAST_DEFAULT_FLOAT_PRECISION;
   VCAST_FLOAT_FIELD_WIDTH      = VCAST_DEFAULT_FLOAT_FIELD_WIDTH;
#endif
   vCAST_PARTITIONS          = VCAST_FLOAT_ONE;
   vCAST_FULL_STRINGS        = VCAST_DEFAULT_FULL_STRINGS;
   vCAST_HEX_NOTATION        = VCAST_DEFAULT_HEX_NOTATION;
   vCAST_PROBE_POINTS_AS_EVENTS  = VCAST_DEFAULT_PROBE_POINTS_AS_EVENTS;
   vCAST_DO_COMBINATION_TESTING = VCAST_DEFAULT_DO_COMBINATION;
   /* vCAST_DO_RANGE_DATA does not need to be reset. It should
    * persist, until the execution of the harness is done. */
}

/* This function is provided so that the harness can read in
 * options from the user with out having to recompile.
 * As of now, several options can be used.
 *
 * This function is called once on start up. It initialized global data that
 * is used to set the defaults after every test run. This is useful so that
 * file I/O does not become a bottleneck.
 */
void vcastSetHarnessOptionsFromFile (void)
{
   char VCAST_TEXT[VCAST_MAX_STRING_LENGTH];
   
   char VCAST_NUMBER[VCAST_LARGEST_COMMAND_FIELD];

   int  VCAST_UNIT_INDEX  = 0;
   int  VCAST_SUB_INDEX   = 0;   /* option to set */
   int  VCAST_PARAM_INDEX = 0;
   int  VCAST_VALUE       = 0;   /* value to set */
   int  VCAST_optsfd      = -1;

   if( (VCAST_optsfd = vectorcast_fopen("HARNOPTS.DAT", "r")) == -1)
      return; /* no HARNOPTS.DAT file, use default values */

   while (vectorcast_fgets ( VCAST_TEXT, VCAST_MAX_STRING_LENGTH, VCAST_optsfd )!=0) {
      VCAST_UNIT_INDEX = vcast_get_unit_id (VCAST_TEXT); 
      VCAST_SUB_INDEX = vcast_get_subprogram_id (VCAST_TEXT);
      VCAST_PARAM_INDEX = vcast_get_parameter_id (VCAST_TEXT);

      vCAST_slice(VCAST_NUMBER, VCAST_TEXT, vcast_get_percent_pos (VCAST_TEXT)+1, VCAST_strlen(VCAST_TEXT));
      VCAST_VALUE = VCAST_atoi( VCAST_NUMBER );

      /* found a config option */
      if(VCAST_UNIT_INDEX == 0) {
         if (VCAST_PARAM_INDEX == 4) {
            vCAST_SET_TESTCASE_CONFIGURATION_OPTIONS(VCAST_SUB_INDEX, VCAST_VALUE, 1);
            }
         else if (VCAST_PARAM_INDEX == 5) {
            vCAST_DO_DATA_IF = (int)VCAST_VALUE;
            }
      }
   }
   vectorcast_fclose(VCAST_optsfd);
}

/* Starting with version 5.1, the TESTORDR.DAT file is now formatted:
 * line 1: <event limit>
 * line 2: <testcase name>
 * line 3: <testcase datafile>
 * line 4: <number of iterations>
 * line 5: <slot description>
 * with lines 2 through N duplicated for each slot */
void vCAST_OPEN_TESTORDR_FILE (void)
{
   char VC_TEXT[VCAST_MAX_STRING_LENGTH];
   int  vc_x;

   vCAST_ORDER_FILE = vectorcast_fopen("TESTORDR.DAT", "r");

   /* read event limit */
   vectorcast_fgets ( VC_TEXT, VCAST_MAX_STRING_LENGTH, vCAST_ORDER_FILE );

   /* Some versions of atoi don't like the trailing newline */
   vc_x = VCAST_strlen(VC_TEXT);
   if (vc_x > 0 && VC_TEXT[vc_x-1] == '\n')
     VC_TEXT[vc_x-1] = '\0';

   vCAST_ENV_HIST_LIMIT = VCAST_atoi ( VC_TEXT );
}


int VCAST_READ_TESTORDR_LINE ( char vc_line[] ) {
   char VC_TEXT[VCAST_MAX_STRING_LENGTH];
   int vc_length;

   vc_line[0] = 0;
   vectorcast_readline(VC_TEXT, vCAST_ORDER_FILE);
   vc_length = VCAST_strlen(VC_TEXT);
   if ( vc_length != 0 ) {
      if ( VC_TEXT[vc_length-1] == '\n' )
        VC_TEXT[--vc_length] = '\0';
   }
   VCAST_strcpy( vc_line, VC_TEXT );
   return vc_length;
}

vCAST_boolean vCAST_READ_NEXT_ORDER (void)
{
   char VC_TEXT[VCAST_MAX_STRING_LENGTH];

   if ( vectorcast_feof ( vCAST_ORDER_FILE ) )
      return vCAST_false;

   /* TESTCASE NAME **********************/
   if ( VCAST_READ_TESTORDR_LINE ( vCAST_ORDER_OBJECT.testName ) == 0 )
      return vCAST_false;

   /* TESTCASE FILE **********************/
   if ( VCAST_READ_TESTORDR_LINE ( vCAST_ORDER_OBJECT.testFilename ) == 0 )
      return vCAST_false;
   
   /* ITERATIONS *************************/
   if ( VCAST_READ_TESTORDR_LINE ( VC_TEXT ) == 0 )
      return vCAST_false;
   vCAST_ORDER_OBJECT.slotIterations = VCAST_atoi ( VC_TEXT );

   /* SLOT_DESCRIPTION *************************/
   VCAST_READ_TESTORDR_LINE ( vCAST_ORDER_OBJECT.slotDescriptor );

   /* PRINT_DATA *************************/
   VCAST_READ_TESTORDR_LINE ( vCAST_ORDER_OBJECT.printEventData );

   return vCAST_true;
} /* end vCAST_READ_NEXT_ORDER */




#ifdef VCAST_CODE_BASED_TESTS_ALLOWED

/* This function is used only for code-based tests, to set the P or R object
   to the correct value when the user provides a list of values.  We cannot
   just use vCAST_EXTRACT_DATA_FROM_COMMAND_LINE because that relies on 
   the global vcRangeCommands data that is setup on initialization.
   
   Also, this code is more simple because we are only handling lists of
   values for code-based testing, not ranges.
*/
static void vcBuildCommandString (char* vcast_buf, const char* command, int position) {
       
   int  startOfValue;
   int  length;
   char valueString [VCAST_MAX_STRING_LENGTH];
   char list_item   [VCAST_MAX_STRING_LENGTH];
   
   length = VCAST_strlen (command);

   startOfValue = vcast_get_percent_pos (command);  
   /* clear the output buffer */
   vcast_buf[0]  = '\0';
   
   /* copy the command part, including the % */
   vCAST_slice(vcast_buf, command, 0, startOfValue);
   /* pass the value part, including the first % */
   vCAST_slice(valueString, command, startOfValue, length);

   vCAST_getListValue (valueString, position, list_item);
   VCAST_strcat (vcast_buf, list_item);
}
#else
static void vcBuildCommandString (char* vcast_buf, const char* command, int position) { }
#endif


static void processOneCommand (int unit, int sub, int param, char* command) {
    
  char    vcast_buf[VCAST_MAX_STRING_LENGTH];
  int     lineUnit, lineSub, lineParam;

  if (VCAST_strlen(command) > 7) {
     lineUnit = vcast_get_unit_id  ( command );
     lineSub   = vcast_get_subprogram_id ( command );
     lineParam = vcast_get_parameter_id ( command );

     if ((lineUnit == unit) &&
         (lineSub == sub) &&
         (lineParam == param))
     {
        if (vcastIsCodeBasedTest) {
           vcBuildCommandString (vcast_buf, command, vCAST_GET_ITERATION_COUNTER_VALUE(unit, sub));
           vCAST_RUN_DATA_IF(vcast_buf, vCAST_false);
        }
        else {
           vCAST_EXTRACT_DATA_FROM_COMMAND_LINE(
              vcast_buf, command, vCAST_GET_ITERATION_COUNTER_VALUE(unit, sub) + 1);
        }
        if(VCAST_strlen(vcast_buf) != 0) {
           vCAST_RUN_DATA_IF(vcast_buf, vCAST_false);
        }
     }
  }
}

void processCodeBasedTestCommands (int unit, int sub, int param) {
#ifdef VCAST_CODE_BASED_TESTS_ALLOWED
   int i;
   char command [VCAST_MAX_STRING_LENGTH];
   
   for (i=0;i<vc_C_DASH_FILE_LENGTH;i++) {
      VCAST_strcpy (command, vc_C_DASH_FILE_COMMANDS[i]);
      processOneCommand (unit, sub, param, command );
      }
#endif
}


void vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM (int vcUnit, int vcSub, int vcParam) {
    
   int     fileHandle;
   char    filename [VCAST_FILENAME_LENGTH]; 
   char    command  [VCAST_MAX_STRING_LENGTH];

   if (vcastIsCodeBasedTest) {
      processCodeBasedTestCommands (vcUnit, vcSub, vcParam);
      }
   else {
      VCAST_strcpy(filename, vCAST_ORDER_OBJECT.testFilename);
      fileHandle = vectorcast_fopen(filename, "r");
      while (!vectorcast_feof(fileHandle)){
         vectorcast_readline(command, fileHandle);
         processOneCommand (vcUnit, vcSub, vcParam, command );
         }
      vectorcast_fclose(fileHandle);
      }

} /* end tableBasedStubParameterProcessing*/




#ifdef VCAST_NO_TYPE_SUPPORT
/* In the no type support case, we generate code to setup the slot
   specific global variables that normally setup by the reading
   of the C-.DAT file.  For example, the global objects for
   vCAST_UNIT, and vCAST_SUBPROGRAM */
#endif 

static int SBFCommand (char* COMMAND_PARAM) {

#ifdef VCAST_SBF_UNITS_AVAILABLE
   return !VCAST_strcmp(&COMMAND_PARAM[vcast_get_percent_pos(COMMAND_PARAM)+1], "<<STUB>>");
#else
   return 0;
#endif
}



/* -----------------------------------------------------------------------------  
   This is called from the S3, B4 switch, vCAST_COMMON_STUB_PROC
*/
void vCAST_READ_COMMAND_DATA (
          int           slotIndex,
          int           unit,
          int           subProgram,
          vCAST_boolean callerIsStub,
          vCAST_boolean initializeOnly)    /* seems to only get set true by B4_switch */
{
   int     CMD_FILE;
   char    VC_FILENAME[VCAST_FILENAME_LENGTH];
   
   int     VC_LENGTH;
   
   int     HC_INDEX;
   int     UNIT_INDEX;
   int     STUB_INDEX;
   int     PARAM_INDEX;
   int     SUB_INDEX;

   char    vcast_buf[VCAST_MAX_STRING_LENGTH];
   char    COMMAND_PARAM[VCAST_MAX_STRING_LENGTH];

#ifdef VCAST_CPP_ENVIRONMENT
#ifndef VCAST_KEIL
   vcast_should_throw_exception = 0;
#endif
#endif
   if(callerIsStub){
      vCAST_INCREMENT_ITERATION_COUNTER(unit, subProgram);
      STUB_INDEX = vCAST_GET_ITERATION_COUNTER_VALUE(unit, subProgram);
   } else {
      STUB_INDEX = 1;
   } /* end if-else */

   if ( slotIndex == -1 )
      VCAST_strcpy( VC_FILENAME, "TESTDATA.DAT" );
   else
      VCAST_strcpy( VC_FILENAME, vCAST_ORDER_OBJECT.testFilename );

   CMD_FILE = vectorcast_fopen ( VC_FILENAME, "r" );

   while (!vectorcast_feof(CMD_FILE)){

      vectorcast_readline(COMMAND_PARAM, CMD_FILE);

      VC_LENGTH = VCAST_strlen(COMMAND_PARAM);
      if (VC_LENGTH > 7){
         HC_INDEX   = vcast_get_hc_id ( COMMAND_PARAM );
         UNIT_INDEX = vcast_get_unit_id( COMMAND_PARAM);
         SUB_INDEX  = vcast_get_subprogram_id ( COMMAND_PARAM );
         PARAM_INDEX = vcast_get_parameter_id ( COMMAND_PARAM );

         /* This determines if vCAST_RUN_DATA_IF is called on this command. 
         */
         if( ( !callerIsStub && (UNIT_INDEX < 7 || SBFCommand (COMMAND_PARAM) ||  uutOrGlobalCommand(COMMAND_PARAM) ) ) ||
             ( callerIsStub && UNIT_INDEX == unit && SUB_INDEX == subProgram ) ) {
             
#ifdef VCAST_CPP_ENVIRONMENT
#ifndef VCAST_KEIL
            /* only stubs may throw exceptions */
            if (callerIsStub){
               if ((!(HC_INDEX == 0 && UNIT_INDEX == 0 && SUB_INDEX == 0)) && PARAM_INDEX == 0) {
                  vcast_should_throw_exception = 1;
                  /* find the type index of the exception being thrown */
                  vcast_exception_index = vcast_get_nth_parameter_id (COMMAND_PARAM, 4);
               } /* end if */
            } /* end if called is a stub */
#endif
#endif
            vCAST_EXTRACT_DATA_FROM_COMMAND_LINE(vcast_buf, COMMAND_PARAM, STUB_INDEX);

            if (VCAST_strlen(vcast_buf) != 0)
               vCAST_RUN_DATA_IF(vcast_buf, initializeOnly);
         } /* end if need to run data if */
      } /* end if VC_LENGTH > 7 */

   } /* end while */

   vectorcast_fclose ( CMD_FILE );

} /* end vCAST_READ_COMMAND_DATA */

vCAST_boolean vCAST_SHOULD_DISPLAY_GLOBALS ( int UNIT,
                                             const char* VC_EVENT_FLAGS ) {

   vCAST_boolean retVal = vCAST_false;

   if ( ( UNIT >= 1000 && UNIT < 2000 ) || ( UNIT == 0 ) )
      retVal = vCAST_true;
   else
   {
      switch ( VCAST_GLOBALS_DISPLAY ) {
      case vCAST_EACH_EVENT:
         retVal = vCAST_true;
         break;
      case vCAST_RANGE_ITERATION:
         if ( VC_EVENT_FLAGS[2] == 'r' ) retVal = vCAST_true;
         break;
      case vCAST_SLOT_ITERATION:
         if ( VC_EVENT_FLAGS[1] == 'i' ) retVal = vCAST_true;
         break;
      case vCAST_TESTCASE:
         if ( VC_EVENT_FLAGS[0] == 's' ) retVal = vCAST_true;
         break;
      }
   }

   return retVal;
}


void vCAST_STORE_PARAMETER_ASCII_DATA (int unit, int subProgram) {

   char VC_TEXT[VCAST_MAX_STRING_LENGTH];
   int  UNIT_ID;
   int  SUB_ID;
   
   vCAST_OPEN_E0_FILE();
   vCAST_OUTPUT_FILE = vCAST_ASCIIRES_FILE;

   while (!vectorcast_feof(vCAST_E0_FILE)){
      vectorcast_readline(VC_TEXT, vCAST_E0_FILE);
      if (VCAST_strlen(VC_TEXT) > 7) {
         UNIT_ID = vcast_get_unit_id (VC_TEXT);
         SUB_ID  = vcast_get_subprogram_id (VC_TEXT);
         /* The E0 file is ordered */
         if (UNIT_ID > unit)
            break;
         else {
            if (SUB_ID != 0 && UNIT_ID == unit && SUB_ID == subProgram) {
               vCAST_RUN_DATA_IF(VC_TEXT, vCAST_false);
               }
            }
        }
      }
   vectorcast_fclose ( vCAST_E0_FILE );
}


/* READ_COMMAND_DATA_FOR_USER_GLOBALS:
 * -----------------------------------
 * Reloads any user globals which have been modified by a (void *) stub.
 * The global array vCAST_GLOBALS_TOUCHED is used to determine whether a
 * given global needs to be reloaded.  The entry in the array is reset to
 * false after reloading the value.  */

void vCAST_READ_COMMAND_DATA_FOR_USER_GLOBALS(void)
{
   int     CMD_FILE;
   char    VC_FILENAME[VCAST_FILENAME_LENGTH];
   int     VC_LENGTH;
   char    vcast_buf[VCAST_MAX_STRING_LENGTH];
   char    unit_str[5], param_str[4];
   int     param;
   char    COMMAND_PARAM[VCAST_MAX_STRING_LENGTH];

   VCAST_strcpy(VC_FILENAME, vCAST_ORDER_OBJECT.testFilename);
   CMD_FILE = vectorcast_fopen(VC_FILENAME, "r");

   while (!vectorcast_feof(CMD_FILE)){

      vectorcast_readline(COMMAND_PARAM, CMD_FILE);

      VC_LENGTH = VCAST_strlen(COMMAND_PARAM);
      if (VC_LENGTH > 7) {
         vcast_get_unit_id_str (COMMAND_PARAM, unit_str);
         vcast_get_parameter_id_str (COMMAND_PARAM, param_str);
         param = VCAST_atoi(param_str);

         if ((VCAST_atoi(unit_str) == 8) &&
             (param > 0 && vCAST_GLOBALS_TOUCHED[param-1]))
         {
            vCAST_EXTRACT_DATA_FROM_COMMAND_LINE(vcast_buf,
               COMMAND_PARAM, vCAST_RANGE_COUNTER);

            if(VCAST_strlen(vcast_buf) != 0)
               vCAST_RUN_DATA_IF(vcast_buf, vCAST_false);
         }
      }
   } /* end while */

   vectorcast_fclose(CMD_FILE);

   /* Reset the globals-touched array */
   for (param = 0; param < sizeof(vCAST_GLOBALS_TOUCHED)/
                           sizeof(vCAST_boolean); param++)
      vCAST_GLOBALS_TOUCHED[param] = vCAST_false;
} 

/* this function figures out the name of the "capture" file for 
this slot (E000000n.DAT where n is the slot number it expects
to receive a char array of VCAST_FILENAME_LENGTH size */
static void computeE0filename (char* filename) {
  char vcWork[7];
  int  vcI, vcLen;
  VCAST_strcpy ( filename, "E0000000.DAT" );
  vcast_unsigned_to_string ( vcWork, vCAST_CURRENT_SLOT+1 );
  vcLen = VCAST_strlen ( vcWork );
  for ( vcI=0; vcI<vcLen; vcI++ )
    filename[8-vcLen+vcI] = vcWork[vcI];
}
       

void vCAST_OPEN_E0_FILE (void)
{
  char filename [VCAST_FILENAME_LENGTH];
  computeE0filename (filename);
  vCAST_E0_FILE = vectorcast_fopen ( filename, "r" );
}


void vCAST_CREATE_EVENT_FILE (void)
{
  if (!vCAST_ASCIIRES_FILE_OPEN)
    vCAST_ASCIIRES_FILE = vectorcast_fopen(
      vcast_get_filename(VCAST_ASCIIRES_DAT), "w");
  vCAST_ASCIIRES_FILE_OPEN = vCAST_true;
  vCAST_OUTPUT_FILE = vCAST_ASCIIRES_FILE;
}

void vCAST_CLOSE_EVENT_FILE (void)
{
  vectorcast_fclose ( vCAST_ASCIIRES_FILE );
  vCAST_ASCIIRES_FILE_OPEN = vCAST_false;
}

void vCAST_CREATE_INST_FILE (void)
{
   if (!vCAST_INST_FILE_OPEN){
#ifdef VCAST_NO_APPEND
      vCAST_INST_FILE = vectorcast_fopen (
         vcast_get_filename(VCAST_TESTINSS_DAT), "w");
#elif defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_COVERAGE_IO_BUFFERED)
      vCAST_INST_FILE = vectorcast_fopen (
         vcast_get_filename(VCAST_TESTINSS_DAT), "wb");
#else
      vCAST_INST_FILE = vectorcast_fopen (
         vcast_get_filename(VCAST_TESTINSS_DAT), "a");
#endif
      vCAST_INST_FILE_OPEN = vCAST_true;
   }
}

void vCAST_CLOSE_INST_FILE (void)
{
   if (vCAST_INST_FILE_OPEN){
      vectorcast_fclose ( vCAST_INST_FILE );
      vCAST_INST_FILE_OPEN = vCAST_false;
   }
}

void vCAST_CREATE_HIST_FILE (void)
{
   if (!vCAST_THISTORY_FILE_OPEN){
      vCAST_THISTORY_FILE = vectorcast_fopen (
         vcast_get_filename(VCAST_THISTORY_DAT), "w");
      vCAST_THISTORY_FILE_OPEN = vCAST_true;
   }
}

void vCAST_CLOSE_HIST_FILE (void)
{
   if (vCAST_THISTORY_FILE_OPEN){
      vectorcast_fclose ( vCAST_THISTORY_FILE );
      vCAST_THISTORY_FILE_OPEN = vCAST_false;
   }
}

/* We do this append processing so that we can minimize
   the number of open file handles at any one time.
   VisualDSP for instance has a maximum number of
   open handles that are supported.

   The problem is that for vxSim on Windows, the
   "append" does not work.  So we have a conditional
   compile to disable this close and append */

void vCAST_RE_OPEN_HIST_FILE (void)
{
#ifndef VCAST_NO_APPEND
   if (!vCAST_THISTORY_FILE_OPEN){
      vCAST_THISTORY_FILE = vectorcast_fopen (
         vcast_get_filename(VCAST_THISTORY_DAT), "a");
      vCAST_THISTORY_FILE_OPEN = vCAST_true;
   }
#endif
}

void vCAST_CLOSE_HIST_FILE_FOR_EVENT (void)
{
#ifndef VCAST_NO_APPEND
   if (vCAST_THISTORY_FILE_OPEN){
      vectorcast_fclose ( vCAST_THISTORY_FILE );
      vCAST_THISTORY_FILE_OPEN = vCAST_false;
   }
#endif
}


void vCAST_openHarnessFiles(void) {
    
     vCAST_CREATE_INST_FILE();
     vCAST_CREATE_EVENT_FILE();
     vCAST_CREATE_HIST_FILE();
     
     /* Environment user code files */
     vcast_user_file = vectorcast_fopen (
        vcast_get_filename(VCAST_USERDATA_DAT), "w" );
     VCAST_EXP_FILE  = vectorcast_fopen (
        vcast_get_filename(VCAST_EXPECTED_DAT), "w" );
    
}


void vCAST_closeHarnessFiles (void) {
    
     vCAST_CLOSE_INST_FILE();
     vCAST_CLOSE_EVENT_FILE();
     vCAST_CLOSE_HIST_FILE();   
     
     /* Environment user code files */
     vectorcast_fclose ( vcast_user_file );
     vectorcast_fclose ( VCAST_EXP_FILE );
    
}


#ifndef VCAST_DISABLE_UC_WRITE_EXPECTED
void vCAST_UC_WRITE_EXPECTED (const char *vcast_param, const char *vcast_name, int vcast_match, const char *vcast_actual) 
{
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, "-- VcastExpect" );
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, vcast_param );
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, (vcast_match ? "1" : "0") );
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, vcast_name );
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, "-- VcastActual" );
   if ( vcast_actual ) {
     vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, vcast_actual );
   }
   vectorcast_fprint_string_with_cr (VCAST_EXP_FILE, "-- VcastEnd" );
}
#endif 




/* This function is used to print the "end of slot" message at the end
   of each slot. For Compound For Batch functionality with nested
   compounds, we want the descriptor at the end of each CFB slot, not 
   each child's slots.
   NOTE: We're printing the slot separator at the end of each slot
   if we're _not_ CFB, but we probably don't need to. */
void VCAST_SLOT_SEPARATOR ( vCAST_boolean VC_EndOfSlot )
{
   /* This function gets called whenever we return from a UUT, so
      we need to check if the EndOfSlot flag is set. */
   if ( VC_EndOfSlot == vCAST_true ) {

      if ( (vCAST_ORDER_OBJECT.slotDescriptor[0] == 'Z') || /* CFB slot */
           (vCAST_ORDER_OBJECT.slotDescriptor[0]>='0' && vCAST_ORDER_OBJECT.slotDescriptor[0]<='9') ) /* not CFB */
      {
         vectorcast_fprint_string_with_cr ( VCAST_EXP_FILE, "-- Slot " );
         vectorcast_fprint_string_with_cr ( VCAST_STDOUT, "VCAST Slot is Done!" );
         vectorcast_fprint_string_with_cr ( vCAST_OUTPUT_FILE, "-- Slot " );
         /* only for CFB we need to add a separator
            to the history and coverage files */
         if ( vCAST_ORDER_OBJECT.slotDescriptor[0] == 'Z') {
            vCAST_RE_OPEN_HIST_FILE();
            vectorcast_fprint_string_with_cr ( vCAST_THISTORY_FILE, "-- Slot " );
            vCAST_CLOSE_HIST_FILE_FOR_EVENT();
            VCAST_WRITE_TO_INST_FILE ( "-- Slot" );
         } /* add separator to history file */
      } /* need separator text */
   } /* end of slot */
}




/* This is the place to initialize any global data that is declared
   in this file.  Some of the target compilers do not by default 
   initialize global scope variables, so we do this explicitly here */
void vcastInitializeS2Data (void) {

    VCAST_DEFAULT_DO_COMBINATION = 0;
    VCAST_DEFAULT_FULL_STRINGS = 0;
    VCAST_DEFAULT_HEX_NOTATION = 0;
    vCAST_DO_DATA_IF = 0;
    vCAST_ASCIIRES_FILE_OPEN = vCAST_false;
    VCAST_GLOBAL_FIRST_EVENT = 1;
    VCAST_GLOBALS_DISPLAY = 0;
    vCAST_HAS_RANGE = vCAST_false;
    vCAST_HIST_INDEX = 1;
    vCAST_THISTORY_FILE_OPEN = vCAST_false;
    vCAST_INST_FILE_OPEN = vCAST_false;
    vCAST_RANGE_COUNTER = 0;
    vcSlotIteration = 0;
    vcRangeIteration = 0;
    vCAST_SKIP_ITER = vCAST_false;
    vCAST_SUBPROGRAM = 1;
    vCAST_CURRENT_SLOT = 0;
    vCAST_TOOL_ERROR = vCAST_false;  
    vCAST_UNIT = 9;
#if VCAST_MAX_RANGE>0
    vcRangeDataIndex=0;
#endif
}   
   
   
void vcastInitializeB2Data (void) {
   vCAST_INST_FILE_OPEN = vCAST_false;
   vCAST_ASCIIRES_FILE_OPEN = vCAST_false;
   vCAST_THISTORY_FILE_OPEN = vCAST_false;
   vCAST_TOOL_ERROR = vCAST_false;
   vCAST_SKIP_ITER = vCAST_false;
   vCAST_PARTITIONS = VCAST_FLOAT_ONE;
   VCAST_memset(eventFlagObject, ' ', sizeOfEventFlagObject);
   eventFlagObject[sizeOfEventFlagObject-1] = '\0';

#ifdef VCAST_NO_MALLOC
   vcast_heap_size = 0;
#endif
}

void vCAST_CHECK_ROBJECT( void* vcastRobject, int vcastCombinedID )
{
   if ( vcast_is_in_driver && !vcastRobject )
      vCAST_SET_HISTORY ( 1011, vcastCombinedID );
}


/* ------------------------------------------------------------------- */
/* These functions were added to support code based test CBT */


/* I created this for simplicity, since we really just want to 
   extract the a few of the key commands from the C-*.DAT file ...
   to figure out if we re CBT, and what the unit and subprogram are.
   It seemed unnecessary to go though the B1 stuff in this case.
*/
void vcastGetKeyTestValues (void) {
    
   int     fileIndex;
   char    line[VCAST_MAX_STRING_LENGTH];
   
   
   vcastIsCodeBasedTest = vCAST_false;

   /* Open the file for this slot */
   fileIndex = vectorcast_fopen (vCAST_ORDER_OBJECT.testFilename, "r" );
   while (!vectorcast_feof(fileIndex)){
       vectorcast_readline(line, fileIndex);
       if (VCAST_strncmp (&line[0], "0.0.0.3%",7)==0) {  /* unit index */
          vCAST_UNIT = VCAST_atoi (&line[8]); }
       else if (VCAST_strncmp (&line[0], "0.0.0.0%",7)==0) { /* subprogram index */
          vCAST_SUBPROGRAM = VCAST_atoi (&line[8]);}
       else if (VCAST_strncmp (&line[0], "0.0.0.5%",7)==0) { /* code based test */ 
          /* This command is only in the file in the "true" case */
          vcastIsCodeBasedTest = vCAST_true;}
       else if (VCAST_strncmp (&line[0], "0.0.0.6%",7)==0) { /* Number of CBT CALLs */
          vcRangeIterationsForThisTest = VCAST_atoi (&line[8]);}
   }         
   vectorcast_fclose ( fileIndex );
}

/*
   For now, we are only supporting code based test for c++, so we
   enclose these functions in a harness supports CBT check
*/

#ifdef VCAST_CODE_BASED_TESTS_ALLOWED


/* For code-based, we track the monitored variables and expected values 
   that the user defines as part of the code-based test CBT.
   The E-*.DAT files have the expected values, and the E0*.DAT files have
   the values that are captured by the harness for each slot.
   
   Since we only support CBT for C++ we could use a C++ vector here
   if we wanted this to be more flexible!

   Note: The CBT data objects are defined at the top of this file 
   */


/* Called from the macro: VMONITOR, (adds value to exec report) */
void vcCBTaddE0Command (const char* vcCmd) {
    
   if (vc_E0_FILE_LENGTH<VC_MAX_CBT_LIST_SIZE) {
       VCAST_strcpy (vc_E0_FILE_COMMANDS[vc_E0_FILE_LENGTH], vcCmd);
       VCAST_strcat (vc_E0_FILE_COMMANDS[vc_E0_FILE_LENGTH], "%0\0");
       vc_E0_FILE_COMMANDS[vc_E0_FILE_LENGTH][0] = '1';
       vc_E0_FILE_LENGTH++;
    }    
}

/* Called from the macro: VEXPECT_EQ, (sets expected value) */
void vcCBTaddEDashCommand (const char* vcCmd, const char* vcValues) {
    
   if (vc_E_DASH_FILE_LENGTH<VC_MAX_CBT_LIST_SIZE) {
        VCAST_strcpy (vc_E_DASH_FILE_COMMANDS[vc_E_DASH_FILE_LENGTH], vcCmd);
        VCAST_strcat (vc_E_DASH_FILE_COMMANDS[vc_E_DASH_FILE_LENGTH], "%");
        VCAST_strcat (vc_E_DASH_FILE_COMMANDS[vc_E_DASH_FILE_LENGTH], vcValues);
        VCAST_strcat (vc_E_DASH_FILE_COMMANDS[vc_E_DASH_FILE_LENGTH], "\0");
        vc_E_DASH_FILE_LENGTH++;
    }
    vcCBTaddE0Command (vcCmd);  /* also add to monitored list */ 
}

/* Called indirectly from the macro: VSET, (multi returns from stub) */
void vcCBTaddCDashCommand (const char* vcCmd, const char* vcValues) {
    
   if (vc_C_DASH_FILE_LENGTH<VC_MAX_CBT_LIST_SIZE) {
        VCAST_strcpy (vc_C_DASH_FILE_COMMANDS[vc_C_DASH_FILE_LENGTH], vcCmd);
        VCAST_strcat (vc_C_DASH_FILE_COMMANDS[vc_C_DASH_FILE_LENGTH], "%");
        VCAST_strcat (vc_C_DASH_FILE_COMMANDS[vc_C_DASH_FILE_LENGTH], vcValues);
        VCAST_strcat (vc_C_DASH_FILE_COMMANDS[vc_C_DASH_FILE_LENGTH], "\0");
        vc_C_DASH_FILE_LENGTH++;
    }
}

  
/* In the CBT case, we have very simple requirements for store_ascii_data, so
   we define this simplified version of the functions here */
void vCAST_STORE_GLOBAL_ASCII_DATA_CBT (void) {}
void vCAST_STORE_ASCII_DATA_CBT (int UN_IT, int SUB_PROG ) {
    int i;
    int  UNIT_ID;
    int  SUB_ID;
    for (i=0;i<vc_E0_FILE_LENGTH;i++) {
        UNIT_ID = vcast_get_unit_id (vc_E0_FILE_COMMANDS[i]);
        SUB_ID  = vcast_get_subprogram_id (vc_E0_FILE_COMMANDS[i]);
        if (SUB_ID==0 || (UNIT_ID == UN_IT && SUB_ID == SUB_PROG)) {
           vCAST_RUN_DATA_IF(vc_E0_FILE_COMMANDS[i], vCAST_false);
        }
    }
 }

 
/* This function will insert a Code Based Test Output event
   if the user has made any calls to VEXPECT during the current test */
void vcCBTinsertEvent (void) {
    if (vcastInsertCBTevent==vCAST_true) {
        vCAST_SET_HISTORY (1016,1);
        vcastInsertCBTevent=vCAST_false;
    }
}
 
void vcCBTendOfTest (void) {
    
    int  i;
    char filename [VCAST_FILENAME_LENGTH];
    
    /* Insert an event with the user generated expected values */
    vcCBTinsertEvent();
    
    /* Dump the E0.DAT file ... */
    computeE0filename (filename);
    vCAST_E0_FILE = vectorcast_fopen ( filename, "w" );
    
    for (i=0;i<vc_E0_FILE_LENGTH;i++) {
       vectorcast_fprint_string_with_cr (vCAST_E0_FILE, vc_E0_FILE_COMMANDS[i]);
       }  
    vectorcast_fclose (vCAST_E0_FILE);
    vc_E0_FILE_LENGTH = 0;  /* reset buffer */

    /* Dump the E-.DAT file ...
       The input file has a name like C-000001.HAR. we meed 
       use a similar name, just change the C to E and HAR to DAT */
    VCAST_strcpy (filename, vCAST_ORDER_OBJECT.testFilename);
    filename[0] = 'E';
    filename[9] = 'D';
    filename[10] = 'A';
    filename[11] = 'T';
    vCAST_E0_FILE = vectorcast_fopen ( filename, "w" );
    
    /* There is an edge case when the same test is in a compound multiple times
       in this case in stdout mode we would end up with the file having it's 
       contents duplicated for each instance.  We guard against that by keeping
       track of the E- files we have already written.
    */
    for (i=0;i<vc_E_DASH_FILE_LENGTH;i++) {
       vectorcast_fprint_string_with_cr (vCAST_E0_FILE, vc_E_DASH_FILE_COMMANDS[i]);
       }  
    vectorcast_fclose (vCAST_E0_FILE);
    /* reset test specific buffers */
    vc_E_DASH_FILE_LENGTH = 0;
    vc_C_DASH_FILE_LENGTH = 0;  
  }
  
#endif /* VCAST_CODE_BASED_TESTS_ALLOWED */

