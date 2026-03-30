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

/*  This file contains platform/compiler specific 
    harness code that is used in test driver (S3) */

#ifdef VCAST_KEIL
#include "vcast_keil_setup.h"
#endif

/* STVD environment does not break on breakpoints, but on watches */
/* VCAST_OUTPUT_VIA_DEBUGGER needs to flag the debugger it can exit its polling loop */
int vcast_exit_flag = 0;


#ifdef VCAST_IAR_4x_TS7300
typedef struct
{
   void (*boot_sdread)();
   void (*boot_ser_puts)();
   unsigned int SystemID;
   unsigned char* DirectoryTail;
   unsigned int StartOfData;
} PARAM_SAVE;
__no_init const PARAM_SAVE __param_save;

/* external prototypes  */
void boot_sdread(unsigned int start_sector, char* buffer, int num_sectors);
void boot_ser_puts(char* buffer);

#endif

#ifdef VCAST_PIC24_LMCO_TGT
#include <intrinsics.h>
#include "io24fj256gb110.h"
#include "MemInterface.h"
#endif

#if defined (__HC12__) && defined (__PRODUCT_HICROSS_PLUS__)
#include <termio.h>
#ifdef VCAST_CW_HC12_SIM
#include <terminal.h>
#endif
#endif

#ifdef VCAST_VXWORKS_653
#include "vThreadsData.h"
#endif

#include "vcast_c_options.h"


#ifdef VCAST_PARADIGM
#define	__PASCAL 	__pascal

#if !defined(CSIM_BUILD)
#define __FAR	__far
#else
#define __FAR	
#endif

void            SerialPortBegin(void);
void Vcast_PMain(void);

extern "C"
{
      void __PASCAL __FAR HwTimerAlarmmStop(void);
};
#endif

#ifdef VCAST_PARADIGM_SC520

#ifndef _586_H_
#define _586_H_
typedef struct  {
	unsigned char ready; /* TRUE when ready */
	unsigned char baud;
	unsigned int mode; 
	unsigned char iflag;   /* interrupt status */
	unsigned char* in_buf; /* Input buffer */
	unsigned int in_tail; /* Input buffer TAIL ptr */
	unsigned int in_head; /* Input buffer HEAD ptr */
	unsigned int in_size; /* Input buffer size */
	unsigned int in_crcnt; /* Input <CR> count */
	unsigned char in_mt; /* Input buffer FLAG */
	unsigned char in_full; /* input buffer full */
	unsigned char* out_buf; /* Output buffer */
	unsigned int out_tail; /* Output buffer TAIL ptr */
	unsigned int out_head; /* Output buffer HEAD ptr */
	unsigned int out_size; /* Output buffer size */
	unsigned char out_full; /* Output buffer FLAG */
	unsigned char out_mt; /* Output buffer MT */
	unsigned char tmso;	/* transmit macro service operation */
	unsigned char rts;
	unsigned char dtr;
	unsigned char en485;
	unsigned char err;
	unsigned char node;
	unsigned char cr; /* scc CR register */
	unsigned char slave;
	unsigned int in_segm; /* input buffer segment */
	unsigned int in_offs; /* input buffer offset */
	unsigned int out_segm; /* output buffer segment */
	unsigned int out_offs; /* output buffer offset */
	unsigned char byte_delay; /* V26 macro service byte delay */
} COM;

#ifdef __cplusplus
extern "C" void sc_init(void);
extern "C" void s1_close(COM *c);
extern "C" void s1_flush(COM *c);
#include "heapsize.c"  /* allow for dynamic memory allocation */
#else
void sc_init(void);
void s1_close(COM *c);
void s1_flush(COM *c);
#endif 

#endif

#ifdef __cplusplus
extern "C" {
#endif 

#include "SER1.h"

#ifdef __cplusplus
}
#endif 

#define MAXOSIZE 1024
#define MAXISIZE 1024
unsigned char ser1_out_buf[MAXOSIZE];
unsigned char ser1_in_buf[MAXISIZE];
unsigned int delay_ctr;
extern COM ser1_com;

   COM * c1;
#ifndef SC520_BAUD
#define SC520_BAUD 8
#endif
/*    baud = 8,  19,200 baud (default)
*     baud = 9,  38,400 baud
*     baud = 10, 57,600 baud
*     baud = 11, 115,200 baud 
*/
unsigned char baud = SC520_BAUD;
#endif  /* end ifdef VCAST_PARADIGM_SC520  */


#ifdef VCAST_NO_EXIT
#ifndef VCAST_NO_SETJMP
  jmp_buf jmp_exit;
#endif
#endif

vCAST_boolean vcast_already_exited = vCAST_false;


#ifdef VCAST_BUFFER_OUTPUT
extern char vcast_output_buffer[VCAST_OUTPUT_BUFFER_SIZE];
#endif

#if defined(GRUNDIG_C51_TGT)
extern void DisableWatchdog() ;
#endif

/******************************************************************/
/* The following need to be included for NEC F3618 and F3619      */
/* Clock output settings may need to be uncommented in some cases */
/******************************************************************/
#if defined (VCAST_NEC_V850)
#include 	"define.h"
#include	"init.h"
#include 	"isr.h"
#include 	"comm.h"
#include	"macrodriver.h"
#include    "comm.h"
#define	ROOT
#include 	"main.h"
#pragma ioreg
/*#define	_CLKOUT		//Clock Output setting
// Skip - I/O port setting*/
#include    "initialize.c"
int _rcopy(unsigned long *, long);
extern unsigned long _S_romp;
#endif /* VCAST_NEC_V850 */

#if defined(VCAST_uVELOSITY)

/* In the case of Micro Velosity, we need to define a "main"  */
/* Function that sets up the VectorCAST Driver as a task, and */
/* then starts the operating system.  The OS will call    */
/* the VectorCAST driver */
#include <gh_os.h>
#include <stdio.h>

static GH_TASK vcast_driver;
static GH_STACK_AREA_DEFINE(vcast_driver_stack, 0x8000);

/* this is the actual vectorcast main() */
static GH_VALUE vcast_driver_entry(GH_ADDRESS input);

#endif /* VCAST_uVELOSITY */

#if defined(VCAST_THREADX)

/* In the case of ThreadX, we need to define a "main" function */
/* that starts the kernel running, and a ThreadX interface function */
/* that sets up the VectorCAST Driver as a thread, which the OS can */
/* then schedule. */
#include    "tx_api.h"
TX_THREAD vcast_driver;

/* This is the actual vectorcast main() */
static int vcast_driver_entry(ULONG thread_input);

#endif /* VCAST_THREADX */




/* Trace Stuff ------------------------------------------------------------- */ 
#ifndef VCAST_TEST_HARNESS_TRACE
#define tracePoint1()
#define tracePoint2()
#define tracePoint3()
#define tracePoint4a()
#define tracePoint4b()
#define tracePoint5()
#define tracePoint6(status)
#else

static void tracePoint1(void) {
  /* TracePoint #1 (main)  #########################################
  Within the Test Harness files there are several of these comment 
  blocks located at key debugging points to help with debugging test 
  harness execution on a new target. Search for TracePoint to 
  find these locations.
  
  This call to vectorcast_initialize_io is a key point in the execution
  of the test harness for many target environments.  If your test harness 
  is configured for to use stdio then the allocation of the memory
  based file system occurs here.
  
  You should set a breakpoint on this function, and then step-over.  If
  you do not come back from the call, the most likely you have a stack
  or heap problem that can be diagnosed by setting breakpoints in the 
  ccast_io functions (file: B0000007.c|cpp)
  */ 

vectorcast_write_to_std_out ("TracePoint S3: #1a, ");
vectorcast_write_to_std_out ("about to call: vectorcast_initialize_io()\n");
VCAST_TRACEPOINT_1:;
}

static void tracePoint2 (void) {
         /* TracePoint #2 (main)  ######################################### 
     If you get there, then the initialization part of the harness has
     completed.  This does not mean that all of the data is necessarily
     setup properly!  
  
     Each iteration of the while loop is a single test, or in the case
     of a compound test, a single slot.  So if "step" from here does not
     go into this loop, there was a problem in the data init.
     */      
vectorcast_write_to_std_out ("TracePoint S3: #2, ");
vectorcast_write_to_std_out ("about to call: vCAST_READ_NEXT_ORDER()\n");
VCAST_TRACEPOINT_2:;
}

static void tracePoint3 (void) {

       /* TracePoint #3 (main)  ######################################### 
       Check what the "Order" structure looks like.
       For example, the field: VC_N should have the name of the .HAR file,
       something that looks like: "C-00000x.HAR"
       */
vectorcast_write_to_std_out ("TracePoint S3: #3, ");
vectorcast_write_to_std_out ("after call to: vCAST_ORDER()\n");
VCAST_TRACEPOINT_3:;
}

static void tracePoint4a (void) {
       
       /* TracePoint #4a (main)  ######################################### 
       If you find that you are not getting to the function under test,
       or you get there, and the input data is not correct, you can come
       back to this point and step through the vCAST_READ_COMMAND_DATA
       */
vectorcast_write_to_std_out ("TracePoint S3: #4a, ");
vectorcast_write_to_std_out ("about to call: vCAST_READ_COMMAND_DATA()\n");
}

static void tracePoint4b (void) {
    
  /* TracePoint #4b (main)  ######################################### 
     Here, you can check that the globals: vCAST_UNIT, and vCAST_SUBPROGRAM
     are set properly.  When there is one unit under test, vCAST_UNIT will 
     generally be 9.
     */
VCAST_TRACEPOINT_4:;
vectorcast_write_to_std_out ("TracePoint S3: #4b, ");
vectorcast_write_to_std_out ("validate Global Data: vCAST_UNIT and vCAST_SUBPROGRAM: ");
{
char debugString[20];
vcast_unsigned_to_string ( debugString,vCAST_UNIT);
vectorcast_write_to_std_out  ( debugString );
vectorcast_write_to_std_out  ( " / " );
vcast_unsigned_to_string ( debugString,vCAST_SUBPROGRAM );
vectorcast_write_to_std_out  ( debugString );
vectorcast_write_to_std_out  ("\n");
}
}

static void tracePoint5() {
    
 /* TracePoint #5 (main)  ######################################### 
    This is where the actual invocation of the function under test 
    happens.  You can step into this call and through the downstream
    functions until you get to the function under test.  Or just set
    a break point on the function under test.  In either case, once
    you get to the function under test, you should verify that the 
    parameters match what was setup in the test case.
    */
vectorcast_write_to_std_out ("TracePoint S3: #5, ");
vectorcast_write_to_std_out ("about to call: vcast_S3_switch()\n");
VCAST_TRACEPOINT_5:;
}

 
static void tracePoint6(int status) {

/* TracePoint #6 (main)  ######################################### 
      If you get here, check the value of the "status" parameter
      The following error codes are possible:
         2 - Event limit exceeded
         4 - VC version of malloc failed
         5 - syslib malloc failed
         6 - syslib realloc failed
         7 - Output Buffer Overflow
      In the case of values 4-6 which are memory errors, we do not
      do all of the normal termination processing, we just exit
   */
VCAST_TRACEPOINT_6:;

{
char debugString[20];
vectorcast_write_to_std_out ("TracePoint S3: #6, ");
vectorcast_write_to_std_out ("in driver_termination (). Exit status is: ");
vcast_unsigned_to_string ( debugString, status);
vectorcast_write_to_std_out  ( debugString );
vectorcast_write_to_std_out  ( "\n" );
}
}

#endif   




/* Profiling Stuff ------------------------------------------------------------- */ 

void vcastStartProfiling (void);
void vcastSaveProfilingData (void);


#if defined(VCAST_MONITOR_STACK) || defined(VCAST_MONITOR_HEAP)
#include "HeapAndStackMonitor.c"
#endif

/* Startup all profiling processing */
void vcastStartProfiling () {

/*****************************************************************************/
#if defined(VCAST_MONITOR_STACK)
   vcast_initStack();
#endif

/*****************************************************************************/
#if defined(VCAST_MONITOR_HEAP)
   vcast_initHeap();
#endif

}

/* Output all profiling data */
void vcastSaveProfilingData () {
    
#if defined(VCAST_MONITOR_STACK) || defined(VCAST_MONITOR_HEAP)
   int stackUsage;
   int heapUsage;
   int fileHandle;  
   fileHandle = vectorcast_fopen("ProfileData.txt", "w");
#endif

/*****************************************************************************/
#if defined(VCAST_MONITOR_STACK)
   stackUsage = vcast_usedStack ();
   vectorcast_fprint_string  (fileHandle, "stack_data\n");
   vectorcast_fprint_string  (fileHandle, "size: ");
   vectorcast_fprint_integer (fileHandle, VCAST_MONITOR_STACK_SIZE);
   vectorcast_fprint_string  (fileHandle, "\n");
   vectorcast_fprint_string  (fileHandle, "unmonitored(bytes): ");
   vectorcast_fprint_integer (fileHandle, UNmonitoredStackBytes);
   vectorcast_fprint_string  (fileHandle, "\n");
   vectorcast_fprint_string  (fileHandle, "usage: ");
   vectorcast_fprint_integer (fileHandle, stackUsage);
   vectorcast_fprint_string  (fileHandle, "\n");          
   vectorcast_fprint_string  (fileHandle, "stack_data_end\n");        
#endif

/*****************************************************************************/
#if defined(VCAST_MONITOR_HEAP)
   heapUsage = vcast_usedHeap ();
   vectorcast_fprint_string  (fileHandle, "heap_data\n");
   vectorcast_fprint_string  (fileHandle, "size: ");
   vectorcast_fprint_integer (fileHandle, VCAST_MONITOR_HEAP_SIZE);
   vectorcast_fprint_string  (fileHandle, "\n");
   vectorcast_fprint_string  (fileHandle, "unmonitored(bytes): ");
   vectorcast_fprint_integer (fileHandle, UNmonitoredHeapBytes);
   vectorcast_fprint_string  (fileHandle, "\n");
   vectorcast_fprint_string  (fileHandle, "usage: ");
   vectorcast_fprint_integer (fileHandle, heapUsage);
   vectorcast_fprint_string  (fileHandle, "\n");          
   vectorcast_fprint_string  (fileHandle, "heap_data_end\n");   
#endif

#if defined(VCAST_MONITOR_STACK) || defined(VCAST_MONITOR_HEAP)
   vectorcast_fclose(fileHandle);
#endif

}

#ifdef VCAST_CUSTOM_END
#ifdef __cplusplus
  extern "C" void VCAST_CUSTOM_END(void);
#else
  extern void VCAST_CUSTOM_END(void);
#endif
#endif

/* This is the common function to call when you want to exit the harness
   if we are exiting because of a problem like the event limit exceeded etc
*/
void vCAST_END(void) {
  /* The purpose of this function is to provide a place to put a breakpoint 
     at the end of the execution of the harness.  For some debuggers, we
     place a watchpoint on the global vcast_exit_flag.
     VCAST_END_LABEL is used for Cosmic HC12
  */
 
#ifdef VCAST_CUSTOM_END
  VCAST_CUSTOM_END();
#endif

#ifdef VCAST_COSMIC
VCAST_END_LABEL:
#endif
  vcast_exit_flag = 1;
  
  /* This object is used for some targets to set an object write BP */
  /* This is used for Keil and maybe others ... */
  vcast_already_exited = vCAST_true;

}


void VCAST_driver_termination(int status, int eventCode) {

    tracePoint6(status);

/* The minimal termination does not work in "file mode" */

#if defined(VCAST_MINIMAL_TERMINATION) && (defined (VCAST_STDIO) || defined (VCAST_NO_STDIN))

    if (eventCode > 0) {
      vectorcast_fprint_integer (vCAST_THISTORY_FILE, eventCode);
      vectorcast_fprint_string  (vCAST_THISTORY_FILE, ",1\n");
    }      
    vectorcast_fprint_string (vCAST_THISTORY_FILE, "0,0\n");
    /* Force a new line with the initial \n */
    vectorcast_print_string ("\nVCAST.END:END\n");
    vCAST_END();
    
#else /* else we are not doing minimal termination */

  if (status == 7) {
     /* 7 is the output buffer over-flow and we can get into some nasty
        recursion if we even try to write the normal stuff since
        every write uses buffer.  So just end */
     vCAST_END(); }
  else {
     commonTerminationProcessing (status, eventCode);
     vcastSaveProfilingData ();
     vCAST_END();
 
#ifdef VCAST_PARADIGM_SC520
#ifndef SC520_DELAY
#define SC520_DELAY 10
#endif
     s1_flush(c1);
     delay_ctr = SC520_DELAY;
     while(delay_ctr) {delay_ctr--;}
#endif
  }  /* end special status code handling */
  
#ifndef VCAST_NO_EXIT
#undef exit
   exit( status );
#else
#ifndef VCAST_NO_SETJMP
   longjmp( jmp_exit, status );
#endif
#endif
  
   /* if we get here then we could not exit via a direct call or via jump so ... just print a message */
   if( status != 0 ) {
       vectorcast_print_string( "VCAST_NO_EXIT and VCAST_NO_SETJMP are set - not able to exit.\n" );
       }
       
#endif /* not minimal termination */


}  /* end function */





/* ------------------------------------------------------------------------ */
/* Special Processing for the declaration of the main() for various targets */
/* ------------------------------------------------------------------------ */

#if defined (VCAST_MAIN)
int vcast_main (int argc, char **argv) {

#elif defined (VCAST_MAIN_NO_ARGS)
#if defined(__cplusplus)
extern "C" void vcast_main (void);
#endif
void vcast_main (void) {

#elif defined(VCAST_PARADIGM)
void Vcast_PMain(void) {

#elif defined(VCAST_PARADIGM_SC520) || defined(VCAST_NEC_V850)
void main(void) {

#elif defined (VCAST_INTEGRITY)
extern int INDRTConnected;
#pragma weak INDRTConnected

int main(int argc, char **argv) {

#elif defined (VCAST_COSMIC)
/* Start of main delayed since it cannot go in a .h file without causing
the executable to fail to run. */

#elif defined(VCAST_KEIL) && defined(__cplusplus)
EXTERN_C int main () {

#elif defined(VCAST_KEIL_51) || defined(VCAST_RENESAS)  || defined(VCAST_KEIL_ARM) || defined(VCAST_KEIL_ARM_STM32_TGT)
int main() {

#elif defined(VCAST_VXWORKS_653)

const unsigned char *__ctype = NULL;
#if defined(__cplusplus)
extern "C" int VCAST_MAIN (void) {
#else
extern int VCAST_MAIN (void) {
#endif
  __ctype = *(__ctypePtrGet ()); 

#elif defined(VCAST_uVELOSITY)

/* In the case of Micro Velosity, we need to define a "main"  */
/* Function that sets up the VectorCAST Driver as a task, and */
/* then starts the operating system.  The OS will call    */
/* the VectorCAST driver */

#if defined(__cplusplus)
extern "C" int main(int argc, char **argv) 
#else
extern int main(int argc, char **argv) 
#endif
{
    /* Create any initial kernel objects. */
    gh_task_create(&vcast_driver, "vcast_driver", vcast_driver_entry, 0,
            vcast_driver_stack, sizeof(vcast_driver_stack), 10, GH_AUTO_START);
    /* Start uvelOSity. This call never returns. */
    uv_kernel_start();
    return 0;    
}


/*  Define the entry routine for our actual main                  */
/* This is what the prototype for the actual main would look like */
/* static GH_VALUE vcast_driver_task_entry(GH_ADDRESS input);     */
static GH_VALUE vcast_driver_entry(GH_ADDRESS input) {

#elif defined(VCAST_THREADX)


/* In the case of ThreadX, we need to define a "main" function */
/* that starts the kernel running, and a ThreadX interface function */
/* that sets up the VectorCAST Driver as a thread, which the OS can */
/* then schedule. */

void main() 
{
    /* Enter the ThreadX kernel. This call never returns. */
    tx_kernel_enter( );
}

/* It may be necessary to tweak this value on memory-constrained targets */
#define VCAST_THREADX_DRIVER_STACK 0x1000

/* Set up the driver as a ThreadX thread */
void tx_application_define(void *first_unused_memory)
{
    /* Create the VectorCAST Driver thread */
    tx_thread_create(&vcast_driver, "VectorCAST Driver Thread", 
            vcast_driver_entry, 0x0, 
            first_unused_memory, VCAST_THREADX_DRIVER_STACK,
            3, 3, TX_NO_TIME_SLICE, TX_AUTO_START);
}

static int vcast_driver_entry(ULONG thread_input) {
    
#else
    
int main (int argc, char **argv) {

#endif  /* all of the code for the target main() definition */
