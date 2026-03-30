/*VectorCAST/Cover
* Copyright 2020 Vector Informatik, GmbH.
*/
#ifndef VCAST_COVER_IO_SYSTEM_CODE
/* If the c_cover_io.c file is being compiled as a separate file instead
   of being appended to a unit, VCAST_COVER_IO_SYSTEM_CODE will not have
   a value yet. Assign it to 1 so the definitions which depend on system
   headers are reached. */
#define VCAST_COVER_IO_SYSTEM_CODE 1
#endif /* VCAST_COVER_IO_SYSTEM_CODE */

#ifndef VCAST_COVER_IO_COVER_CODE
/* If the c_cover_io.c file is being compiled as a separate file instead
   of being appended to a unit, VCAST_COVER_IO_COVER_CODE will not have
   a value yet. Assign it to 1 so the definitions which are independent of
   system headers (but may require vcast_c_options.h) are reached. */
#define VCAST_COVER_IO_COVER_CODE 1
#endif /* VCAST_COVER_IO_COVER_CODE */

#ifndef VCAST_ATTRIBUTE_CODE
/* The default attribute for the variables vcast_ascii_coverage_data_pool
   and vcast_avltree_data_pool is no attribute. */
#define VCAST_ATTRIBUTE_CODE
#endif /* VCAST_ATTRIBUTE_CODE */

/* we needed to add this define because some compilers, Code Warrior in 
 * particular, will interpret the number "1" as a signed int, which when
 * bit shifted as we do for capturing coverage data, into the 15th bit
 * position, will cause the sign bit to get sign extended into the 
 * the upper 16 bits, so instead of getting 0x00008000 when you perform 
 * (1<<15), you get 0xFFFF8000.
 */
#define VCAST_UNSIGNED_1 ((VCAST_MCDC_STORAGE_TYPE)1)

#ifndef VCAST_UNIT_TEST_TOOL
#ifndef VCAST_USE_STATIC_MEMORY
/* In the unit test tool, this will use the VCAST_malloc
   already defined in the unit test harness. In the coverage
   tool, malloc is currently used. */
#define VCAST_malloc malloc
#define VCAST_free free
#endif /* VCAST_USE_STATIC_MEMORY */
#endif /* VCAST_UNIT_TEST_TOOL */
 
/* If we have been instructed to build for "shared object"
 * mode, then set the default linkage visibility to "hidden"
 */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility push(hidden)
#endif

#if (VCAST_COVER_IO_SYSTEM_CODE == 1)
/* Include vcast_c_options.h for VCAST_CONDITION_TYP definition. */
#include "vcast_c_options.h"
#if (VCAST_COVER_IO_COVER_CODE == 0)
typedef int VECTORCAST_MARKER__C_COVER_H_START;
#endif /*VCAST_COVER_IO_COVER_CODE == 0*/
#include "c_cover.h"
#if (VCAST_COVER_IO_COVER_CODE == 0)
typedef int VECTORCAST_MARKER__C_COVER_H_END;
#endif /*VCAST_COVER_IO_COVER_CODE == 0*/
 
/* use default linkage visibility for included headers */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility pop  
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#ifdef VCAST_SIMULINK_OUTPUT
#include "target_io.h"
#endif /* VCAST_SIMULINK_OUTPUT */

#ifdef VCAST_CUDA
#include <cuda_runtime.h>
#ifdef VCAST_CUDA_ENABLE_DRIVER_API
#include <cuda.h>
#endif /* VCAST_CUDA_ENABLE_DRIVER_API */
#endif /* VCAST_CUDA */

/* return to hidden linkage visiblity for coverage data/code */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility push(hidden)
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#ifndef VCAST_UNIT_TEST_TOOL

/*Allow file operations*/
#ifndef VCAST_USE_STDIO_OPS
#define VCAST_USE_STDIO_OPS
#endif /* VCAST_USE_STDIO_OPS */

#endif /*VCAST_UNIT_TEST_TOOL*/

/* VCAST_DUMP_BINARY_COVERAGE is not compatible with VCAST_USE_BUFFERED_ASCII_DATA */
#if defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#undef VCAST_USE_BUFFERED_ASCII_DATA
#endif

#ifdef VCAST_USE_BUFFERED_ASCII_DATA
/*Do not use file operations*/
#undef VCAST_USE_STDIO_OPS

extern char VCAST_ATTRIBUTE_CODE vcast_ascii_coverage_data_pool[];
int vcast_ascii_coverage_data_pos = 0;
int vcast_coverage_data_buffer_full = 0;
const char *VCAST_MAX_CAPTURED_ASCII_DATA_EXCEEDED_ERROR = "\nVCAST_MAX_CAPTURED_ASCII_DATA_EXCEEDED";
int vcast_max_captured_ascii_data_exceeded_error_size = 39;
void VCAST_WRITE_TO_BUFFER(const char *S);
#endif /* VCAST_USE_BUFFERED_ASCII_DATA */

#ifndef VCAST_COVER_NO_STDIO
char *
vcast_strcat (char *VC_S, const char *VC_T)
{
   int vc_i,vc_j;
   vc_i = vc_j = 0;
   while ( VC_S[vc_i] != 0 )
      vc_i++;           /* find end of VC_S */
   while ( (VC_S[vc_i++] = VC_T[vc_j++]) != 0 ) ; /* copy VC_T */
   return VC_S;
}

int vcast_strlen(const char *VC_S);
int
vcast_strlen(const char *VC_S)
{
   int vc_result = 0;

   while(*VC_S) {
      vc_result++;
      VC_S++;
   }

   return vc_result;
}

char *
vcast_int_to_string (char *buf, VCAST_MCDC_STORAGE_TYPE vc_x)
{
   int vc_i;
   VCAST_MCDC_STORAGE_TYPE vc_cur = vc_x;
   int vc_size = 0;

   if (vc_x == 0) {
      buf[0] = '0';
      buf[1] = '\0';
      return buf;
   }

   while (vc_cur != 0) {
      vc_size++;
      vc_cur /= 10;
   }

   for (vc_i = 0; vc_x != 0; vc_i++){
      buf[vc_size-vc_i-1] = (char)((vc_x % 10) + '0');
      vc_x /= 10;
   }

   buf[vc_size] = 0;

   return buf;
}
#endif /* VCAST_COVER_NO_STDIO */
 
/* use default linkage visibility for included headers */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility pop  
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#if defined(VCAST_DUMP_COVERAGE_AT_EXIT) || !defined(VCAST_USE_STATIC_MEMORY)
#if !defined(VCAST_COVER_NO_STDIO) && !defined(VCAST_NO_STDLIB)
/* Contains atexit and malloc prototypes */
#include <stdlib.h>
#endif /* !defined(VCAST_COVER_NO_STDIO) && !defined(VCAST_NO_STDLIB) */
#endif /* defined(VCAST_DUMP_COVERAGE_AT_EXIT) || !defined(VCAST_USE_STATIC_MEMORY) */

#if defined(VCAST_APPEND_SECONDS_SINCE_EPOCH) || defined(VCAST_APPEND_WIN32_PID_AND_EPOCH) || defined(VCAST_APPEND_POSIX_PID_AND_EPOCH)
#include <time.h>
#endif

#ifndef VCAST_USE_GH_SYSCALL
#ifdef VCAST_USE_STDIO_OPS
#ifndef VCAST_COVER_NO_STDIO
#include <stdio.h>
#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_USE_STDIO_OPS */
#endif /*VCAST_USE_GH_SYSCALL*/

#ifdef VCAST_COVER_CUSTOM_HEADER_INCLUDE
#include VCAST_COVER_CUSTOM_HEADER_INCLUDE
#endif

/* return to "hidden" linkage for internal symbols */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility push(hidden)
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#ifndef VCAST_USE_STDOUT
/* Normal case, uses a file for output */
#ifndef VCAST_UNIT_TEST_TOOL
#ifdef VCAST_USE_STDIO_OPS
#ifdef VCAST_SIMULINK_OUTPUT
#define VCAST_INST_FILE_TYPE unsigned short
#else
#ifndef VCAST_COVER_NO_STDIO
#define VCAST_INST_FILE_TYPE FILE*
#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_SIMULINK_OUTPUT */
#ifndef VCAST_COVER_NO_STDIO
unsigned short vCAST_INST_FILE_OPENED = 0;
VCAST_INST_FILE_TYPE vCAST_INST_FILE = 0;
#endif /* VCAST_COVER_NO_STDIO */

#ifndef VCAST_TESTINSS_FILE
#define VCAST_TESTINSS_FILE "TESTINSS.DAT"
#else
#define VCAST_CUSTOM_TESTINSS_FILE
#ifndef VCAST_MAX_PATH_LENGTH
#define VCAST_MAX_PATH_LENGTH 261
#endif
#endif

#ifndef VCAST_COVER_NO_STDIO
void vCAST_HANDLE_ERROR(const char *msg, const char *arg);
void vCAST_HANDLE_ERROR(const char *msg, const char *arg)
{
#ifdef VCAST_PRINT_ERROR
  fprintf(stderr, msg, arg);
#else
  /* write custom code here or set a breakpoint for debugging */
  if (msg && arg) {}
#endif
}
#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_USE_STDIO_OPS */
#endif /* VCAST_UNIT_TEST_TOOL */
#endif /* VCAST_USE_STDOUT */

#ifdef VCAST_DUMP_COVERAGE_AT_EXIT
int vcast_has_registered_atexit = 0;
void vcast_register_atexit(void);
void vcast_register_atexit(void) {
   atexit(VCAST_DUMP_COVERAGE_DATA);
}
#endif /* VCAST_DUMP_COVERAGE_AT_EXIT */

#ifndef VCAST_UNIT_TEST_TOOL
#ifndef VCAST_COVER_NO_STDIO
#ifndef VCAST_USE_STDOUT

/* use default linkage visibility for included headers */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility pop  
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#ifdef VCAST_APPEND_WIN32_PID
#include <windows.h>
#elif defined(VCAST_APPEND_POSIX_PID) || defined(VCAST_APPEND_POSIX_PID_AND_EPOCH)
#include <sys/types.h>
#include <unistd.h>
#endif /* end VCAST_APPEND_WIN32_PID */
 
/* return to "hidden" linkage for internal symbols */
#ifdef VCAST_HIDE_COVER_IO_SYMBOLS
#pragma GCC visibility push(hidden)
#endif /* VCAST_HIDE_COVER_IO_SYMBOLS */

#ifdef VCAST_COVERAGE_RESULTS_DIRECTORY
#ifndef VCAST_MAX_PATH_LENGTH
#define VCAST_MAX_PATH_LENGTH 261
#endif
#ifndef VCAST_ENV_VAR_NAME_MAX_LENGTH
#define VCAST_ENV_VAR_NAME_MAX_LENGTH 101
#endif

void vCAST_ENV_VAR_NAME(char* env_name, const char* src, int start_pos, int end_pos)
{
  int i = 0, char_pos = start_pos;
  while (char_pos < end_pos)
  {
    env_name[i++] = src[char_pos++];
    if (i >= VCAST_ENV_VAR_NAME_MAX_LENGTH - 1)
    {
      env_name[VCAST_ENV_VAR_NAME_MAX_LENGTH - 1] = '\0';
      if (!vCAST_INST_FILE_OPENED)
      {
        vCAST_HANDLE_ERROR("Environment variable name is too long, truncating to %s\n", env_name);
      }
      return;
    }
  }
  env_name[i] = '\0';
}

void vCAST_SHIFT_STRING_RIGHT_ONE(char* str, int start_pos)
{
  int i = vcast_strlen(str);
  str[i + 1] = '\0';
  while (i > start_pos)
  {
    str[i] = str[i - 1];
    --i;
  }
}

void vCAST_SHIFT_STRING_LEFT_ONE(char* str, int start_pos)
{
  int i = start_pos, end_pos = vcast_strlen(str);
  while (i < end_pos)
  {
    str[i] = str[i + 1];
    ++i;
  }
}

int vCAST_SUBST_STRING(const char* env_value, char* path, int start_pos, int end_pos)
{
  int env_var_name_size = end_pos - start_pos + 1;
  int env_var_val_size = env_value == NULL ? 0 : vcast_strlen(env_value);
  int string_size_change = env_var_val_size - env_var_name_size;
  int new_string_size = vcast_strlen(path) + string_size_change + 1;
  int i, j = 0;

  for (i = start_pos; i < new_string_size; ++i)
  {
    if (j < env_var_val_size)
    {
      if (i > end_pos)
        vCAST_SHIFT_STRING_RIGHT_ONE(path, i);

      path[i] = env_value[j++];
    }
    else if (i <= end_pos)
    {
      vCAST_SHIFT_STRING_LEFT_ONE(path, i--);
      --end_pos;
    }
    else
      break;
  }

  return end_pos + 1;
}

void vCAST_SUBST_ENV_VARS(char* path)
{
  char c = '\0';
  int i = 0;
  int env_var_start = 0;
  char env_name[VCAST_ENV_VAR_NAME_MAX_LENGTH];
  char* env_value;
  while ((c = path[i++]))
  {
    if (c == '$' && path[i] == '(')
    {
      env_var_start = i - 1;
      continue;
    }
    if (c == ')')
    {
      vCAST_ENV_VAR_NAME(env_name, path, env_var_start + 2, i - 1);
      env_value = getenv(env_name);
      i = vCAST_SUBST_STRING(env_value, path, env_var_start, i - 1);
    }

#if defined(VCAST_APPEND_WIN32_PID) || defined(VCAST_APPEND_POSIX_PID) || defined(VCAST_APPEND_SECONDS_SINCE_EPOCH) || \
  defined(VCAST_APPEND_WIN32_PID_AND_EPOCH) || defined(VCAST_APPEND_POSIX_PID_AND_EPOCH)
    if (i >= VCAST_MAX_PATH_LENGTH - 32)
#else
    if (i >= VCAST_MAX_PATH_LENGTH - 12)
#endif
    {
      path[VCAST_MAX_PATH_LENGTH - 1] = '\0';
      if (!vCAST_INST_FILE_OPENED)
      {
        vCAST_HANDLE_ERROR("Error: path %s is too long for buffer. Increase VCAST_MAX_PATH_LENGTH.\n", path);
      }
      path[0] = '\0';
      return;
    }
  }

  if (path[0])
  {
    if (path[i - 2] != VCAST_DIRECTORY_PATH_SEPARATOR)
    {
      path[i - 1] = VCAST_DIRECTORY_PATH_SEPARATOR;
      path[i] = '\0';
    }
  }
}
#endif

void vCAST_CREATE_INST_FILE (void);
/**
 * function to open the file that will get all the coverage data 
 * written to it. 
 *
 * @param  void 
 * @return void
 */
void vCAST_CREATE_INST_FILE (void)
{
#ifdef VCAST_CUSTOM_FILE_OUTPUT
  /* Insert your code here using your API to create the TESTINSS.DAT */
  /* file.  For example: my_fopen("TESTINSS.DAT");  */
  
  /* Use the vCAST_CREATE_INST_FILE() code below after the #else */
  /* as a guideline for what your code should do, e.g. set       */
  /* the file pointer vCAST_INST_FILE accordingly, if it         */
  /* hasn't already been set, and open for writing ("w")         */
  /* or appending ("a"). Then you can remove the #error line.     */

  /* Also set the defined variable: VCAST_CUSTOM_FILE_OUTPUT */
  /* in the VectorCAST Tool Options Dialog -> C/C++ tab */

#error You need to insert code in vCAST_CREATE_INST_FILE() function

#else
#ifdef VCAST_SIMULINK_OUTPUT
  /* Output using MATLAN Simulink integration */
  char buf[100];
  char result_filename[] = VCAST_TESTINSS_FILE;
  if (!vCAST_INST_FILE_OPENED) {
      vCAST_INST_FILE_OPENED = 1;
      vCAST_INST_FILE = targetFopen(result_filename);
  }
#else
#ifdef VCAST_USE_STDIO_OPS
#ifndef VCAST_COVERAGE_RESULTS_DIRECTORY
#ifndef VCAST_CUSTOM_TESTINSS_FILE
  char result_filename[32];
#else
  char result_filename[VCAST_MAX_PATH_LENGTH];
#endif
  result_filename[0] = '\0';
#else
  char result_filename[VCAST_MAX_PATH_LENGTH];
  result_filename[0] = '\0';
#if defined(VCAST_APPEND_WIN32_PID) || defined(VCAST_APPEND_POSIX_PID) || defined(VCAST_APPEND_SECONDS_SINCE_EPOCH) || \
  defined(VCAST_APPEND_WIN32_PID_AND_EPOCH) || defined(VCAST_APPEND_POSIX_PID_AND_EPOCH)
  if (vcast_strlen(VCAST_COVERAGE_RESULTS_DIRECTORY) > VCAST_MAX_PATH_LENGTH - 32)
#else
  if (vcast_strlen(VCAST_COVERAGE_RESULTS_DIRECTORY) > VCAST_MAX_PATH_LENGTH - 12)
#endif
  {
    if (!vCAST_INST_FILE_OPENED)
    {
      vCAST_HANDLE_ERROR("Error: path %s is too long for buffer. Increase VCAST_MAX_PATH_LENGTH.\n", VCAST_COVERAGE_RESULTS_DIRECTORY);
    }
  }
  else
    vcast_strcat(result_filename, VCAST_COVERAGE_RESULTS_DIRECTORY);
  vCAST_SUBST_ENV_VARS(result_filename);
#endif /* VCAST_COVERAGE_RESULTS_DIRECTORY */
#ifdef VCAST_APPEND_WIN32_PID
  sprintf (result_filename + vcast_strlen(result_filename),
           VCAST_PRINTF_STRING "-" VCAST_PRINTF_INTEGER "." VCAST_PRINTF_STRING,
           "TESTINSS",
           GetCurrentProcessId(), 
           "DAT");
#elif defined VCAST_APPEND_POSIX_PID
  sprintf (result_filename + vcast_strlen(result_filename),
           VCAST_PRINTF_STRING "-" VCAST_PRINTF_INTEGER "." VCAST_PRINTF_STRING,
           "TESTINSS",
           (int)getpid(),
           "DAT");
#elif defined VCAST_APPEND_SECONDS_SINCE_EPOCH
   sprintf(result_filename + vcast_strlen(result_filename),
           VCAST_PRINTF_STRING "-" VCAST_PRINTF_INTEGER "." VCAST_PRINTF_STRING,
           "TESTINSS",
           (int)time(0),
           "DAT");
#elif defined VCAST_APPEND_WIN32_PID_AND_EPOCH
  sprintf (result_filename + vcast_strlen(result_filename),
           VCAST_PRINTF_STRING "-" VCAST_PRINTF_INTEGER "-" VCAST_PRINTF_INTEGER "." VCAST_PRINTF_STRING,
           "TESTINSS",
           GetCurrentProcessId(), 
           (int)time(0),
           "DAT");
#elif defined VCAST_APPEND_POSIX_PID_AND_EPOCH
  sprintf (result_filename + vcast_strlen(result_filename),
           VCAST_PRINTF_STRING "-" VCAST_PRINTF_INTEGER "-" VCAST_PRINTF_INTEGER "." VCAST_PRINTF_STRING,
           "TESTINSS",
           (int)getpid(), 
           (int)time(0),
           "DAT");
#else
  vcast_strcat(result_filename, VCAST_TESTINSS_FILE);
#endif
   if (!vCAST_INST_FILE && !vCAST_INST_FILE_OPENED) {
      const char *vc_mode;
      vCAST_INST_FILE_OPENED = 1;
#ifdef VCAST_CUSTOM_CREATE_FILE_INCLUDE
#include VCAST_CUSTOM_CREATE_FILE_INCLUDE
#elif defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_COVERAGE_IO_BUFFERED)
      vc_mode = "wb";
#elif defined(VCAST_APPEND_TO_TESTINSS)
      vc_mode = "a";
#else /* VCAST_APPEND_TO_TESTINSS */
      vc_mode = "w";
#endif /* VCAST_APPEND_TO_TESTINSS */

#ifdef VCAST_USE_FOPEN_S
      fopen_s(&vCAST_INST_FILE, result_filename, vc_mode);
#else
      vCAST_INST_FILE = fopen(result_filename, vc_mode);
#endif

      if (!vCAST_INST_FILE)
      {
        vCAST_HANDLE_ERROR("Error: cannot open file %s\n", result_filename);
      }

#if defined(VCAST_USE_SETLINEBUF) || defined(VCAST_USE_SETVBUF) || defined(VCAST_USE_SETUNBUF)
#if defined(VCAST_USE_SETUNBUF)
#define VCAST_SETVBUF_MODE _IONBF
#else
#define VCAST_SETVBUF_MODE _IOLBF
#endif
      /* use if you expect harness to be killed before C library buffers can be flushed */
      setvbuf( vCAST_INST_FILE, NULL, VCAST_SETVBUF_MODE, 0 );
#endif /* VCAST_USE_SETLINEBUF || VCAST_USE_SETVBUF */

   }
#endif /* VCAST_USE_STDIO_OPS */
#endif /* VCAST_SIMULINK_OUTPUT */
#endif /* VCAST_CUSTOM_FILE_OUTPUT */
}

void VCAST_CLOSE_FILE (void);
 /**
 * function to close the file that has all the coverage data 
 * written in it. default file name is TESTINSS.DAT 
 *
 * @param  void
 * @return void
 */
void VCAST_CLOSE_FILE (void)
{
#ifdef VCAST_CUSTOM_CLOSE_FILE_INCLUDE
#include VCAST_CUSTOM_CLOSE_FILE_INCLUDE
#else
#ifdef VCAST_CUSTOM_FILE_OUTPUT
  /* Insert code here using your API to close the TESTINSS.DAT */
  /* file.  For example: "my_fclose(vCAST_INST_FILE);  */
  
  /* Use the vCAST_CLOSE_FILE() code after the #else       */
  /* below as a guideline for what your function should do */
  /* Then you can remove the #error line.                  */

  /* Also set the defined variable: VCAST_CUSTOM_FILE_OUTPUT */
  /* in the VectorCAST Tool Options Dialog -> C/C++ tab */

#error You need to insert code in VCAST_CLOSE_FILE() function

#else
#ifdef VCAST_SIMULINK_OUTPUT
  /* File automatically closed by Simulink */
#else
#ifdef VCAST_USE_STDIO_OPS
   if (vCAST_INST_FILE != (FILE*)0 )
      fclose(vCAST_INST_FILE);
   vCAST_INST_FILE = (FILE*)0;
   vCAST_INST_FILE_OPENED = 0;
#endif /* VCAST_USE_STDIO_OPS */
#endif /* VCAST_SIMULINK_OUTPUT */
#endif /* VCAST_CUSTOM_FILE_OUTPUT */
#endif /* VCAST_CUSTOM_CLOSE_FILE_INCLUDE */
}
#endif /* VCAST_USE_STDOUT */
#endif /* VCAST_COVER_NO_STDIO */

#ifdef VCAST_CUSTOM_STD_OUTPUT_EXTERNAL
void VCAST_CUSTOM_STD_OUTPUT_EXTERNAL (const char *S, int flush);
#endif /* VCAST_CUSTOM_STD_OUTPUT_EXTERNAL */

#ifdef VCAST_USE_GH_SYSCALL

#ifdef __cplusplus
extern "C" int __ghs_syscall(int, ...);
#else /* __cplusplus */
extern int __ghs_syscall(int, ...);
#endif /* __cplusplus */

#endif /* end VCAST_USE_GH_SYS_CALL */

#ifndef VCAST_COVER_NO_STDIO
void VCAST_WRITE_TO_INST_FILE_COVERAGE (const char *S, int flush);

 /**
 * Original vcast_write_to_inst_file function.  Currently used by default 
 * when coverage optimizations are turned off. 
 *
 * @param const char S[] string with single line of coverage data 
 * @param int flush  flag to cause data flush for file i/o if flush != 0
 * @return void
 */
void VCAST_WRITE_TO_INST_FILE_COVERAGE (const char *S, int flush)
{
#ifdef VCAST_USE_BUFFERED_ASCII_DATA
  VCAST_WRITE_TO_BUFFER(S);
#else /* VCAST_USE_BUFFERED_ASCII_DATA */
#ifdef VCAST_CUSTOM_FILE_OUTPUT
  /* Insert your own call to an API to write "S" out of your target */
  /* Note that you should append a carriage return "/n" to the end */
  /*      of the "S" string before printing           */

  /* For example: see code snippet below ...          */

  /*    vCAST_CREATE_INST_FILE();                     */
  /*    my_fprintf ( vCAST_INST_FILE, "%s\n", S );    */
  /*    if (flush) {                                  */
  /*        my_fflush (vCAST_INST_FILE);              */
  /*    }                                             */

  /* Then you can remove the #error line below.       */

  /* Also set the defined variable: VCAST_CUSTOM_FILE_OUTPUT */
  /* in the VectorCAST Tool Options Dialog -> C/C++ tab */

#error Need to insert file i/o code in VCAST_WRITE_TO_INST_FILE_COVERAGE() 

#else
#ifdef VCAST_SIMULINK_OUTPUT
   vCAST_CREATE_INST_FILE();
   targetFprintf ( vCAST_INST_FILE, VCAST_PRINTF_STRING "\n", S );
#else
#ifdef VCAST_USE_STDIO_OPS
#ifdef VCAST_USE_STDOUT
#ifdef VCAST_USE_PUTCHAR

   int i, len;
   len = vcast_strlen( S );
   for( i=0; i<len; ++i ) {
      putchar( S[i] );
   }
   putchar( '\n' );

#else /* ndef VCAST_USE_PUTCHAR */
#ifdef VCAST_USE_GH_SYSCALL

   char Str[42];
   int  Len = vcast_strlen (S);
   Str[0] = 0;
   vcast_strcat (Str, S);
   vcast_strcat (Str, "\n");
   /* we hardcode stdout (1) as the file handle */
   __ghs_syscall(0x40001, 1, Str, Len+1);
     
#else /* ndef VCAST_USE_GH_SYSCALL */    
#ifdef VCAST_CUSTOM_STD_OUTPUT
  /* Insert user code here to write "S" out to serial port  */
  /* or STDOUT of your target,                              */
  /* then you can remove the #error line below.             */
  /* you will have to cut&paste this serial port data from  */
  /* the application receiving the data (e.g. HyperTerminal */
  /* and put into a file that can be imported into Cover    */
  /* environment   */

  /* Also set the defined variable: VCAST_CUSTOM_STD_OUTPUT */
  /* in the VectorCAST Tool Options Dialog -> C/C++ tab */

  /* Need to also define VCAST_USE_STDOUT to set the stdout flag */

#ifdef VCAST_CUSTOM_STD_OUTPUT_EXTERNAL
  VCAST_CUSTOM_STD_OUTPUT_EXTERNAL (S, flush);
#else  /* ndef VCAST_CUSTOM_STD_OUTPUT_EXTERNAL */
#ifdef VCAST_CUSTOM_STD_OUTPUT_INCLUDE
#include VCAST_CUSTOM_STD_OUTPUT_INCLUDE
#else /* ndef VCAST_CUSTOM_STD_OUTPUT_INCLUDE */
#ifdef VCAST_CUSTOM_STD_OUTPUT_NONE
/* VCAST_WRITE_TO_INST_FILE_COVERAGE is not needed, therefore empty */
#else
 #error Need to insert serial/std i/o code in VCAST_WRITE_TO_INST_FILE_COVERAGE()
#endif /* end VCAST_CUSTOM_STD_OUTPUT_NONE */
#endif /* VCAST_CUSTOM_STD_OUTPUT_INCLUDE */
#endif /* end VCAST_CUSTOM_STD_OUTPUT_EXTERNAL */
#else
   puts( S );
#endif /* VCAST_CUSTOM_STD_OUTPUT */
     
#endif /* end VCAST_USE_GH_SYS_CALL */
#endif /* end VCAST_USE_PUTCHAR */

#else /* ndef VCAST_USE_STDOUT */

   vCAST_CREATE_INST_FILE();
   if (vCAST_INST_FILE)
   {
     fprintf ( vCAST_INST_FILE, VCAST_PRINTF_STRING "\n", S );
     if (flush) {
       fflush (vCAST_INST_FILE);
     }
#ifdef VCAST_FLUSH_DATA
     else {
       fflush (vCAST_INST_FILE);
     }
#endif /* VCAST_FLUSH_DATA */
   }
#endif /* end VCAST_USE_STDOUT */
#endif /* VCAST_USE_STDIO_OPS */
#endif /* VCAST_SIMULINK_OUTPUT */
#endif /* VCAST_CUSTOM_FILE_OUTPUT */
#endif /* VCAST_USE_BUFFERED_ASCII_DATA */
}
#endif /* VCAST_COVER_NO_STDIO */
#endif /* end VCAST_UNIT_TEST_TOOL */

#endif /*VCAST_COVER_IO_SYSTEM_CODE*/

#if (VCAST_COVER_IO_COVER_CODE == 1)

/* Include vcast_c_options.h again, this time for the cover variables. */
#define VCAST_DEFINE_COVER_VARIABLES 1
#include "vcast_c_options.h"
#ifdef VCAST_USE_STATIC_MEMORY
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
struct vcast_mcdc_statement vcast_mcdc_statement_pool[VCAST_MAX_MCDC_STATEMENTS];
struct vcast_mcdc_statement *vcast_mcdc_statement_pool_ptr = vcast_mcdc_statement_pool;
struct vcast_mcdc_statement *vcast_mcdc_statement_end = vcast_mcdc_statement_pool + VCAST_MAX_MCDC_STATEMENTS;
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
#endif /* VCAST_USE_STATIC_MEMORY */

void vcast_fatal_error (const char *msg);

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
static int vcast_max_mcdc_statements_exceeded = 0;
struct vcast_mcdc_statement *vcast_get_mcdc_statement (void);
struct vcast_mcdc_statement *
vcast_get_mcdc_statement (void)
{
  struct vcast_mcdc_statement *ptr;
#ifdef VCAST_USE_STATIC_MEMORY
  if (vcast_mcdc_statement_pool_ptr < vcast_mcdc_statement_pool ||
      vcast_mcdc_statement_pool_ptr >= vcast_mcdc_statement_end)
  {
    if (vcast_max_mcdc_statements_exceeded == 0)
	   vcast_fatal_error ("VCAST_MAX_MCDC_STATEMENTS exceeded!");
    vcast_max_mcdc_statements_exceeded = 1;
    return 0;
  }
  ptr = vcast_mcdc_statement_pool_ptr++;
#else /* VCAST_USE_STATIC_MEMORY */
  ptr = (struct vcast_mcdc_statement*) 
    VCAST_malloc (sizeof (struct vcast_mcdc_statement));
#endif /* VCAST_USE_STATIC_MEMORY */

  return ptr;
}
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

struct VCAST_AVLNode
{
  VCAST_elementType element;
  VCAST_AVLTree left;
  VCAST_AVLTree right;
  int vcast_height;
};
#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#ifdef VCAST_USE_STATIC_MEMORY
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
struct VCAST_AVLNode vcast_avlnode_pool[VCAST_MAX_MCDC_STATEMENTS];
VCAST_AVLTree vcast_avlnode_pool_ptr = vcast_avlnode_pool;
VCAST_AVLTree vcast_avlnode_pool_end = vcast_avlnode_pool + VCAST_MAX_MCDC_STATEMENTS;
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
#endif /* VCAST_USE_STATIC_MEMORY */

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
VCAST_AVLTree vcast_getVCAST_AVLTree (void);
VCAST_AVLTree
vcast_getVCAST_AVLTree (void)
{
  VCAST_AVLTree ptr;
#ifdef VCAST_USE_STATIC_MEMORY
  if (vcast_avlnode_pool_ptr < vcast_avlnode_pool || vcast_avlnode_pool_ptr >= vcast_avlnode_pool_end)
    return 0;
  ptr = vcast_avlnode_pool_ptr++;
#else /* VCAST_USE_STATIC_MEMORY */
  ptr = (struct VCAST_AVLNode *)VCAST_malloc (sizeof (struct VCAST_AVLNode));
#endif /* VCAST_USE_STATIC_MEMORY */

  return ptr;
}
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#ifdef VCAST_USE_BUFFERED_ASCII_DATA
char VCAST_ATTRIBUTE_CODE vcast_ascii_coverage_data_pool[VCAST_MAX_CAPTURED_ASCII_DATA];

void VCAST_WRITE_TO_BUFFER(const char *S){
  if (!vcast_coverage_data_buffer_full) {
    int vc_size = vcast_strlen(S);
    if (vcast_ascii_coverage_data_pos + vc_size + 2 >= VCAST_MAX_CAPTURED_ASCII_DATA) {
       vcast_coverage_data_buffer_full = 1;
    } else {
       while (*S) {
         vcast_ascii_coverage_data_pool[vcast_ascii_coverage_data_pos++] = *S;
         ++S;
       }
    }

    /* if not enough room in the buffer for all the coverage data */
    if (vcast_coverage_data_buffer_full) {
      const char *vcast_cur = VCAST_MAX_CAPTURED_ASCII_DATA_EXCEEDED_ERROR;
      vcast_ascii_coverage_data_pos -= (vcast_max_captured_ascii_data_exceeded_error_size+2);
      for (; *vcast_cur; ++vcast_cur) {
        vcast_ascii_coverage_data_pool[vcast_ascii_coverage_data_pos++] = *vcast_cur;
      }
    }

    vcast_ascii_coverage_data_pool[vcast_ascii_coverage_data_pos++] = '\n';
    vcast_ascii_coverage_data_pool[vcast_ascii_coverage_data_pos] = '\0';
  }
}
#endif /* VCAST_USE_BUFFERED_ASCII_DATA */

#if defined VCAST_UNIT_TEST_TOOL
#define VCAST_WRITE_COVERAGE_DATA(string) { vCAST_CREATE_INST_FILE(); vectorcast_fprint_string_with_cr(vCAST_INST_FILE, string); }
#define VCAST_WRITE_COVERAGE_DATA_FLUSH(string) { vCAST_CREATE_INST_FILE(); vectorcast_fprint_string_with_cr(vCAST_INST_FILE, string); }
#else /* VCAST_UNIT_TEST_TOOL */
#ifndef VCAST_COVER_NO_STDIO
#define VCAST_WRITE_COVERAGE_DATA(string) (VCAST_WRITE_TO_INST_FILE_COVERAGE(string, 0))
#define VCAST_WRITE_COVERAGE_DATA_FLUSH(string) (VCAST_WRITE_TO_INST_FILE_COVERAGE(string, 1))
#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_UNIT_TEST_TOOL */

/* The instrumentation code depends on this data, usually found in S2.c in a
 * test harness.  For standalone coverage, they need to be supplied here: */
#ifndef LONG_MAX
#define LONG_MAX 2147483647L
#endif /* LONG_MAX */

/*
   VCAST_UNIQUE_ID_BUF_SIZE        : The number of characters needed to print
                                     a unique id. The default is 10, which 
                                     supports 999,999,999 ids in a single unit.
   VCAST_UNIT_ID_BUF_SIZE          : The number of characters needed to print
                                     a unit id. The default is 10, which
                                     supports 2,147,483,647 units in a project.
*/

/* The following defines will control the sizes of intermediate character 
 * strings that VectorCAST uses to output coverage data. Keeping these 
 * values close to the sizes needed results in less memory being used 
 * on the stack, during test execution.
 */
#ifndef VCAST_UNIQUE_ID_BUF_SIZE
#define VCAST_UNIQUE_ID_BUF_SIZE 10
#endif

#define VCAST_UNIT_ID_BUF_SIZE 10

/* The amount of space needed to write a line of statement data is,
 * The size of the unit id, plus a space, plus the size of the 
 * unique id, plus the NUL character.
 */
#define VCAST_STATEMENT_DATA_BUF_SIZE (VCAST_UNIQUE_ID_BUF_SIZE + 1 \
+ VCAST_UNIT_ID_BUF_SIZE + 1)

/* The branch data is the same as the statement data, except it has an
 * extra space, and then an extra character or two (T, F, TX, or FX) at
 * the end.
 */
#define VCAST_BRANCH_DATA_BUF_SIZE (VCAST_STATEMENT_DATA_BUF_SIZE + 3)

/* The user can never go above the maximum of the supported 64 bit
 * limit, which is 18446744073709551615.
 */
#if defined(VCAST_UNSIGNED_LONG_MCDC_STORAGE) || !defined(VCAST_HAS_LONGLONG)
#define VCAST_MCDC_ID_BUF_SIZE 11
#else
#define VCAST_MCDC_ID_BUF_SIZE 21
#endif

/* The mcdc data is the same as the statement data, except that
 * it has an extra space, plus a mcdc bits number, plus a space,
 * plus an mcdc bits used number.
 */
#define VCAST_MCDC_DATA_BUF_SIZE (VCAST_STATEMENT_DATA_BUF_SIZE + 1 + \
VCAST_MCDC_ID_BUF_SIZE + 1 + VCAST_MCDC_ID_BUF_SIZE)

/* The function call data is the same as the statement data, except it has a
 * 'F' character instead of the space.
 */
#define VCAST_FUNCTION_DATA_BUF_SIZE VCAST_STATEMENT_DATA_BUF_SIZE

/* The function call data is the same as the statement data, except it has a
 * 'C' character instead of the space.
 */
#define VCAST_FN_CALL_DATA_BUF_SIZE VCAST_STATEMENT_DATA_BUF_SIZE

#ifndef VCAST_COVER_NO_STDIO
#if defined(VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) ||        \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) ||      \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) ||  \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) ||      \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_FN_CALL_ID(int id)
{
   char vcast_out_str[VCAST_FN_CALL_DATA_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, id);
   vcast_strcat(vcast_out_str, "C");
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_FN_CALL_ID(int unit, int id)
{
   char vcast_out_str[VCAST_FN_CALL_DATA_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, unit);
   vcast_int_to_string(id_buf, id);
   vcast_strcat(vcast_out_str, "C");
   vcast_strcat(vcast_out_str, id_buf);
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL */

#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_STATEMENT_ID(int id)
{
   char vcast_out_str[VCAST_STATEMENT_DATA_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, id);
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_STATEMENT_ID(int unit, int id)
{
   char vcast_out_str[VCAST_STATEMENT_DATA_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, unit);
   vcast_int_to_string(id_buf, id);
   vcast_strcat(vcast_out_str, " ");
   vcast_strcat(vcast_out_str, id_buf);
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif

#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_BRANCH_ID(int id, const char *TorF)
{
   char vcast_out_str[VCAST_BRANCH_DATA_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, id);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, TorF);
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_BRANCH_ID(int unit, int id, const char *TorF)
{
   char vcast_out_str[VCAST_BRANCH_DATA_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, unit);
   vcast_int_to_string(id_buf, id);
   vcast_strcat(vcast_out_str, " ");
   vcast_strcat(vcast_out_str, id_buf);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, TorF);
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif

#if defined(VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#if defined(VCAST_USE_STANDARD_MCDC_INSTRUMENTATION) || defined(VCAST_COVERAGE_IO_ANIMATION)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_MCDC_ID(int id,
                               VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                               VCAST_MCDC_STORAGE_TYPE mcdc_bits_used);
int VCAST_WRITE_GLOBAL_MCDC_ID(int id,
                               VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                               VCAST_MCDC_STORAGE_TYPE mcdc_bits_used)
{
   char vcast_out_str[VCAST_MCDC_DATA_BUF_SIZE];
   char mcdc_bits_buf[VCAST_MCDC_ID_BUF_SIZE]; 
   char mcdc_bits_used_buf[VCAST_MCDC_ID_BUF_SIZE];

   vcast_int_to_string (vcast_out_str, id);
#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
   vcast_strcat (vcast_out_str, "V");
#else
   vcast_strcat (vcast_out_str, "G");
#endif
   vcast_int_to_string (mcdc_bits_buf, mcdc_bits);
   vcast_strcat (vcast_out_str, mcdc_bits_buf);
   vcast_int_to_string (mcdc_bits_used_buf, mcdc_bits_used);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_used_buf);
   VCAST_WRITE_COVERAGE_DATA (vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_MCDC_ID(int unit, int id,
                        VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                        VCAST_MCDC_STORAGE_TYPE mcdc_bits_used);
int VCAST_WRITE_MCDC_ID(int unit, int id,
                        VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                        VCAST_MCDC_STORAGE_TYPE mcdc_bits_used)
{
   char vcast_out_str[VCAST_MCDC_DATA_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE]; 
   char mcdc_bits_buf[VCAST_MCDC_ID_BUF_SIZE]; 
   char mcdc_bits_used_buf[VCAST_MCDC_ID_BUF_SIZE];

   vcast_int_to_string (vcast_out_str, unit);
   vcast_int_to_string (id_buf, id);
#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
   vcast_strcat (vcast_out_str, "V");
#else
   vcast_strcat (vcast_out_str, " ");
#endif
   vcast_strcat (vcast_out_str, id_buf);
   vcast_int_to_string (mcdc_bits_buf, mcdc_bits);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_buf);
   vcast_int_to_string (mcdc_bits_used_buf, mcdc_bits_used);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_used_buf);
   VCAST_WRITE_COVERAGE_DATA (vcast_out_str);
   return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #if defined(VCAST_USE_STANDARD_MCDC_INSTRUMENTATION) || defined(VCAST_COVERAGE_IO_ANIMATION) */

#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID(int id, char num_conditions,
                                     VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                                     VCAST_MCDC_STORAGE_TYPE mcdc_bits_used)
{
   char vcast_out_str[VCAST_MCDC_DATA_BUF_SIZE + 1];
   char num_cond_buf[2];
   char mcdc_bits_buf[VCAST_MCDC_ID_BUF_SIZE]; 
   char mcdc_bits_used_buf[VCAST_MCDC_ID_BUF_SIZE];

   vcast_int_to_string (vcast_out_str, id);
   num_cond_buf[0] = num_conditions;
   num_cond_buf[1] = '\0';
   vcast_strcat (vcast_out_str, num_cond_buf);
   vcast_int_to_string (mcdc_bits_buf, mcdc_bits);
   vcast_strcat (vcast_out_str, mcdc_bits_buf);
   vcast_int_to_string (mcdc_bits_used_buf, mcdc_bits_used);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_used_buf);
   VCAST_WRITE_COVERAGE_DATA (vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_OPTIMIZED_MCDC_ID(int unit, int id, char num_conditions,
                                  VCAST_MCDC_STORAGE_TYPE mcdc_bits, 
                                  VCAST_MCDC_STORAGE_TYPE mcdc_bits_used)
{
   char vcast_out_str[VCAST_MCDC_DATA_BUF_SIZE + 1];
   char num_cond_buf[2];
   char mcdc_bits_buf[VCAST_MCDC_ID_BUF_SIZE]; 
   char mcdc_bits_used_buf[VCAST_MCDC_ID_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE]; 
   vcast_int_to_string (vcast_out_str, unit);
   vcast_int_to_string (id_buf, id);
   num_cond_buf[0] = num_conditions;
   num_cond_buf[1] = '\0';
   vcast_strcat (vcast_out_str, num_cond_buf);
   vcast_strcat (vcast_out_str, id_buf);
   vcast_int_to_string (mcdc_bits_buf, mcdc_bits);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_buf);
   vcast_int_to_string (mcdc_bits_used_buf, mcdc_bits_used);
   vcast_strcat (vcast_out_str, " ");
   vcast_strcat (vcast_out_str, mcdc_bits_used_buf);
   VCAST_WRITE_COVERAGE_DATA (vcast_out_str);
   return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /*mcdc*/

#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined (VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL ) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_WRITE_GLOBAL_FUNCTION_ID(int id)
{
   char vcast_out_str[VCAST_FUNCTION_DATA_BUF_SIZE];
   vcast_int_to_string(vcast_out_str, id);
   vcast_strcat(vcast_out_str, "F");
   VCAST_WRITE_COVERAGE_DATA(vcast_out_str);
   return 1;
}
#else
int VCAST_WRITE_FUNCTION_ID(int unit, int id)
{
   char vcast_out_str[VCAST_FUNCTION_DATA_BUF_SIZE];
   char id_buf[VCAST_UNIQUE_ID_BUF_SIZE];
   vcast_int_to_string (vcast_out_str, unit);
   vcast_int_to_string (id_buf, id);
   vcast_strcat (vcast_out_str, "F");
   vcast_strcat (vcast_out_str, id_buf);
   VCAST_WRITE_COVERAGE_DATA (vcast_out_str);
   return 0;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION */

void
vcast_fatal_error (const char *msg)
{
#if !defined(VCAST_DUMP_BINARY_COVERAGE) || !defined(VCAST_COVERAGE_IO_BUFFERED)
  VCAST_WRITE_COVERAGE_DATA_FLUSH (msg);
#endif
}
#endif /* VCAST_COVER_NO_STDIO */

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
int vcast_mcdc_statement_compare (struct vcast_mcdc_statement *ptr1,
                                  struct vcast_mcdc_statement *ptr2);
int
vcast_mcdc_statement_compare (struct vcast_mcdc_statement *ptr1,
                        struct vcast_mcdc_statement *ptr2)
{
  if (ptr1->mcdc_bits == ptr2->mcdc_bits)
  {
    if (ptr1->mcdc_bits_used == ptr2->mcdc_bits_used)
      return 0;
    else if (ptr1->mcdc_bits_used < ptr2->mcdc_bits_used)
      return -1;
    else
      return 1;
  } else if (ptr1->mcdc_bits < ptr2->mcdc_bits)
    return -1;
  else
    return 1;
}
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP
VCAST_SAVE_MCDC_SUBCONDITION (struct vcast_mcdc_statement *mcdc_statement,
                              int bit_index, VCAST_CONDITION_TYP condition)
{
   /* This is a sub-condition for an MCDC expression, just record the bit */
  if (condition)
    mcdc_statement->mcdc_bits |= (VCAST_UNSIGNED_1 << bit_index);

  mcdc_statement->mcdc_bits_used |= (VCAST_UNSIGNED_1 << bit_index);

  return condition;
}
#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#if defined VCAST_COVERAGE_TYPE_STATEMENT_MCDC || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL)  || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
VCAST_CONDITION_TYP
VCAST_SAVE_MCDC_STATEMENT_MCDC_SUBCONDITION ( 
                              struct vcast_mcdc_statement *mcdc_statement,
                              int bit_index, VCAST_CONDITION_TYP condition);
VCAST_CONDITION_TYP
VCAST_SAVE_MCDC_STATEMENT_MCDC_SUBCONDITION ( 
                              struct vcast_mcdc_statement *mcdc_statement,
                              int bit_index, VCAST_CONDITION_TYP condition)
{
   /* This is a sub-condition for an MCDC expression, just record the bit */
  if (condition)
    mcdc_statement->mcdc_bits |= (VCAST_UNSIGNED_1 << bit_index);

  mcdc_statement->mcdc_bits_used |= (VCAST_UNSIGNED_1 << bit_index);

  return condition;
}

#endif /* VCAST_COVERAGE_TYPE_STATEMENT_MCDC */

#ifdef VCAST_COVERAGE_IO_REAL_TIME
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
VCAST_CONDITION_TYP 
VCAST_GLOBAL_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME(struct vcast_mcdc_statement *mcdc_statement,
                                                           int id,
                                                           VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   /* Get the coverage data necessary */
   if (!vcast_find (mcdc_statement, vcast_mcdc_bytes[id]))
   {
      struct vcast_mcdc_statement *vcast_mcdc_statement = vcast_get_mcdc_statement();
      if (!vcast_mcdc_statement)
        return condition;
      *vcast_mcdc_statement = *mcdc_statement;

      vcast_mcdc_bytes[id] = 
         vcast_insert (vcast_mcdc_statement, vcast_mcdc_bytes[id]);

      VCAST_WRITE_GLOBAL_MCDC_ID (id,
            mcdc_statement->mcdc_bits,
            mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CONDITION_TYP 
VCAST_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME(VCAST_AVLTree *vcast_mcdc_array,
                                                    struct vcast_mcdc_statement *mcdc_statement,
                                                    int unit, int id,
                                                    VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   /* Get the coverage data necessary */
   if (!vcast_find (mcdc_statement, vcast_mcdc_array[id]))
   {
      struct vcast_mcdc_statement *vcast_mcdc_statement = vcast_get_mcdc_statement();
      if (!vcast_mcdc_statement)
        return condition;
      *vcast_mcdc_statement = *mcdc_statement;

      vcast_mcdc_array[id] = 
         vcast_insert (vcast_mcdc_statement, vcast_mcdc_array[id]);

      VCAST_WRITE_MCDC_ID (unit, id,
            mcdc_statement->mcdc_bits,
            mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#ifndef VCAST_COVERAGE_POINTS_AS_MACROS
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME_0(int id,
                                                                       VCAST_CONDITION_TYP condition)
{
   return condition ?
      (((vcast_coverage_bytes[id >> 2] & ((((unsigned long)0x3) << ((id << 1) % 8)))) == 0) ?
       (vcast_coverage_bytes[id >> 2] |= (char)((((unsigned long)0x3) << ((id << 1) % 8))),
        VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID(id, 'a', 1, 1), 1) : 1)
      :
      (((vcast_coverage_bytes[id >> 2] & ((((unsigned long)0x1) << ((id << 1) % 8)))) == 0) ?
       (vcast_coverage_bytes[id >> 2] |= (char)((((unsigned long)0x1) << ((id << 1) % 8))),
        VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID(id, 'a', 0, 1), 0) : 0);
}
#else
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME_0(char* covdata,
                                                                int unit, int id,
                                                                VCAST_CONDITION_TYP condition)
{
   return condition ?
      (((covdata[id >> 2] & ((((unsigned long)0x3) << ((id << 1) % 8)))) == 0) ?
       (covdata[id >> 2] |= (char)((((unsigned long)0x3) << ((id << 1) % 8))),
        VCAST_WRITE_OPTIMIZED_MCDC_ID(unit, id, 'a', 1, 1), 1) : 1)
      :
      (((covdata[id >> 2] & ((((unsigned long)0x1) << ((id << 1) % 8)))) == 0) ?
       (covdata[id >> 2] |= (char)((((unsigned long)0x1) << ((id << 1) % 8))),
        VCAST_WRITE_OPTIMIZED_MCDC_ID(unit, id, 'a', 0, 1), 0) : 0);
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifndef VCAST_COVERAGE_POINTS_AS_MACROS */

#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME_1(struct vcast_mcdc_statement *mcdc_statement,
                                                                       int id,
                                                                       VCAST_CONDITION_TYP condition)
{
   int bits_needed = 4;
   int bit_offset = id * bits_needed;
   int cond_result_start = bit_offset + 2;
   int actual_result = 0;
   int cond_val = 0;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = (int)mcdc_statement->mcdc_bits >> 1;

   if (! (vcast_coverage_bytes[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8))))
   {
     vcast_coverage_bytes[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
     vcast_coverage_bytes[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));

     VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID (id, 'b',
                                       mcdc_statement->mcdc_bits,
                                       mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME_1(char* covdata,
                                                                struct vcast_mcdc_statement *mcdc_statement,
                                                                int unit, int id,
                                                                VCAST_CONDITION_TYP condition)
{
   int bits_needed = 4;
   int bit_offset = id * bits_needed;
   int cond_result_start = bit_offset + 2;
   int actual_result = 0;
   int cond_val = 0;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = (int)mcdc_statement->mcdc_bits >> 1;

   if (! (covdata[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8))))
   {
     covdata[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
     covdata[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));

     VCAST_WRITE_OPTIMIZED_MCDC_ID (unit, id, 'b',
                               mcdc_statement->mcdc_bits,
                               mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */

#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME(char* covdata,
                                                                     struct vcast_mcdc_statement *mcdc_statement,
                                                                     int id, int num_conditions,
                                                                     VCAST_CONDITION_TYP condition)
{
   int bits_needed = (1 << num_conditions) * (num_conditions + 1);
   int bit_offset = 0;
   int cond_result_start = 0;
   int used_start = 0;
   int actual_result = 0;
   int cond_val = 0;
   int used_val = 0;
   int i;

   if (bits_needed == 1)
     bits_needed = 2;

   bit_offset = id * bits_needed;
   cond_result_start = bit_offset + (1 << num_conditions);

   if (bits_needed == 2)
     --cond_result_start;

   used_start = bit_offset + (1 << (num_conditions + 1));

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = (int)mcdc_statement->mcdc_bits >> 1;
   used_val = (int)mcdc_statement->mcdc_bits_used >> 2;

   if (! (covdata[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8))))
   {
     covdata[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
     covdata[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));

     for (i = 0; i < num_conditions - 1; ++i)
       covdata[(used_start + cond_val + i * (1 << num_conditions)) >> 3] |= (char)(((1 & (used_val >> i))) << ((used_start + cond_val + i * (1 << num_conditions)) % 8));

     VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID (id, (char)(num_conditions + 97),
                                       mcdc_statement->mcdc_bits,
                                       mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_REALTIME(char* covdata,
                                                              struct vcast_mcdc_statement *mcdc_statement,
                                                              int unit, int id, int num_conditions,
                                                              VCAST_CONDITION_TYP condition)
{
   int bits_needed = (1 << num_conditions) * (num_conditions + 1);
   int bit_offset = 0;
   int cond_result_start = 0;
   int used_start = 0;
   int actual_result = 0;
   int cond_val = 0;
   int used_val = 0;
   int i;

   if (bits_needed == 1)
     bits_needed = 2;

   bit_offset = id * bits_needed;
   cond_result_start = bit_offset + (1 << num_conditions);

   if (bits_needed == 2)
     --cond_result_start;

   used_start = bit_offset + (1 << (num_conditions + 1));

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = (int)mcdc_statement->mcdc_bits >> 1;
   used_val = (int)mcdc_statement->mcdc_bits_used >> 2;

   if (! (covdata[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8))))
   {
     covdata[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
     covdata[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));

     for (i = 0; i < num_conditions - 1; ++i)
       covdata[(used_start + cond_val + i * (1 << num_conditions)) >> 3] |= (char)(((1 & (used_val >> i))) << ((used_start + cond_val + i * (1 << num_conditions)) % 8));

     VCAST_WRITE_OPTIMIZED_MCDC_ID (unit, id, (char)(num_conditions + 97),
                                    mcdc_statement->mcdc_bits,
                                    mcdc_statement->mcdc_bits_used);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif /* VCAST_COVERAGE_IO_REAL_TIME */
#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */


/***************************** Functions for MCDC Coverage **************************************** */
/***************************** Functions for MCDC Coverage **************************************** */

#if defined(VCAST_COVERAGE_IO_ANIMATION)
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CONDITION_TYP 
VCAST_GLOBAL_MCDC_CONDITION_INSTRUMENTATION_POINT_ANIMATION(
                             struct vcast_mcdc_statement *mcdc_statement,
                             int id, VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   VCAST_WRITE_GLOBAL_MCDC_ID (id, mcdc_statement->mcdc_bits,
                               mcdc_statement->mcdc_bits_used);

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}

#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_ANIMATION(struct vcast_mcdc_statement *mcdc_statement,
                                                                      int id,
                                                                      int num_conditions,
                                                                      VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID (id, (char)(num_conditions + 97),
                                         mcdc_statement->mcdc_bits,
                                         mcdc_statement->mcdc_bits_used);

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#else
VCAST_CONDITION_TYP 
VCAST_MCDC_CONDITION_INSTRUMENTATION_POINT_ANIMATION(
                             struct vcast_mcdc_statement *mcdc_statement,
                             int unit_index,
                             int id, VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   VCAST_WRITE_MCDC_ID (unit_index, id, mcdc_statement->mcdc_bits,
                        mcdc_statement->mcdc_bits_used);

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}

#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_ANIMATION(struct vcast_mcdc_statement *mcdc_statement,
                                                               int unit, int id,
                                                               int num_conditions,
                                                               VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   VCAST_WRITE_OPTIMIZED_MCDC_ID (unit, id, (char)(num_conditions + 97),
                             mcdc_statement->mcdc_bits,
                             mcdc_statement->mcdc_bits_used);

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
#endif /* VCAST_COVERAGE_IO_ANIMATION */

#if defined (VCAST_COVERAGE_IO_BUFFERED)
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_GLOBAL_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED(struct vcast_mcdc_statement *mcdc_statement,
                                                           int id,
                                                           VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   /* Get the coverage data necessary */
   if (!vcast_find (mcdc_statement, vcast_mcdc_bytes[id]))
   {
      struct vcast_mcdc_statement *vcast_mcdc_statement = vcast_get_mcdc_statement();
      if (!vcast_mcdc_statement)
        return condition;
      *vcast_mcdc_statement = *mcdc_statement;

      vcast_mcdc_bytes[id] = 
         vcast_insert (vcast_mcdc_statement, vcast_mcdc_bytes[id]);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED(VCAST_AVLTree *vcast_mcdc_array,
                                                    struct vcast_mcdc_statement *mcdc_statement,
                                                    int id,
                                                    VCAST_CONDITION_TYP condition)
{
   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   /* Get the coverage data necessary */
   if (!vcast_find (mcdc_statement, vcast_mcdc_array[id]))
   {
      struct vcast_mcdc_statement *vcast_mcdc_statement = vcast_get_mcdc_statement();
      if (!vcast_mcdc_statement)
        return condition;
      *vcast_mcdc_statement = *mcdc_statement;

      vcast_mcdc_array[id] = 
         vcast_insert (vcast_mcdc_statement, vcast_mcdc_array[id]);
   }

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#ifndef VCAST_COVERAGE_POINTS_AS_MACROS
#ifdef VCAST_CUDA
#undef VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_0
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_0(int id,
                                                                       VCAST_CONDITION_TYP condition)
{
   return condition ?
      (vcast_coverage_bytes[id >> 2] |= ((((unsigned long)0x3) << ((id << 1) % 8))), 1)
      :
      (vcast_coverage_bytes[id >> 2] |= ((((unsigned long)0x1) << ((id << 1) % 8))), 0);
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_0(char* covdata,
                                                                int id,
                                                                VCAST_CONDITION_TYP condition)
{
/* CUDA requires 'atomicOr' to handle race conditions */
#ifdef __CUDA_ARCH__
    return condition ? \
      (atomicOr(&(((int*)(covdata))[id >> 4]), (((unsigned long)0x3) << ((id << 1) % 32))), 1)
      :
      (atomicOr(&(((int*)(covdata))[id >> 4]), (((unsigned long)0x1) << ((id << 1) % 32))), 0);
#else
   return condition ?
      (covdata[id >> 2] |= (char)((((unsigned long)0x3) << ((id << 1) % 8))), 1)
      :
      (covdata[id >> 2] |= (char)((((unsigned long)0x1) << ((id << 1) % 8))), 0);
#endif
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifndef VCAST_COVERAGE_POINTS_AS_MACROS */

#ifdef VCAST_CUDA
#undef VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_1
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_1(struct vcast_mcdc_statement *mcdc_statement,
                                                                       int id,
                                                                       VCAST_CONDITION_TYP condition)
{
   int bits_needed = 4;
   int bit_offset = id * bits_needed;
   int cond_result_start = bit_offset + 2;
   int actual_result = 0;
   int cond_val = 0;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = mcdc_statement->mcdc_bits >> 1;

   vcast_coverage_bytes[(bit_offset + cond_val) >> 3] |= (1 << ((bit_offset + cond_val) % 8));
   vcast_coverage_bytes[(cond_result_start + cond_val) >> 3] |= (actual_result << ((cond_result_start + cond_val) % 8));

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED_1(char* covdata,
                                                                struct vcast_mcdc_statement *mcdc_statement,
                                                                int id,
                                                                VCAST_CONDITION_TYP condition)
{
   int bits_needed = 4;
   int bit_offset = id * bits_needed;
   int cond_result_start = bit_offset + 2;
   int actual_result = 0;
   int cond_val = 0;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   actual_result = mcdc_statement->mcdc_bits & 1;
   cond_val = (int)mcdc_statement->mcdc_bits >> 1;

/* CUDA requires 'atomicOr' to handle race conditions */
#ifdef __CUDA_ARCH__
   int *ptr = &((int*)covdata)[bit_offset >> 5];
   int  val  = 1 << ((bit_offset + cond_val) % 32);
   val  |= actual_result << ((cond_result_start + cond_val) % 32);
   atomicOr((int*)ptr, val);
#else
   covdata[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
   covdata[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));
#endif

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */

#ifdef VCAST_CUDA
#undef VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_GLOBAL_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED(char* covdata,
                                                                     struct vcast_mcdc_statement *mcdc_statement,
                                                                     int id,
                                                                     int num_conditions,
                                                                     VCAST_CONDITION_TYP condition)
{
   int bits_needed = (1 << num_conditions) * (num_conditions + 1);
   int bit_offset = 0;
   int cond_result_start = 0;
   int used_start = 0;
   int actual_result = 0;
   int cond_val = 0;
   int used_val = 0;
   int i;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   if (bits_needed == 1)
     bits_needed = 2;
   bit_offset = id * bits_needed;

   cond_result_start = bit_offset + (1 << num_conditions);
   if (bits_needed == 2)
     --cond_result_start;
   used_start = bit_offset + (1 << (num_conditions + 1));
   actual_result = mcdc_statement->mcdc_bits & 1;

   cond_val = mcdc_statement->mcdc_bits >> 1;
   used_val = mcdc_statement->mcdc_bits_used >> 2;

   covdata[(bit_offset + cond_val) >> 3] |= (1 << ((bit_offset + cond_val) % 8));
   covdata[(cond_result_start + cond_val) >> 3] |= (actual_result << ((cond_result_start + cond_val) % 8));

   for (i = 0; i < num_conditions - 1; ++i)
     covdata[(used_start + cond_val + i * (1 << num_conditions)) >> 3] |= (((1 & (used_val >> i))) << ((used_start + cond_val + i * (1 << num_conditions)) % 8));

   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
VCAST_CONDITION_TYP 
VCAST_OPTIMIZED_MCDC_CONDITION_INSTRUMENTATION_POINT_BUFFERED(char* covdata,
                                                              struct vcast_mcdc_statement *mcdc_statement,
                                                              int id,
                                                              int num_conditions,
                                                              VCAST_CONDITION_TYP condition)
{
   int bits_needed = (1 << num_conditions) * (num_conditions + 1);
   int bit_offset = 0;
   int cond_result_start = 0;
   int used_start = 0;
   int actual_result = 0;
   int cond_val = 0;
   int used_val = 0;
   int i;

   /* Store the total expression */
   if (condition)
     mcdc_statement->mcdc_bits |= 1;
   mcdc_statement->mcdc_bits_used |= 1;

   if (bits_needed == 1)
     bits_needed = 2;
   bit_offset = id * bits_needed;

   cond_result_start = bit_offset + (1 << num_conditions);
   if (bits_needed == 2)
     --cond_result_start;
   used_start = bit_offset + (1 << (num_conditions + 1));
   actual_result = mcdc_statement->mcdc_bits & 1;

   cond_val = (int)mcdc_statement->mcdc_bits >> 1;
   used_val = (int)mcdc_statement->mcdc_bits_used >> 2;

/* CUDA requires 'atomicOr' to handle race conditions */
#ifdef __CUDA_ARCH__
   {
     int *ptr = &((int*)covdata)[(bit_offset + cond_val) >> 5];
     int  val  = 1 << ((bit_offset + cond_val) % 32);
     atomicOr ( (int*)ptr, val );
   }
   {
     int *ptr = &((int*)covdata)[(cond_result_start + cond_val) >> 5];
     int  val  = actual_result << ((cond_result_start + cond_val) % 32);
     atomicOr ( (int*)ptr, val );
   }

   for (i = 0; i < num_conditions - 1; ++i) {
     int *ptr = &((int*)covdata)[(used_start + cond_val + i * (1 << num_conditions)) >> 5];
     int  val  = (((1 & (used_val >> i))) << ((used_start + cond_val + i * (1 << num_conditions)) % 32));
     atomicOr ( (int*)ptr, val );
   }
#else
   covdata[(bit_offset + cond_val) >> 3] |= (char)(1 << ((bit_offset + cond_val) % 8));
   covdata[(cond_result_start + cond_val) >> 3] |= (char)(actual_result << ((cond_result_start + cond_val) % 8));

   for (i = 0; i < num_conditions - 1; ++i)
     covdata[(used_start + cond_val + i * (1 << num_conditions)) >> 3] |= (char)(((1 & (used_val >> i))) << ((used_start + cond_val + i * (1 << num_conditions)) % 8));
#endif


   mcdc_statement->mcdc_bits = 0;
   mcdc_statement->mcdc_bits_used = 0;

   return condition;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
#endif /* VCAST_COVERAGE_IO_BUFFERED */

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifdef VCAST_USE_STATIC_MEMORY
VCAST_AVLTree VCAST_ATTRIBUTE_CODE vcast_avltree_data_pool[VCAST_NUMBER_AVLTREE_POINTERS];
#endif

int vcast_find_val;
VCAST_position
vcast_find (VCAST_elementType VCAST_X, VCAST_AVLTree VCAST_T)
{
  if (VCAST_T == 0)
    return 0;
  vcast_find_val = vcast_mcdc_statement_compare (VCAST_X, VCAST_T->element);
  if (vcast_find_val < 0)
    return vcast_find (VCAST_X, VCAST_T->left);
  else if (vcast_find_val > 0)
    return vcast_find (VCAST_X, VCAST_T->right);
  else
    return VCAST_T;
}

static int
vcast_height (VCAST_position P)
{
  if (P == 0)
    return -1;
  else
    return P->vcast_height;
}

static int
vcast_avl_max (int Lhs, int Rhs)
{
  return Lhs > Rhs ? Lhs : Rhs;
}

	/* This function can be called only if K2 has a left child */
	/* Perform a rotate between a node (K2) and its left child */
	/* Update heights, then return new root */

static VCAST_position
vcast_singleRotateWithLeft (VCAST_position K2)
{
  VCAST_position K1;

  K1 = K2->left;
  K2->left = K1->right;
  K1->right = K2;

  K2->vcast_height = vcast_avl_max (vcast_height (K2->left), vcast_height (K2->right)) + 1;
  K1->vcast_height = vcast_avl_max (vcast_height (K1->left), K2->vcast_height) + 1;

  return K1;			/* New root */
}

	/* This function can be called only if K1 has a right child */
	/* Perform a rotate between a node (K1) and its right child */
	/* Update heights, then return new root */

static VCAST_position
vcast_singleRotateWithRight (VCAST_position K1)
{
  VCAST_position K2;

  K2 = K1->right;
  K1->right = K2->left;
  K2->left = K1;

  K1->vcast_height = vcast_avl_max (vcast_height (K1->left), vcast_height (K1->right)) + 1;
  K2->vcast_height = vcast_avl_max (vcast_height (K2->right), K1->vcast_height) + 1;

  return K2;			/* New root */
}

	/* This function can be called only if K3 has a left */
	/* child and K3's left child has a right child */
	/* Do the left-right double rotation */
	/* Update heights, then return new root */

static VCAST_position
vcast_doubleRotateWithLeft (VCAST_position K3)
{
  /* Rotate between K1 and K2 */
  K3->left = vcast_singleRotateWithRight (K3->left);

  /* Rotate between K3 and K2 */
  return vcast_singleRotateWithLeft (K3);
}

	/* This function can be called only if K1 has a right */
	/* child and K1's right child has a left child */
	/* Do the right-left double rotation */
	/* Update heights, then return new root */

static VCAST_position
vcast_doubleRotateWithRight (VCAST_position K1)
{
  /* Rotate between K3 and K2 */
  K1->right = vcast_singleRotateWithLeft (K1->right);

  /* Rotate between K1 and K2 */
  return vcast_singleRotateWithRight (K1);
}

int vcast_insert_val;
VCAST_AVLTree
vcast_insert (VCAST_elementType VCAST_X, VCAST_AVLTree VCAST_T)
{
  if (VCAST_T == 0)
    {
      /* Create and return a one-node tree */
      VCAST_T = vcast_getVCAST_AVLTree ();
      if (VCAST_T == 0)
      {
        if (vcast_max_mcdc_statements_exceeded == 0)
	  vcast_fatal_error ("VCAST_MAX_MCDC_STATEMENTS exceeded!");
        vcast_max_mcdc_statements_exceeded = 1;
      }
      else
	{
	  VCAST_T->element = VCAST_X;
	  VCAST_T->vcast_height = 0;
	  VCAST_T->left = VCAST_T->right = 0;
	}
    }
  else if ((vcast_insert_val = vcast_mcdc_statement_compare (VCAST_X, VCAST_T->element)) < 0)
    {
      VCAST_T->left = vcast_insert (VCAST_X, VCAST_T->left);
      if (vcast_height (VCAST_T->left) - vcast_height (VCAST_T->right) == 2)
	{
	  if (vcast_mcdc_statement_compare (VCAST_X, VCAST_T->left->element) < 0)
	    VCAST_T = vcast_singleRotateWithLeft (VCAST_T);
	  else
	    VCAST_T = vcast_doubleRotateWithLeft (VCAST_T);
	}
    }
  else if (vcast_insert_val > 0)
    {
      VCAST_T->right = vcast_insert (VCAST_X, VCAST_T->right);
      if (vcast_height (VCAST_T->right) - vcast_height (VCAST_T->left) == 2)
	{
	  if (vcast_mcdc_statement_compare (VCAST_X, VCAST_T->right->element) > 0)
	    VCAST_T = vcast_singleRotateWithRight (VCAST_T);
	  else
	    VCAST_T = vcast_doubleRotateWithRight (VCAST_T);
	}
    }
  /* Else X is in the tree already; we'll do nothing */

  VCAST_T->vcast_height = vcast_avl_max (vcast_height (VCAST_T->left), vcast_height (VCAST_T->right)) + 1;
  return VCAST_T;
}
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#ifdef VCAST_PROBE_PRINT_AVAILABLE
#if defined(VCAST_COVERAGE_IO_BUFFERED) && defined(VCAST_DUMP_BINARY_COVERAGE)
static int vcast_probe_print_rejected = 0;
#endif

#ifndef VCAST_COVER_NO_STDIO
/** This function copies string VC_T to string VC_S */
void vectorcast_strcpy ( char *VC_S, const char *VC_T )
{
   int vcast_i = 0;
   while ( (VC_S[vcast_i] = VC_T[vcast_i]) != 0 )
      vcast_i++;
}

void vectorcast_signed_to_string ( char vcDest[],
                                   VCAST_LONGEST_INT vcSrc )
{
   unsigned vcCount = 0;
   VCAST_UNSIGNED_CONVERSION_TYPE absolute;
   unsigned vcI,vcJ;

   absolute = ((vcSrc < 0) ? -vcSrc : vcSrc);

   do
   {
      vcDest[vcCount++] = (char)('0' + (absolute % 10));
      absolute = absolute / 10;
   } while (absolute != 0);

   if (vcSrc < 0)
   {
      vcDest[vcCount++] = '-';
   }

   vcDest[vcCount] = '\0';

   /* in place reversal of the array */
   for (vcI = 0, vcJ = vcCount - 1; vcI < vcJ; vcI++, vcJ--)
   {
      char temp = vcDest[vcI];
      vcDest[vcI] = vcDest[vcJ];
      vcDest[vcJ] = temp;
   }
}
#endif /* VCAST_COVER_NO_STDIO */


#if defined(VCAST_PROBE_POINTS_AVAILABLE) || defined(VCAST_UNIT_TEST_TOOL)

#ifndef VCAST_COVER_NO_STDIO
#if !defined(VCAST_UNIT_TEST_TOOL) || defined(VCAST_FP) || defined(VCAST_NO_SPRINTF)

/* ifndef VCAST_NO_FLOAT */
#ifndef VCAST_NO_FLOAT

#define VCAST_FLOAT_ZERO  0.0
#define VCAST_FLOAT_ONE   1.0
#define VCAST_FLOAT_TWO   2.0
#define VCAST_FLOAT_TEN  10.0

#define vCAST_false 0
#define vCAST_true 1

#define ASCII_CONVERSION 48
#define MAX_DIGITS 32
#define MAX_PRECISION 17
#define DEFAULT_PRECISION 6

int VCAST_special_compare ( char *vcDouble1, char *vcDouble2, int vcLen )
{
   int vcI;
   for (vcI=0; vcI<vcLen; vcI++) {
      if ( vcDouble1[vcI] != vcDouble2[vcI] )
         return vCAST_false;
   }
   return vCAST_true;
}

/* ------------------------------------------------------------------------------- */
void vectorcast_float_to_string( char *mixed_str, vCAST_long_double vcast_f ) {

   char whole_str[MAX_DIGITS]; /* string representation of whole portion */
   char frac_str[MAX_DIGITS];  /* string representation of fractional portion */
   char temp_str[MAX_DIGITS];  /* temp variable for string manipulation */

   vCAST_long_double f_abs;  /* the absolute value of vcast_f */
   VCAST_UNSIGNED_CONVERSION_TYPE whole;        /* int value of whole portion */
   vCAST_long_double frac;                /* double value of fractional portion */
   VCAST_UNSIGNED_CONVERSION_TYPE upper;
   int new_dig,      /* as digits get popped off, they're held here */
       float_precision=-1, /* desired precision of final result */
       sig_digs=0,   /* counter to keep track of how precise the number is */
       sign,         /* the sign of vcast_f */
       exp=0,        /* the exponent of vcast_f */
       i=0,          /* string index counter */
       last,         /* the last digit in the precision */
       last_in_frac, /* flag - does last reside in frac or whole? */
       key,          /* the next digit after last (investigate for rounding) */
       round,        /* flag - round or not? */
       cur_pos;      /* rounding index counter */

#ifndef VCAST_NO_PRINT_NAN
   /* handle special-case numbers */
   static int vcDoubleSize = 0;
#ifdef VCAST_LITERAL_DIVISOR_ZERO
/* Some compilers require a literal 0.0 divisor to produce NaN or Infinity */
#define VCAST_DIVISOR_ZERO VCAST_FLOAT_ZERO
#else
/* Some compilers do not allow a literal 0.0 divisor, so use a variable */
   static vCAST_long_double vcZERO = VCAST_FLOAT_ZERO;
#define VCAST_DIVISOR_ZERO vcZERO
#endif
   static vCAST_long_double vcNAN;
   static vCAST_long_double vcNINF;
   static vCAST_long_double vcPINF;
   if ( vcDoubleSize == 0 ) {
      vcDoubleSize = sizeof ( vCAST_long_double );
      vcNAN  = VCAST_FLOAT_ZERO/VCAST_DIVISOR_ZERO;
      vcNINF = (-VCAST_FLOAT_ONE)/VCAST_DIVISOR_ZERO;
      vcPINF = VCAST_FLOAT_ONE/VCAST_DIVISOR_ZERO;
   }

   if ( VCAST_special_compare ( (char *)&vcast_f, (char *)&vcNAN, vcDoubleSize ) ) {
      vectorcast_strcpy ( mixed_str, "NaN" );
      return;
   }

   if ( VCAST_special_compare ( (char *)&vcast_f, (char *)&vcNINF, vcDoubleSize ) ) {
      vectorcast_strcpy ( mixed_str, "-INF" );
      return;
   }

   if ( VCAST_special_compare ( (char *)&vcast_f, (char *)&vcPINF, vcDoubleSize ) ) {
      vectorcast_strcpy ( mixed_str, "+INF" );
      return;
   }
#endif

/* --- calculate float precision --- */

#ifdef VCAST_UNIT_TEST_TOOL
   /* assumes VCAST_FLOAT_FORMAT in form "%lg" or "%.xlg" or "%.xxlg" */
   if( VCAST_FLOAT_FORMAT[1] != '.' ) {
      float_precision = DEFAULT_PRECISION;
   } else {
      last = VCAST_FLOAT_FORMAT[2] - ASCII_CONVERSION;
      /* isdigit(VCAST_FLOAT_FORMAT[3]) */
      if( VCAST_FLOAT_FORMAT[3] >= '0' && VCAST_FLOAT_FORMAT[3] <= '9') {
         key = VCAST_FLOAT_FORMAT[3] - ASCII_CONVERSION;
         float_precision = last*10 + key;
      } else {
         float_precision = last;
      }
   }

   if( float_precision < 0 || float_precision > MAX_PRECISION ) {
      float_precision=DEFAULT_PRECISION;
   } else if( float_precision == 0 ) {
      float_precision=1;
   }
#else
   float_precision = DEFAULT_PRECISION;
#endif

/* --- determine sign of vcast_f --- */

   if( vcast_f == 0.0 ) {
      /* vcast_f is zero */
      vectorcast_strcpy( mixed_str, "0" );
      return;

   } else if( vcast_f > 0.0 ) {
      sign = 1;   /* vcast_f is positive */

   } else {
      sign = -1;  /* vcast_f is negative */
   }

   f_abs = vcast_f*sign;

   if( f_abs < 0 ) { /* out of range - infinity */
      vectorcast_strcpy( mixed_str, "Inf" );
      return;
   }


/* --- determine exponent value --- */

   /* calculate pow(10, float_precision) without including math.h */
   for( i=1, upper=10; i<float_precision; i++ ) {
      upper*=10;
   }
   upper-=1;

   /* to switch to exp notation: 4 leading zeros or f > (10^precision-1) */
   if( f_abs < .00009999999999999 || f_abs > upper ) {
      if( f_abs < 1.0 ) { /* negative exponent */
         while( f_abs < 1.0 ) {
            exp--;
            f_abs*=10.0;      /* introduces loss of precision */
         }

      } else {          /* positive exponent */
         while( f_abs > 10.0 ) {
            exp++;
            f_abs/=10.0;      /* introduces loss of precision */
         }
      }
   } /* else, don't use exponential notation */


/* --- trim digits off while building whole_str, frac_str and mixed_str --- */

   whole = (VCAST_UNSIGNED_CONVERSION_TYPE)f_abs;
   vcast_int_to_string ( whole_str, whole );
   if( whole > 0 ) {
      sig_digs = vcast_strlen(whole_str);
   }

   frac = f_abs - whole;

   /* build frac_str (grab an extra digit for rounding information) */
   i=0;
   while( sig_digs < float_precision+1 ) {
      frac*=10.0;             /* introduces loss of precision */
      new_dig = (int)(frac);
      frac_str[i++] = (char)(new_dig + ASCII_CONVERSION);
      frac-=(float)new_dig;

      if( sig_digs > 0 || new_dig > 0 ) {
         sig_digs++;
      }

   }
   frac_str[i] = 0;


/* --- calculate and perform rounding (if necessary) --- */

   /* check for rounding */
   if( i < 2 ) {  /* last dig is in whole_str */
      last_in_frac = 0;
      cur_pos = vcast_strlen(whole_str)-1;
      last = whole_str[cur_pos]-ASCII_CONVERSION;
   } else {       /* last dig is in frac_str */
      last_in_frac = 1;
      cur_pos = i-2;
      last = frac_str[cur_pos]-ASCII_CONVERSION;
   }

   round = 0;
   key = frac_str[i-1]-ASCII_CONVERSION;

   if( key > 5 ) {  /* 1.6 -> round up, 1.4 -> don't round */
      round = 1;
   } else if( key == 5 ) { /* 1.50000 -> don't round, 1.500001 -> round up */
      while( sig_digs < 36 && !round ) {
         frac*=10.0;          /* introduces loss of precision */
         new_dig = (int)(frac);

         if( new_dig>0 ) {
            round=1;
         }
         sig_digs++;

      }
   }

   if( round ) {       /* round up */
      if( last != 9 ) {    /* just add 1 to the last digit */
         if( last_in_frac ) {
            frac_str[cur_pos]++;
         } else {
            whole_str[cur_pos]++;
         }

      } else {             /* domino rounding */
         while( last == 9 ) {
            /* make cur_pos 0 */
            if( last_in_frac ) {
               frac_str[cur_pos] = '0';
            } else {
               whole_str[cur_pos] = '0';
            }

            /* set new last */
            if( --cur_pos >= 0 ) {  /* simply set new last */
               if( last_in_frac ) {
                  last = frac_str[cur_pos]-ASCII_CONVERSION;
               } else {
                  last = whole_str[cur_pos]-ASCII_CONVERSION;
               }
            } else {                /* cross decimal point */
               if( last_in_frac ) {
                  last_in_frac = 0;
                  cur_pos = vcast_strlen(whole_str)-1;
                  last = whole_str[cur_pos]-ASCII_CONVERSION;
               } else { /* need to shift to add extra 1 */
                  last = 0;
               }
            }
         } /* end while */

         /* add 1 to the current digit */
         if( last_in_frac ) {
            frac_str[cur_pos]++;
         } else {
            if( cur_pos >= 0 ) {
               whole_str[cur_pos]++;
            } else {
               /* need to add a 1 to the front of whole_str */
               if( exp==0 ) {
                  vectorcast_strcpy ( temp_str, "1" );
                  vcast_strcat ( temp_str, whole_str );
                  vectorcast_strcpy( whole_str, temp_str );
               } else {
                  vectorcast_strcpy( whole_str, "1" );
                  exp++;
               }
            }
         }

      } /* end domino */
   } /* end rounding */


/* --- clean up and build mixed_str --- */

   /* trim off rounding info */
   frac_str[i-1] = 0;

   /* kill trailing zeros */
   while( vcast_strlen(frac_str) > 0 && frac_str[vcast_strlen(frac_str)-1] == '0' ) {
      frac_str[vcast_strlen(frac_str)-1] = 0;
   }

   /* don't print the exponent if its zero */
   vectorcast_strcpy ( mixed_str, (sign==-1)?"-":"" );
   vcast_strcat ( mixed_str, whole_str );
   if( vcast_strlen(frac_str) > 0 ) {
      vcast_strcat ( mixed_str, "." );
      vcast_strcat ( mixed_str, frac_str );
   }
   if( exp!=0 ) {
      vectorcast_signed_to_string ( whole_str, exp );
      vcast_strcat ( mixed_str, (exp<0)?"e":"e+" );
      vcast_strcat ( mixed_str, whole_str );
   }

   /* done - mixed_str contains final result */
   return;
}
#endif
/* endif VCAST_NO_FLOAT */
#endif /* !VCAST_UNIT_TEST_TOOL || VCAST_FP || VCAST_NO_SPRINTF */
#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_PROBE_POINTS_AVAILABLE || VCAST_UNIT_TEST_TOOL */

#ifdef VCAST_PROBE_POINTS_AVAILABLE
#ifndef VCAST_COVER_NO_STDIO

#ifndef VCAST_UNIT_TEST_TOOL
void vcast_probe_print (const char *S)
{
#if defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_COVERAGE_IO_BUFFERED)
   vcast_probe_print_rejected = 1;
#else
   VCAST_WRITE_COVERAGE_DATA("VPROBE:");
   VCAST_WRITE_COVERAGE_DATA(S);
   VCAST_WRITE_COVERAGE_DATA(":VPROBE");
#endif
}
#endif

void vcast_probe_print_unsigned (VCAST_UNSIGNED_CONVERSION_TYPE i)
{
   char local_string[32];
   vcast_int_to_string(local_string, i);
   vcast_probe_print (local_string);
}
void vcast_probe_print_int (VCAST_SIGNED_CONVERSION_TYPE i)
{
   char local_string[32];
   vectorcast_signed_to_string(local_string, i);
   vcast_probe_print (local_string);
}
#ifndef VCAST_NO_FLOAT
void vcast_probe_print_float (vCAST_long_double vcast_f)
{
   char local_string[32];
#if !defined(VCAST_UNIT_TEST_TOOL) || defined(VCAST_FP) || defined(VCAST_NO_SPRINTF)
   vectorcast_float_to_string(local_string, vcast_f);
#else
   sprintf ( local_string, VCAST_FLOAT_FORMAT, vcast_f );
#endif /* !VCAST_UNIT_TEST_TOOL || VCAST_FP || VCAST_NO_SPRINTF */
   vcast_probe_print (local_string);
}
#endif

#endif /* endif VCAST_PROBE_POINTS_AVAILABLE */

#endif /* VCAST_COVER_NO_STDIO */
#endif /* VCAST_PROBE_PRINT_AVAILABLE */

#ifndef VCAST_COVER_NO_STDIO
void VCAST_REGISTER_DUMP_AT_EXIT (void)
{
#ifdef VCAST_DUMP_COVERAGE_AT_EXIT
  if (vcast_has_registered_atexit == 0) {
     vcast_register_atexit();
     vcast_has_registered_atexit = 1;
   }
#endif  /* VCAST_DUMP_COVERAGE_AT_EXIT */
}
#endif /* VCAST_COVER_NO_STDIO */

#ifndef VCAST_COVER_NO_STDIO
#ifdef VCAST_COVERAGE_IO_BUFFERED
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
void VCAST_DUMP_GLOBAL_MCDC_COVERAGE_ID (int unique_id, VCAST_AVLTree tree);
void
VCAST_DUMP_GLOBAL_MCDC_COVERAGE_ID (int unique_id, VCAST_AVLTree tree)
{
  /* Walk the tree, and output the data */
  if (tree)
  {
    VCAST_DUMP_GLOBAL_MCDC_COVERAGE_ID (unique_id, tree->left);
    VCAST_WRITE_GLOBAL_MCDC_ID (unique_id,
                                tree->element->mcdc_bits,
                                tree->element->mcdc_bits_used);
    VCAST_DUMP_GLOBAL_MCDC_COVERAGE_ID (unique_id, tree->right);
  }
}
#else
void VCAST_DUMP_MCDC_COVERAGE_ID (int unit, int unique_id, VCAST_AVLTree tree);
void
VCAST_DUMP_MCDC_COVERAGE_ID (int unit, int unique_id, VCAST_AVLTree tree)
{
  /* Walk the tree, and output the data */
  if (tree)
  {
    VCAST_DUMP_MCDC_COVERAGE_ID (unit, unique_id, tree->left);
    VCAST_WRITE_MCDC_ID (unit, unique_id,
                         tree->element->mcdc_bits,
                         tree->element->mcdc_bits_used);
    VCAST_DUMP_MCDC_COVERAGE_ID (unit, unique_id, tree->right);
  }
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#endif /* defined (VCAST_COVERAGE_TYPE_MCDC) || defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
void VCAST_DUMP_STATEMENT_COVERAGE_DATA_ID(int vcast_unit,
                                           char *vcast_statement_array,
                                           int vcast_statement_bytes);
#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
void VCAST_DUMP_GLOBAL_STATEMENT_COVERAGE_DATA_ID();
#endif /* defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS) */

#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_GLOBAL_STATEMENT_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_STATEMENT_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_STATEMENT_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_STATEMENT_UNIQUE_ID; ++vcast_cur_unique_id){
    if (vcast_coverage_bytes[vcast_cur_unique_id]){
      VCAST_WRITE_GLOBAL_STATEMENT_ID(vcast_cur_unique_id);
    }
  }
}
#else
void VCAST_DUMP_GLOBAL_STATEMENT_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_STATEMENT_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_STATEMENT_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_STATEMENT_UNIQUE_ID;
       ++vcast_cur_unique_id)
  {
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 3] & (1 << (vcast_cur_unique_id % 8)))
      VCAST_WRITE_GLOBAL_STATEMENT_ID(vcast_cur_unique_id);
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_STATEMENT_COVERAGE_DATA_ID(int vcast_unit,
                                           char *vcast_statement_array,
                                           int vcast_statement_bytes)
{
  int vcast_cur_byte;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_statement_bytes; ++vcast_cur_byte) {
    if (vcast_statement_array[vcast_cur_byte]){
      VCAST_WRITE_STATEMENT_ID(vcast_unit, vcast_cur_byte);
    }
  }
}
#else
void VCAST_DUMP_STATEMENT_COVERAGE_DATA_ID(int vcast_unit,
                                           char *vcast_statement_array,
                                           int vcast_statement_bytes)
{
  int vcast_cur_byte;
  int vcast_cur_bit;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_statement_bytes; ++vcast_cur_byte) {
    int vcast_byte = vcast_statement_array[vcast_cur_byte];
    /* For each bit in the byte */
    for (vcast_cur_bit = 0; vcast_cur_bit < 8; ++vcast_cur_bit) {
      if (vcast_byte & (1 << vcast_cur_bit)) {
        VCAST_WRITE_STATEMENT_ID(vcast_unit, vcast_cur_byte*8 + vcast_cur_bit);
      }
    }
  }
}
#endif
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif

#if defined VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_GLOBAL_FN_CALL_COVERAGE_DATA_ID();
void VCAST_DUMP_GLOBAL_FN_CALL_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_FN_CALL_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_FN_CALL_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_FN_CALL_UNIQUE_ID;
       ++vcast_cur_unique_id)
  {
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 3] & (1 << (vcast_cur_unique_id % 8)))
      VCAST_WRITE_GLOBAL_FN_CALL_ID(vcast_cur_unique_id);
  }
}
#else
void VCAST_DUMP_GLOBAL_FN_CALL_COVERAGE_DATA_ID();
void VCAST_DUMP_GLOBAL_FN_CALL_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_FN_CALL_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_FN_CALL_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_FN_CALL_UNIQUE_ID; ++vcast_cur_unique_id){
    if (vcast_coverage_bytes[vcast_cur_unique_id]){
      VCAST_WRITE_GLOBAL_FN_CALL_ID(vcast_cur_unique_id);
    }
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else
void VCAST_DUMP_FN_CALL_COVERAGE_DATA_ID(int vcast_unit,
                                         char *vcast_fn_call_array,
                                         int vcast_fn_call_bytes);

#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_FN_CALL_COVERAGE_DATA_ID(int vcast_unit,
                                         char *vcast_fn_call_array,
                                         int vcast_fn_call_bytes)
{
  int vcast_cur_byte;
  int vcast_cur_bit;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_fn_call_bytes; ++vcast_cur_byte) {
    int vcast_byte = vcast_fn_call_array[vcast_cur_byte];
    /* For each bit in the byte */
    for (vcast_cur_bit = 0; vcast_cur_bit < 8; ++vcast_cur_bit) {
      if (vcast_byte & (1 << vcast_cur_bit)) {
        VCAST_WRITE_FN_CALL_ID(vcast_unit, vcast_cur_byte*8 + vcast_cur_bit);
      }
    }
  }
}
#else
void VCAST_DUMP_FN_CALL_COVERAGE_DATA_ID(int vcast_unit,
                                         char *vcast_fn_call_array,
                                         int vcast_fn_call_bytes)
{
  int vcast_cur_byte;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_fn_call_bytes; ++vcast_cur_byte) {
    if (vcast_fn_call_array[vcast_cur_byte]){
      VCAST_WRITE_FN_CALL_ID(vcast_unit, vcast_cur_byte);
    }
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL */

#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined(VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
void VCAST_DUMP_GLOBAL_BRANCH_COVERAGE_DATA_ID();
void VCAST_DUMP_GLOBAL_SINGLE_BRANCH_COVERAGE_DATA_ID();
#if ! defined(VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_GLOBAL_BRANCH_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;
  int vcast_cur_byte = (VCAST_MIN_BRANCH_UNIQUE_ID - 1) * 2;

  if (VCAST_MIN_BRANCH_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_BRANCH_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_BRANCH_UNIQUE_ID; ++vcast_cur_unique_id){
    if (vcast_coverage_bytes[vcast_cur_byte]){
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "T");
    }
    if (vcast_coverage_bytes[vcast_cur_byte + 1]){
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "F");
    }
    vcast_cur_byte += 2;
  }
}
void VCAST_DUMP_GLOBAL_SINGLE_BRANCH_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_SINGLE_BRANCH_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_SINGLE_BRANCH_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_SINGLE_BRANCH_UNIQUE_ID; ++vcast_cur_unique_id){
    if (vcast_coverage_bytes[vcast_cur_unique_id]){
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "S");
    }
  }
}
#else
void VCAST_DUMP_GLOBAL_BRANCH_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;
  int vcast_cur_bit;

  if (VCAST_MIN_BRANCH_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_BRANCH_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_BRANCH_UNIQUE_ID;
       ++vcast_cur_unique_id)
  {
    vcast_cur_bit = (vcast_cur_unique_id % 4) << 1;
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 2] & (1 << vcast_cur_bit))
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "T");
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 2] & (1 << vcast_cur_bit + 1))
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "F");
  }
}
void VCAST_DUMP_GLOBAL_SINGLE_BRANCH_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_SINGLE_BRANCH_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_SINGLE_BRANCH_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_SINGLE_BRANCH_UNIQUE_ID;
       ++vcast_cur_unique_id)
  {
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 3] & (1 << (vcast_cur_unique_id % 8)))
      VCAST_WRITE_GLOBAL_BRANCH_ID(vcast_cur_unique_id, "S");
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else
void VCAST_DUMP_BRANCH_COVERAGE_DATA_ID(int vcast_unit,
                                        char *vcast_branch_array,
                                        int vcast_branch_bytes);

#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_BRANCH_COVERAGE_DATA_ID(int vcast_unit,
                                        char *vcast_branch_array,
                                        int vcast_branch_bytes)
{
  int vcast_cur_byte;
  int vcast_cur_id = 0;
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_branch_bytes; vcast_cur_byte+=2) {
    if (vcast_branch_array[vcast_cur_byte]){
      VCAST_WRITE_BRANCH_ID(vcast_unit, vcast_cur_id, "T");
    }
    if (vcast_branch_array[vcast_cur_byte + 1]){
      VCAST_WRITE_BRANCH_ID(vcast_unit, vcast_cur_id, "F");
    }
    vcast_cur_id++;
  }
}
#else
void VCAST_DUMP_BRANCH_COVERAGE_DATA_ID(int vcast_unit,
                                        char *vcast_branch_array,
                                        int vcast_branch_bytes)
{
  int vcast_cur_byte;
  int vcast_cur_bit;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_branch_bytes; ++vcast_cur_byte) {
    int vcast_byte = vcast_branch_array[vcast_cur_byte];
    /* For each bit in the byte */
    for (vcast_cur_bit = 0; vcast_cur_bit < 8; ++vcast_cur_bit) {
      if (vcast_byte & (1 << vcast_cur_bit)) {
        VCAST_WRITE_BRANCH_ID(vcast_unit, vcast_cur_byte*4 + (vcast_cur_bit >> 1),
                              ((vcast_cur_bit % 2 == 0) ? "T" : "F"));
      }
    }
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* branch */

#if defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
void VCAST_DUMP_GLOBAL_MCDC_COVERAGE_DATA_ID(VCAST_AVLTree *vcast_mcdc_array,
                                             int vcast_mcdc_statement_count);
void VCAST_DUMP_GLOBAL_MCDC_COVERAGE_DATA_ID(VCAST_AVLTree *vcast_mcdc_array,
                                             int vcast_mcdc_statement_count)
{
  int unique_id;
  for (unique_id = 0; unique_id < vcast_mcdc_statement_count; ++unique_id)
  {
    if (vcast_mcdc_array[unique_id])
    {
      VCAST_DUMP_GLOBAL_MCDC_COVERAGE_ID(unique_id,
                                         vcast_mcdc_array[unique_id]);
    }
  }
}
#else
void VCAST_DUMP_MCDC_COVERAGE_DATA_ID(int vcast_unit,
                                      VCAST_AVLTree *vcast_mcdc_array,
                                      int vcast_mcdc_statement_count);
void VCAST_DUMP_MCDC_COVERAGE_DATA_ID(int vcast_unit,
                                      VCAST_AVLTree *vcast_mcdc_array,
                                      int vcast_mcdc_statement_count)
{
  int unique_id;
  for (unique_id = 0; unique_id < vcast_mcdc_statement_count; ++unique_id)
  {
    if (vcast_mcdc_array[unique_id])
    {
      VCAST_DUMP_MCDC_COVERAGE_ID(vcast_unit, unique_id,
                                  vcast_mcdc_array[unique_id]);
    }
  }
}
#endif /* #ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
void VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(int num_conditions);
void VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(int num_conditions)
{
  int id;
  int bit_offset = 0;
  int bits_needed = (1 << num_conditions) * (num_conditions + 1);
  int start_unique_id = 0;
  int end_unique_id = 0;
  int num_mcdc_elems = 0;
  int cond_val;
  int used_val;
  int actual_result;
  int cond_result_start;
  int used_start;
  if (bits_needed == 1)
    bits_needed = 2;

  switch (num_conditions)
  {
  case 0:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_0;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_0;
    break;
  case 1:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_1;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_1;
    break;
  case 2:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_2;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_2;
    break;
  case 3:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_3;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_3;
    break;
  case 4:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_4;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_4;
    break;
  case 5:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_5;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_5;
    break;
  case 6:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_6;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_6;
    break;
  case 7:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_7;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_7;
    break;
  case 8:
    start_unique_id = VCAST_MIN_MCDC_UNIQUE_ID_8;
    end_unique_id = VCAST_MAX_MCDC_UNIQUE_ID_8;
    break;
  }

  bit_offset = bits_needed * (start_unique_id - 1);

  for (id = start_unique_id - 1; id < end_unique_id; ++id)
  {
    cond_result_start = bit_offset + (1 << num_conditions);
    used_start = bit_offset + (1 << (num_conditions + 1));

    for (cond_val = 0; cond_val < (1 << num_conditions); ++cond_val)
    {
      if (vcast_coverage_bytes[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8)))
      {
        int i;
        actual_result = (vcast_coverage_bytes[(cond_result_start + cond_val) >> 3] & (1 << ((cond_result_start + cond_val) % 8))) >> ((cond_result_start + cond_val) % 8);
        used_val = (1 << (num_conditions > 0 ? 1 : 0)) | 1;
        for (i = 0; i < num_conditions - 1; ++i)
          used_val |= ((vcast_coverage_bytes[(used_start + cond_val + i * (1 << num_conditions)) >> 3] & (1 << ((used_start + cond_val + i * (1 << num_conditions)) % 8))) >> (((used_start + cond_val + i * (1 << num_conditions)) % 8))) << (2 + i);

        VCAST_WRITE_GLOBAL_OPTIMIZED_MCDC_ID (id, (char)(num_conditions + 97),
                                              (cond_val << 1) | actual_result,
                                              used_val);
      }
    }

    bit_offset += bits_needed;
  }
}
#else
void VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(int vcast_unit,
                                                char *vcast_optimized_mcdc_array,
                                                int vcast_optimized_mcdc_bytes,
                                                int num_conditions);
void VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(int vcast_unit,
                                                char *vcast_optimized_mcdc_array,
                                                int vcast_optimized_mcdc_bytes,
                                                int num_conditions)
{
  int id;
  int bit_offset = 0;
  int bits_needed = (1 << num_conditions) * (num_conditions + 1);
  if (bits_needed == 1)
    bits_needed = 2;

  for (id = 0; id < vcast_optimized_mcdc_bytes; ++id)
  {
    int cond_result_start = bit_offset + (1 << num_conditions);
    int used_start = bit_offset + (1 << (num_conditions + 1));
    int cond_val;
    int used_val;
    int actual_result;

    for (cond_val = 0; cond_val < (1 << num_conditions); ++cond_val)
    {
      if (vcast_optimized_mcdc_array[(bit_offset + cond_val) >> 3] & (1 << ((bit_offset + cond_val) % 8)))
      {
        int i;
        actual_result = (vcast_optimized_mcdc_array[(cond_result_start + cond_val) >> 3] & (1 << ((cond_result_start + cond_val) % 8))) >> ((cond_result_start + cond_val) % 8);
        used_val = (1 << (num_conditions > 0 ? 1 : 0)) | 1;
        for (i = 0; i < num_conditions - 1; ++i)
          used_val |= ((vcast_optimized_mcdc_array[(used_start + cond_val + i * (1 << num_conditions)) >> 3] & (1 << ((used_start + cond_val + i * (1 << num_conditions)) % 8))) >> (((used_start + cond_val + i * (1 << num_conditions)) % 8))) << (2 + i);

        VCAST_WRITE_OPTIMIZED_MCDC_ID (vcast_unit, id, (char)(num_conditions + 97),
                                       ((cond_val << 1) | actual_result),
                                       used_val);
      }
    }

    bit_offset += bits_needed;
  }
}
#endif
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif

#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined (VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
void
VCAST_DUMP_FUNCTION_COVERAGE_DATA_ID(int vcast_unit,
                                     char *vcast_function_array,
                                     int vcast_function_bytes);

#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
void VCAST_DUMP_GLOBAL_FUNCTION_COVERAGE_DATA_ID();
#endif /* defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS) */

#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void VCAST_DUMP_GLOBAL_FUNCTION_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_FUNCTION_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_FUNCTION_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_FUNCTION_UNIQUE_ID; ++vcast_cur_unique_id){
    if (vcast_coverage_bytes[vcast_cur_unique_id]){
      VCAST_WRITE_GLOBAL_FUNCTION_ID(vcast_cur_unique_id);
    }
  }
}
#else
void VCAST_DUMP_GLOBAL_FUNCTION_COVERAGE_DATA_ID()
{
  int vcast_cur_unique_id;

  if (VCAST_MIN_FUNCTION_UNIQUE_ID == 0)
    return;

  for (vcast_cur_unique_id = VCAST_MIN_FUNCTION_UNIQUE_ID - 1;
       vcast_cur_unique_id < VCAST_MAX_FUNCTION_UNIQUE_ID;
       ++vcast_cur_unique_id)
  {
    if (vcast_coverage_bytes[vcast_cur_unique_id >> 3] & (1 << (vcast_cur_unique_id % 8)))
      VCAST_WRITE_GLOBAL_FUNCTION_ID(vcast_cur_unique_id);
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
void
VCAST_DUMP_FUNCTION_COVERAGE_DATA_ID(int vcast_unit,
                                     char *vcast_function_array,
                                     int vcast_function_bytes)
{
  int vcast_cur_byte;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_function_bytes; ++vcast_cur_byte) {
    if (vcast_function_array[vcast_cur_byte]){
      VCAST_WRITE_FUNCTION_ID(vcast_unit, vcast_cur_byte);
    }
  }
}
#else
void
VCAST_DUMP_FUNCTION_COVERAGE_DATA_ID(int vcast_unit,
                                     char *vcast_function_array,
                                     int vcast_function_bytes)
{
  int vcast_cur_byte;
  int vcast_cur_bit;

  /* For each byte */
  for (vcast_cur_byte = 0; vcast_cur_byte < vcast_function_bytes; ++vcast_cur_byte) {
    int vcast_byte = vcast_function_array[vcast_cur_byte];
    /* For each bit in the byte */
    for (vcast_cur_bit = 0; vcast_cur_bit < 8; ++vcast_cur_bit) {
      if (vcast_byte & (1 << vcast_cur_bit)) {
        VCAST_WRITE_FUNCTION_ID(vcast_unit, vcast_cur_byte*8 + vcast_cur_bit);
      }
    }
  }
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION */

void VCAST_DUMP_COVERAGE_DATA_ID(void);

#if defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#ifdef VCAST_USE_STDOUT
#define VCAST_WRITE_BINARY_DATA(data, size) { int i; for (i = 0; i < size; ++i) putchar(data[i]); }
#define VCAST_WRITE_BINARY_INTEGER(data, size) { putchar(*data); }
#elif defined VCAST_UNIT_TEST_TOOL
#define VCAST_WRITE_BINARY_DATA(data, size) { vCAST_CREATE_INST_FILE(); vectorcast_fwrite(vCAST_INST_FILE, data, size); }
#define VCAST_WRITE_BINARY_INTEGER(data, size) VCAST_WRITE_BINARY_DATA(data, size)
#else
#define VCAST_WRITE_BINARY_DATA(data, size) { vCAST_CREATE_INST_FILE(); fwrite(data, 1, size, (FILE*)vCAST_INST_FILE); }
#define VCAST_WRITE_BINARY_INTEGER(data, size) VCAST_WRITE_BINARY_DATA(data, size)
#endif

#if defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
void VCAST_COUNT_BINARY_GLOBAL_MCDC_COVERAGE_ID(int unique_id,
                                                VCAST_AVLTree tree,
                                                int *num_elements)
{
  if (tree)
  {
    VCAST_COUNT_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id, tree->left, num_elements);
    ++(*num_elements);
    VCAST_COUNT_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id, tree->right, num_elements);
  }
}

void VCAST_DUMP_BINARY_GLOBAL_MCDC_COVERAGE_ID(int unique_id,
                                               VCAST_AVLTree tree)
{
  if (tree)
  {
    VCAST_DUMP_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id, tree->left);

    VCAST_WRITE_BINARY_INTEGER(&unique_id, sizeof(unique_id));
    VCAST_WRITE_BINARY_INTEGER(&(tree->element->mcdc_bits), sizeof(tree->element->mcdc_bits));
    VCAST_WRITE_BINARY_INTEGER(&(tree->element->mcdc_bits_used), sizeof(tree->element->mcdc_bits_used));

    VCAST_DUMP_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id, tree->right);
  }
}

void VCAST_DUMP_BINARY_MCDC_COVERAGE_DATA_ID(VCAST_AVLTree *tree, int array_size)
{
  int unique_id;
  fpos_t start_pos;
  int num_elements = 0;

  for (unique_id = 0; unique_id < array_size; ++unique_id)
  {
    if (tree[unique_id])
    {
      VCAST_COUNT_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id, tree[unique_id], &num_elements);
    }
  }

  VCAST_WRITE_BINARY_INTEGER(&num_elements, sizeof(num_elements));

  for (unique_id = 0; unique_id < array_size; ++unique_id)
  {
    if (tree[unique_id])
    {
      VCAST_DUMP_BINARY_GLOBAL_MCDC_COVERAGE_ID(unique_id,
                                                tree[unique_id]);
    }
  }
}
#endif /* VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#endif /* MCDC */

#endif /* VCAST_COVERAGE_IO_BUFFERED */

void VCAST_DUMP_BINARY_COVERAGE_DATA_ID(void);
void VCAST_DUMP_BINARY_COVERAGE_DATA_ID(void)
{
#ifdef VCAST_COVERAGE_IO_BUFFERED
#ifdef VCAST_DUMP_BINARY_COVERAGE
  VCAST_WRITE_BINARY_DATA(vcast_coverage_bytes, sizeof(vcast_coverage_bytes));
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
  VCAST_DUMP_BINARY_MCDC_COVERAGE_DATA_ID(vcast_mcdc_bytes,
                                          sizeof(vcast_mcdc_bytes) / sizeof(VCAST_AVLTree));

  if (vcast_max_mcdc_statements_exceeded)
    VCAST_WRITE_COVERAGE_DATA_FLUSH("\nVCAST_MAX_MCDC_STATEMENTS exceeded!");
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#if defined(VCAST_COVERAGE_TYPE_COUPLING) || defined(VCAST_COUPLING_APPLIED)
  vcastDumpCouplingData();
#endif
#ifdef VCAST_PROBE_PRINT_AVAILABLE
  if (vcast_probe_print_rejected)
  {
    VCAST_WRITE_COVERAGE_DATA_FLUSH("\nProbe point printing not allowed in buffered binary coverage dumps!");
    vcast_probe_print_rejected = 0;
  }
#endif
#endif
#endif
}

#if defined(VCAST_COVERAGE_IO_BUFFERED) && defined(VCAST_STATIC_REGISTRATION)
struct vcast_unit_values_s *vcast_unit_values_head = 0;
#if defined(VCAST_VCWRAP_GHS_BUFFERED_IO)
extern void (* const __ghstable_vcast[])(void);

void VCAST_REGISTER_GHS_BUFFERED_IO()
{
  void (*const* unit_reg_func_ptr)(void) = __ghstable_vcast;
  while (unit_reg_func_ptr && *unit_reg_func_ptr)
  {
    (**unit_reg_func_ptr)();
    ++unit_reg_func_ptr;
  }
}
#endif
#if defined(VCAST_VCWRAP_TASKING_BUFFERED_IO) && !defined __cplusplus
/* This part of the code was provided by Tasking and allows us to call __sti__vcast_register_unit functions.
  Checking __cplusplus was necessary here because when this function is called in C++ with a single file,
  the program will fall into an infinite loop because of a wrong linked list initialisation. */
extern unsigned int _lc_ub__lc__ctors;

void VCAST_REGISTER_TASKING_BUFFERED_IO()
{
  void (*unit_reg_func_ptr)(void);
  unsigned int *uip;
  uip = (unsigned int *)&_lc_ub__lc__ctors;
  while (*uip) {
    unit_reg_func_ptr = (void (*)())(*uip);
    unit_reg_func_ptr();
    uip+=1;
  }
}
#endif
#endif

void VCAST_DUMP_COVERAGE_DATA_ID(void)
{
#if defined(VCAST_COVERAGE_IO_BUFFERED)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined(VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined(VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
    defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
  VCAST_DUMP_GLOBAL_FUNCTION_COVERAGE_DATA_ID();
#endif
#if defined(VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL)
  VCAST_DUMP_GLOBAL_FN_CALL_COVERAGE_DATA_ID();
#endif
#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
  VCAST_DUMP_GLOBAL_STATEMENT_COVERAGE_DATA_ID();
#endif
#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
  VCAST_DUMP_GLOBAL_BRANCH_COVERAGE_DATA_ID();
  VCAST_DUMP_GLOBAL_SINGLE_BRANCH_COVERAGE_DATA_ID();
#endif
#if defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
  VCAST_DUMP_GLOBAL_MCDC_COVERAGE_DATA_ID(vcast_mcdc_bytes,
                                          sizeof(vcast_mcdc_bytes) / sizeof(VCAST_AVLTree));
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 0
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(0); 
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 1
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(1); 
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 2
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(2);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 3
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(3);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 4
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(4);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 5
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(5);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 6
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(6);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 7
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(7);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 8
  VCAST_DUMP_GLOBAL_OPTIMIZED_MCDC_COVERAGE_DATA_ID(8);
#endif 
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif /* defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
#else
#ifdef VCAST_STATIC_REGISTRATION
#if defined(VCAST_VCWRAP_GHS_BUFFERED_IO)
  VCAST_REGISTER_GHS_BUFFERED_IO();
#endif
#if defined(VCAST_VCWRAP_TASKING_BUFFERED_IO) && !defined __cplusplus
/* See comment line 3204 about why we need !defined __cplusplus */
  VCAST_REGISTER_TASKING_BUFFERED_IO();
#endif
  const struct vcast_unit_values_s *vcast_unit_cur;
  for (vcast_unit_cur = vcast_unit_values_head; vcast_unit_cur;
       vcast_unit_cur = vcast_unit_cur->previous) {
#else  /*VCAST_STATIC_REGISTRATION*/
  const struct vcast_unit_list *vcast_unit_cur;
  for (vcast_unit_cur = vcast_unit_list_values; vcast_unit_cur->vcast_unit;
       ++vcast_unit_cur) {
#endif /*VCAST_STATIC_REGISTRATION*/
    int vcast_unit = vcast_unit_cur->vcast_unit;
#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined (VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_DUMP_FUNCTION_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_function_array,
                                         vcast_unit_cur->vcast_function_bytes);
#endif
#if defined(VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_DUMP_FN_CALL_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_fn_call_array,
                                        vcast_unit_cur->vcast_fn_call_bytes);
#endif
#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_DUMP_STATEMENT_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_statement_array,
                                          vcast_unit_cur->vcast_statement_bytes);
#endif
#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined(VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
    VCAST_DUMP_BRANCH_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_branch_array,
                                       vcast_unit_cur->vcast_branch_bytes);
#endif
#if defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
    VCAST_DUMP_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_mcdc_array,
                                     vcast_unit_cur->vcast_mcdc_statement_count);
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */

#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 0
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_0,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_0, 0);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 1
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_1,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_1, 1);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 2
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_2,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_2, 2);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 3
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_3,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_3, 3);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 4
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_4,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_4, 4);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 5
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_5,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_5, 5);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 6
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_6,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_6, 6);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 7
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_7,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_7, 7);
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 8
    VCAST_DUMP_OPTIMIZED_MCDC_COVERAGE_DATA_ID(vcast_unit, vcast_unit_cur->vcast_optimized_mcdc_array_8,
                                               vcast_unit_cur->vcast_optimized_mcdc_bytes_8, 8);
#endif
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif /* defined(VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
  }
#endif

#if defined(VCAST_COVERAGE_TYPE_COUPLING) || defined(VCAST_COUPLING_APPLIED)
  vcastDumpCouplingData();
#endif
#endif /* VCAST_COVERAGE_IO_BUFFERED */
}
#endif /* VCAST_COVER_NO_STDIO */
#endif

#ifdef VCAST_CUDA

#ifdef VCAST_CUDA_ENABLE_DRIVER_API

typedef struct vcastCudaDeviceContext {
    int dev;
    int show_as;
    CUmodule hmod;
    CUcontext ctx;
    struct vcastCudaDeviceContext *next;
} vcastCudaDeviceContext_t;

static vcastCudaDeviceContext_t *vcast_cuda_registrations = NULL;

/* Register a device context that should be dumped. */
void VCAST_REGISTER_DEVICE_COVERAGE_CONTEXT(int device, int show_as, CUmodule hmod, CUcontext ctx);

void VCAST_REGISTER_DEVICE_COVERAGE_CONTEXT(int device, int show_as, CUmodule hmod, CUcontext ctx) 
{
    /* create new context structure */ 
    vcastCudaDeviceContext_t *reg = (vcastCudaDeviceContext_t *)malloc(sizeof(vcastCudaDeviceContext_t));
    if (reg == NULL) {
        fprintf(stderr, "Error: Memory allocation failed.\n");
        return;
        /*exit(1);*/ /* should we exit instead? */
    }

    /* fill structure values */
    reg->dev = device;
    reg->show_as = show_as;
    reg->hmod = hmod;
    reg->ctx = ctx;
    
    /* add to linked list */
    reg->next = vcast_cuda_registrations;  /* current head */
    vcast_cuda_registrations = reg;  /* we're the new head */
}

/* Clear out registrations */
void VCAST_CLEAR_DEVICE_REGISTRATIONS(void);

void VCAST_CLEAR_DEVICE_REGISTRATIONS(void)
{
    vcastCudaDeviceContext_t *cur = vcast_cuda_registrations;
    vcastCudaDeviceContext_t *next;
    
    /* walk list and free as we go. */
    while (cur) {
        next = cur->next;
        free(cur);
        cur = next;
    }
    
    /* make sure list head pointer is empty */
    vcast_cuda_registrations = NULL;
}

/* A global pointer to the current module from which coverage 
 * symbols should be found. If NULL, then get symbols from the 
 * current runtime environment rather than from a module. 
 */
CUmodule vcast_cuda_coverage_module = NULL;

#endif /* defined(VCAST_CUDA_ENABLE_DRIVER_API) */


/* CUDA dump needs to iterate over every device, so we will
   call this function from the application, and rename our
   original function to be VCAST_DUMP_COVERAGE_DATA_DEVICE */
void VCAST_DUMP_COVERAGE_DATA_DEVICE (void);

/* CUDA dump needs to clear buffers. Note that VCAST_CUDA implies 
 * VCAST_ENABLE_DATA_CLEAR_API.
 */
void VCAST_CLEAR_COVERAGE_DATA_ID(void);

void VCAST_DUMP_COVERAGE_DATA (void) {
    int deviceCount;

    /* write flag indicating we are dumping host data */
    VCAST_WRITE_COVERAGE_DATA ( "CUDA HOST" );
    /* dump coverage data for the host "device" */
    VCAST_DUMP_COVERAGE_DATA_DEVICE();
    /* Now clear all of the host buffers so we won't dump them over and over.
     * Use the internal clear function, which only clears data buffers, 
     * and not the main (non-ID) call which will close TESTINSS.DAT. That
     * results in it being overwritten if VCAST_APPEND_TO_TESTINSS isn't 
     * enabled.
     */
    VCAST_CLEAR_COVERAGE_DATA_ID();

    /* get the number of devices available */
    cudaError_t error_id = cudaGetDeviceCount(&deviceCount);
    /* continue if success */
    if ( error_id == cudaSuccess ) {
        int dev;

#ifdef VCAST_CUDA_ENABLE_DRIVER_API
        if (vcast_cuda_registrations == NULL) {
#endif
            /* No registered dump contexts; loop over every device 
             * and dump from its primary context */
            for (dev = 0; dev < deviceCount; ++dev) {
                /* set the device to query */
                cudaSetDevice(dev);
                int major=0, minor=0;
                /* print the device architecture flag */
                cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, dev);
                cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, dev);
                /* 13 = length of "CUDA ARCH_" + 2-digit family + terminating null */
                char prompt[13];
                unsigned family = major * 10 + minor;
                sprintf ( prompt, "CUDA ARCH_%d", family );
                VCAST_WRITE_COVERAGE_DATA ( prompt );
                /* copy device coverage data to the host */
                VCAST_CUDA_COLLECT_DEVICE_COVERAGE(family);
                /* dump the device coverage data */
                VCAST_DUMP_COVERAGE_DATA_DEVICE();
            } /* loop through devices */
#ifdef VCAST_CUDA_ENABLE_DRIVER_API
        } else /* vcast_cuda_registrations != NULL */ {
            /* One or more registered device contexts exist. Dump from 
             * registered contexts only. */
            vcastCudaDeviceContext_t *reg = vcast_cuda_registrations;
            
            /* walk list and dump as we go. */
            while (reg) {
                /* set device */
                cudaSetDevice(reg->dev);
                
                /* set context */
                if (reg->ctx != NULL) {
                    cuCtxSetCurrent(reg->ctx);
                }
                
                /* set coverage module for symbol lookup (if applicable) */
                if (reg->hmod != NULL) {
                    vcast_cuda_coverage_module = reg->hmod;                
                }
                
                /* write out coverage preamble */
                char prompt[13];
                unsigned family;
                if (reg->show_as != 0) {
                    /* If registration specified a family as which to display 
                     * coverage, then honor that. This is useful if, say,
                     * a PTX image is built for compute_30 (and thus the
                     * VectorCAST projects will be "ARCH_30"), but you're 
                     * running the code on something like an arch_53 device. 
                     */                     
                    family = reg->show_as;
                } else {
                    /* Otherwise, use the actual device properties */
                    int major=0, minor=0;
                    cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, dev);
                    cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, dev);
                    family = major * 10 + minor;
                }
                sprintf ( prompt, "CUDA ARCH_%d", family );
                VCAST_WRITE_COVERAGE_DATA ( prompt );
                
                /* collect coverage data from selected device/context */
                VCAST_CUDA_COLLECT_DEVICE_COVERAGE(family);
                
                /* write out the collected device coverage data */
                VCAST_DUMP_COVERAGE_DATA_DEVICE();
                
                /* clean up */
                vcast_cuda_coverage_module = NULL;
                
                /* move to next registration */    
                reg = reg->next;
            }
        }
#endif /* defined(VCAST_CUDA_ENABLE_DRIVER_API) */
    } /* successful query */
#ifndef VCAST_UNIT_TEST_TOOL
#ifndef VCAST_USE_STDOUT
    VCAST_CLOSE_FILE();
#endif
#endif
} /* VCAST_DUMP_COVERAGE_DATA for CUDA */

void VCAST_DUMP_COVERAGE_DATA_DEVICE (void)
#else
#ifndef VCAST_COVER_NO_STDIO
void VCAST_DUMP_COVERAGE_DATA (void)
#endif /* VCAST_COVER_NO_STDIO */
#endif
#ifndef VCAST_COVER_NO_STDIO
{
#if defined(VCAST_COVERAGE_IO_BUFFERED)
#if defined(VCAST_DUMP_BINARY_COVERAGE) && defined(VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
  VCAST_DUMP_BINARY_COVERAGE_DATA_ID();
#else
  VCAST_DUMP_COVERAGE_DATA_ID();
#endif
#ifdef VCAST_DUMP_CALLBACK
  VCAST_DUMP_CALLBACK ();
#endif /* VCAST_DUMP_CALLBACK */
#ifndef VCAST_UNIT_TEST_TOOL
#ifndef VCAST_USE_STDOUT
#ifndef VCAST_CUDA
  VCAST_CLOSE_FILE();
#endif
#endif
#endif
#endif /* VCAST_COVERAGE_IO_BUFFERED */
}
#endif /* VCAST_COVER_NO_STDIO */

#if defined (VCAST_ENABLE_DATA_CLEAR_API) || defined(VCAST_CUDA)
static void VCAST_CLEAR_BUFFER(char* buffer, unsigned int size )
{
  unsigned int i = 0;
    for (; i < size; ++i)
        buffer[i] = 0;
}

#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifndef VCAST_USE_STATIC_MEMORY
static void vcast_freeVCAST_AVLTree( VCAST_AVLTree root )
{
  if( root )
  {
    vcast_freeVCAST_AVLTree(root->left);
    vcast_freeVCAST_AVLTree(root->right);
    VCAST_free(root->element);
    VCAST_free(root);
  }
}
#endif
#endif

void VCAST_CLEAR_COVERAGE_DATA_ID(void);

void
VCAST_CLEAR_COVERAGE_DATA_ID(void)
{
#if defined(VCAST_COVERAGE_IO_BUFFERED)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
  VCAST_CLEAR_BUFFER(vcast_coverage_bytes, sizeof(vcast_coverage_bytes) / sizeof(char));
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifndef VCAST_USE_STATIC_MEMORY
    {
      int unique_id;
      for (unique_id = 0; unique_id < sizeof(vcast_mcdc_bytes) / sizeof(VCAST_AVLTree); ++unique_id)
      {
        vcast_freeVCAST_AVLTree(vcast_mcdc_bytes[unique_id]);
      }
    }
#endif
    VCAST_CLEAR_BUFFER ( (char*)vcast_mcdc_bytes, sizeof(vcast_mcdc_bytes) );
#endif
#endif /* if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */

#else
#ifdef VCAST_STATIC_REGISTRATION
  const struct vcast_unit_values_s *vcast_unit_cur;
  for (vcast_unit_cur = vcast_unit_values_head; vcast_unit_cur;
       vcast_unit_cur = vcast_unit_cur->previous) {
#else  /*VCAST_STATIC_REGISTRATION*/
  const struct vcast_unit_list *vcast_unit_cur;
  for (vcast_unit_cur = vcast_unit_list_values; vcast_unit_cur->vcast_unit;
       ++vcast_unit_cur) {
#endif /*VCAST_STATIC_REGISTRATION*/
#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined (VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_function_array, vcast_unit_cur->vcast_function_bytes );
#endif
#if defined(VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_CLEAR_BUFFER( vcast_unit_cur->vcast_fn_call_array, vcast_unit_cur->vcast_fn_call_bytes);
#endif
#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) ||    \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_statement_array,  vcast_unit_cur->vcast_statement_bytes );
#endif
#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined(VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_branch_array, vcast_unit_cur->vcast_branch_bytes );
#endif
#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifndef VCAST_USE_STATIC_MEMORY
    {
      int unique_id;
      for (unique_id = 0; unique_id < vcast_unit_cur->vcast_mcdc_statement_count; ++unique_id)
      {
        vcast_freeVCAST_AVLTree(vcast_unit_cur->vcast_mcdc_array[unique_id]);
      }
    }
#endif
    VCAST_CLEAR_BUFFER ( (char*)vcast_unit_cur->vcast_mcdc_array, vcast_unit_cur->vcast_mcdc_statement_count * sizeof(VCAST_AVLTree) );
#endif /* #ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#ifdef VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 0
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_0, VCAST_OPTIMIZED_MCDC_BYTES_0_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_0) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 1
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_1, VCAST_OPTIMIZED_MCDC_BYTES_1_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_1) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 2
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_2, VCAST_OPTIMIZED_MCDC_BYTES_2_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_2) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 3
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_3, VCAST_OPTIMIZED_MCDC_BYTES_3_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_3) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 4
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_4, VCAST_OPTIMIZED_MCDC_BYTES_4_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_4) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 5
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_5, VCAST_OPTIMIZED_MCDC_BYTES_5_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_5) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 6
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_6, VCAST_OPTIMIZED_MCDC_BYTES_6_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_6) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 7
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_7, VCAST_OPTIMIZED_MCDC_BYTES_7_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_7) );
#endif
#if VCAST_OPTIMIZED_MCDC_STORAGE_THRESHOLD >= 8
    VCAST_CLEAR_BUFFER ( vcast_unit_cur->vcast_optimized_mcdc_array_8, VCAST_OPTIMIZED_MCDC_BYTES_8_SIZE(vcast_unit_cur->vcast_optimized_mcdc_bytes_8) );
#endif
#endif /* VCAST_USE_OPTIMIZED_MCDC_INSTRUMENTATION */
#endif /* if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) */
  }
#endif
#if defined(VCAST_COVERAGE_TYPE_COUPLING) || defined(VCAST_COUPLING_APPLIED)
    vcastCouplingDataInit();
#endif
#endif /* VCAST_COVERAGE_IO_BUFFERED */
}

void 
VCAST_CLEAR_COVERAGE_DATA(void)
{
#if defined(VCAST_COVERAGE_IO_BUFFERED)
  VCAST_CLEAR_COVERAGE_DATA_ID();
#endif /* VCAST_COVERAGE_IO_BUFFERED */

#ifdef VCAST_USE_BUFFERED_ASCII_DATA
  vcast_ascii_coverage_data_pool[0] = 0;
  vcast_ascii_coverage_data_pos = 0;
  vcast_coverage_data_buffer_full = 0;
#endif

#ifndef VCAST_UNIT_TEST_TOOL
#ifndef VCAST_USE_STDOUT
  VCAST_CLOSE_FILE();
#endif
#endif

#if defined (VCAST_COVERAGE_TYPE_MCDC) || defined(VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#ifdef VCAST_USE_STANDARD_MCDC_INSTRUMENTATION
#ifdef VCAST_USE_STATIC_MEMORY
   vcast_mcdc_statement_pool_ptr = vcast_mcdc_statement_pool;
   vcast_avlnode_pool_ptr = vcast_avlnode_pool;
#endif /* VCAST_USE_STATIC_MEMORY */
   vcast_max_mcdc_statements_exceeded = 0;
#endif /* VCAST_USE_STANDARD_MCDC_INSTRUMENTATION */
#endif
}
#endif /* VCAST_ENABLE_DATA_CLEAR_API */


#ifndef VCAST_COVERAGE_POINTS_AS_MACROS

/***************************** Functions for Function Call Coverage **************************************** */

#if defined VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) || \
  defined(VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#if defined(VCAST_COVERAGE_IO_ANIMATION)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_FN_CALL_INSTRUMENTATION_POINT_ANIMATION(int id)
{
  return VCAST_WRITE_GLOBAL_FN_CALL_ID(id);
}
#else
int VCAST_FN_CALL_INSTRUMENTATION_POINT_ANIMATION(int unit, int id)
{
  return VCAST_WRITE_FN_CALL_ID(unit, id);
}
#endif
#elif defined (VCAST_COVERAGE_IO_BUFFERED)
#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_CUDA
#undef VCAST_FN_CALL_INSTRUMENTATION_POINT_BUFFERED
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_GLOBAL_FN_CALL_INSTRUMENTATION_POINT_BUFFERED(int id)
{
  return vcast_coverage_bytes[id >> 3] |= (((unsigned long)1) << (id % 8));
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_FN_CALL_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id)
{
#if defined(__CUDA_ARCH__)
  return atomicOr(&(((int*)covdata)[id >> 5]), (((unsigned long)1) << (id % 32)));
#else
  return covdata[id >> 3] |= (char)(((unsigned long)1) << (id % 8));
#endif
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#else
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_FN_CALL_INSTRUMENTATION_POINT_BUFFERED(int id)
{
  vcast_coverage_bytes[id] = 1;
  return 1;
}
#else
int VCAST_FN_CALL_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id)
{
#if defined(__CUDA_ARCH__)
  covdata_device[id] = 1;
#else
  covdata[id] = 1;
#endif
  return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS*/
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */

#elif defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_GLOBAL_FN_CALL_INSTRUMENTATION_POINT_REALTIME(int id)
{
  return ((vcast_coverage_bytes[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (vcast_coverage_bytes[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_GLOBAL_FN_CALL_ID(id)) : 1;
}
#else
int VCAST_GLOBAL_FN_CALL_INSTRUMENTATION_POINT_REALTIME(int id)
{
  if (vcast_coverage_bytes[id] == 0) {
      vcast_coverage_bytes[id] = 1;
      VCAST_WRITE_GLOBAL_FN_CALL_ID(id);
  }
  return 1;
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else
#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_FN_CALL_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  return ((covdata[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (covdata[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_FN_CALL_ID(unit, id)) : 1;
}
#else
int VCAST_FN_CALL_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  if (covdata[id] == 0) {
      covdata[id] = 1;
      VCAST_WRITE_FN_CALL_ID(unit, id);
  }
  return 1;
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */

#endif /* VCAST_COVERAGE_IO_ANIMATION */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL */

/***************************** Functions for Statement Coverage **************************************** */

#if defined(VCAST_COVERAGE_TYPE_STATEMENT) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH ) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_CALL) ||   \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
  defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)

#if defined(VCAST_COVERAGE_IO_ANIMATION)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_STATEMENT_INSTRUMENTATION_POINT_ANIMATION(int id)
{
  return VCAST_WRITE_GLOBAL_STATEMENT_ID(id);
}
#else
int VCAST_STATEMENT_INSTRUMENTATION_POINT_ANIMATION(int unit, int id)
{
  return VCAST_WRITE_STATEMENT_ID(unit, id);
}
#endif

#elif defined (VCAST_COVERAGE_IO_BUFFERED) && defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_CUDA
#undef VCAST_STATEMENT_INSTRUMENTATION_POINT_BUFFERED
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_GLOBAL_STATEMENT_INSTRUMENTATION_POINT_BUFFERED(int id)
{
  return vcast_coverage_bytes[id >> 3] |= (((unsigned long)1) << (id % 8));
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_STATEMENT_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id)
{
#if defined(__CUDA_ARCH__)
  return atomicOr(&(((int*)covdata)[id >> 5]), (((unsigned long)1) << (id % 32)));
#else
  return covdata[id >> 3] |= (char)(((unsigned long)1) << (id % 8));
#endif
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#elif defined (VCAST_COVERAGE_IO_BUFFERED) && !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_STATEMENT_INSTRUMENTATION_POINT_BUFFERED(int id)
{
  vcast_coverage_bytes[id] = 1;
  return 1;
}
#else
int VCAST_STATEMENT_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id)
{
#if defined(__CUDA_ARCH__)
  covdata_device[id] = 1;
#else
  covdata[id] = 1;
#endif
  return 1;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS*/
#elif defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_GLOBAL_STATEMENT_INSTRUMENTATION_POINT_REALTIME(int id)
{
  if (vcast_coverage_bytes[id] == 0) {
      vcast_coverage_bytes[id] = 1;
      VCAST_WRITE_GLOBAL_STATEMENT_ID(id);
  }
  return 1;
}

#else
int VCAST_GLOBAL_STATEMENT_INSTRUMENTATION_POINT_REALTIME(int id)
{
  return ((vcast_coverage_bytes[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (vcast_coverage_bytes[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_GLOBAL_STATEMENT_ID(id)) : 1;
} 
#endif
#elif !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_STATEMENT_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  if (covdata[id] == 0) {
      covdata[id] = 1;
      VCAST_WRITE_STATEMENT_ID(unit, id);
  }
  return 1;
}

#else
int VCAST_STATEMENT_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  return ((covdata[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (covdata[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_STATEMENT_ID(unit, id)) : 1;
} 


#endif /*type of COVERAGE_IO*/
#endif /*statement instrumentation*/

/***************************** Functions for Function Coverage **************************************** */

#if defined(VCAST_COVERAGE_TYPE_FUNCTION) || \
    defined (VCAST_COVERAGE_TYPE_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL) || \
    defined (VCAST_COVERAGE_TYPE_STATEMENT_MCDC_FUNCTION_FUNCTION_CALL)
#if defined(VCAST_COVERAGE_IO_ANIMATION)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_FUNCTION_INSTRUMENTATION_POINT_ANIMATION(int id)
{
  return VCAST_WRITE_GLOBAL_FUNCTION_ID(id);
}
#else
int VCAST_FUNCTION_INSTRUMENTATION_POINT_ANIMATION(int unit, int id)
{
  return VCAST_WRITE_FUNCTION_ID(unit, id);
}
#endif
#elif defined (VCAST_COVERAGE_IO_BUFFERED)
#if defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_CUDA
#undef VCAST_FUNCTION_INSTRUMENTATION_POINT_BUFFERED
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_GLOBAL_FUNCTION_INSTRUMENTATION_POINT_BUFFERED(int id){

  return vcast_coverage_bytes[id >> 3] |= (((unsigned long)1) << (id % 8));
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_FUNCTION_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id){

#if defined(__CUDA_ARCH__)
  return atomicOr(&(((int*)covdata)[id >> 5]), (((unsigned long)1) << (id % 32)));
#else
  return covdata[id >> 3] |= (char)(((unsigned long)1) << (id % 8));
#endif
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#else
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_FUNCTION_INSTRUMENTATION_POINT_BUFFERED(int id)
{
  vcast_coverage_bytes[id] = 1;
  return 0;
}
#else
int VCAST_FUNCTION_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id)
{
#if defined(__CUDA_ARCH__)
  covdata_device[id] = 1;
#else
  covdata[id] = 1;
#endif
  return 0;
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */

#elif defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_GLOBAL_FUNCTION_INSTRUMENTATION_POINT_REALTIME(int id)
{
  if (vcast_coverage_bytes[id] == 0) {
      vcast_coverage_bytes[id] = 1;
      VCAST_WRITE_GLOBAL_FUNCTION_ID(id);
  }
  return 1;
}

#else
int VCAST_GLOBAL_FUNCTION_INSTRUMENTATION_POINT_REALTIME(int id)
{
  return ((vcast_coverage_bytes[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (vcast_coverage_bytes[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_GLOBAL_FUNCTION_ID(id)) : 1;
} 
#endif
#elif !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_FUNCTION_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  if (covdata[id] == 0) {
      covdata[id] = 1;
      VCAST_WRITE_FUNCTION_ID(unit, id);
  }
  return 1;
}

#else
int VCAST_FUNCTION_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id)
{
  return ((covdata[id >> 3] & (((unsigned long)1) << id % 8)) == 0) ?
    (covdata[id >> 3] |= (char)(((unsigned long)1) << id % 8),
     VCAST_WRITE_FUNCTION_ID(unit, id)) : 1;
} 
#endif /* VCAST_COVERAGE_IO_ANIMATION */
#endif /* VCAST_COVERAGE_TYPE_FUNCTION */

/***************************** Functions for Branch Coverage **************************************** */
#if defined(VCAST_COVERAGE_TYPE_BRANCH) || defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_CALL ) || \
defined (VCAST_COVERAGE_TYPE_STATEMENT_BRANCH_FUNCTION_FUNCTION_CALL )
#if defined(VCAST_COVERAGE_IO_ANIMATION)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_BRANCH_INSTRUMENTATION_POINT_ANIMATION(int id, VCAST_CONDITION_TYP condition, int onPath)
{
  return condition ? 
    (VCAST_WRITE_GLOBAL_BRANCH_ID(id, onPath ? "T" : "TX"), 1) 
    : 
    (VCAST_WRITE_GLOBAL_BRANCH_ID(id, onPath ? "F" : "FX"), 0); 
}
int VCAST_GLOBAL_SINGLE_BRANCH_INSTRUMENTATION_POINT_ANIMATION(int id, VCAST_CONDITION_TYP condition, int onPath)
{
  VCAST_WRITE_GLOBAL_BRANCH_ID(id, onPath? "S" : "SX");
  return condition;
}
#else
int VCAST_BRANCH_INSTRUMENTATION_POINT_ANIMATION(int unit, int id, VCAST_CONDITION_TYP condition, int onPath)
{
  return condition ? 
    (VCAST_WRITE_BRANCH_ID(unit, id, onPath ? "T" : "TX"), 1) 
    : 
    (VCAST_WRITE_BRANCH_ID(unit, id, onPath ? "F" : "FX"), 0); 
}
#endif

#elif defined (VCAST_COVERAGE_IO_BUFFERED) && defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_CUDA
#undef VCAST_BRANCH_INSTRUMENTATION_POINT_BUFFERED
#endif
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_GLOBAL_BRANCH_INSTRUMENTATION_POINT_BUFFERED(int id, VCAST_CONDITION_TYP condition)
{
  return condition ? 
    (vcast_coverage_bytes[id >> 2] |= (((unsigned long)1) << (id % 4 << 1)), 1) 
    : 
    (vcast_coverage_bytes[id >> 2] |= (((unsigned long)1) << ((id % 4 << 1) + 1)), 0); 
}
int VCAST_GLOBAL_SINGLE_BRANCH_INSTRUMENTATION_POINT_BUFFERED(int id, VCAST_CONDITION_TYP condition)
{
  vcast_coverage_bytes[id >> 3] |= (((unsigned long)1) << (id % 8));
  return condition;
}
#else
VCAST_CUDA_HOST_DEVICE_FUNCTION
int VCAST_BRANCH_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id, VCAST_CONDITION_TYP condition)
{
#if defined(__CUDA_ARCH__)
  return condition ?
    (atomicOr(&(((int*)covdata)[id >> 4]), (((unsigned long)1) << (id % 16 << 1))), 1)
    : 
    (atomicOr(&(((int*)covdata)[id >> 4]), (((unsigned long)1) << ((id % 16 << 1) + 1))), 0);
#else
  return condition ? 
    (covdata[id >> 2] |= (char)(((unsigned long)1) << (id % 4 << 1)), 1) 
    : 
    (covdata[id >> 2] |= (char)(((unsigned long)1) << ((id % 4 << 1) + 1)), 0); 
#endif
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#elif defined (VCAST_COVERAGE_IO_BUFFERED) && !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
#ifdef VCAST_GLOBAL_BUFFER_OPTIMIZATIONS
int VCAST_GLOBAL_BRANCH_INSTRUMENTATION_POINT_BUFFERED(int id, VCAST_CONDITION_TYP condition)
{
  if (condition){
    vcast_coverage_bytes[id * 2] = 1;
    return 1;
  }else{
    vcast_coverage_bytes[id * 2 + 1] = 1;
    return 0;
  }
}
int VCAST_GLOBAL_SINGLE_BRANCH_INSTRUMENTATION_POINT_BUFFERED(int id, VCAST_CONDITION_TYP condition)
{
  vcast_coverage_bytes[id] = 1;
  return condition;
}
#else
int VCAST_BRANCH_INSTRUMENTATION_POINT_BUFFERED(char* covdata, int id, VCAST_CONDITION_TYP condition)
{
  if (condition){
#if defined(__CUDA_ARCH__)
    covdata_device[id * 2] = 1;
#else
    covdata[id * 2] = 1;
#endif
    return 1;
  }else{
    covdata[id * 2 + 1] = 1;
    return 0;
  }
}
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#else
#if defined (VCAST_GLOBAL_BUFFER_OPTIMIZATIONS)
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_GLOBAL_BRANCH_INSTRUMENTATION_POINT_REALTIME(int id, VCAST_CONDITION_TYP condition)
{
  if (condition){
    int index = id * 2;
    if (vcast_coverage_bytes[index] == 0) {
        vcast_coverage_bytes[index] = 1;
        VCAST_WRITE_GLOBAL_BRANCH_ID(id, "T");
    }
    return 1;
  }else{
    int index = id * 2 + 1;
    if (vcast_coverage_bytes[index] == 0) {
        vcast_coverage_bytes[index] = 1;
        VCAST_WRITE_GLOBAL_BRANCH_ID(id, "F");
    }
    return 0;
  }
}
int VCAST_GLOBAL_SINGLE_BRANCH_INSTRUMENTATION_POINT_REALTIME(int id, VCAST_CONDITION_TYP condition)
{
  if (vcast_coverage_bytes[id] == 0) {
    vcast_coverage_bytes[id] = 1;
    VCAST_WRITE_GLOBAL_BRANCH_ID(id, "S");
  }
  return condition;
}
#else
int VCAST_GLOBAL_BRANCH_INSTRUMENTATION_POINT_REALTIME(int id, VCAST_CONDITION_TYP condition)
{
  return condition ? 
    (((vcast_coverage_bytes[id >> 2] & (((unsigned long)1) << (id % 4 << 1))) == 0) ? 
     (vcast_coverage_bytes[id >> 2] |= (char)(((unsigned long)1) << (id % 4 << 1)), 
      VCAST_WRITE_GLOBAL_BRANCH_ID(id, "T"), 1) : 1) 
    : 
    (((vcast_coverage_bytes[id >> 2] & (((unsigned long)1) << ((id % 4 << 1) + 1))) == 0) ? 
     (vcast_coverage_bytes[id >> 2] |= (char)(((unsigned long)1) << ((id % 4 << 1) + 1)), 
      VCAST_WRITE_GLOBAL_BRANCH_ID(id, "F"), 0) : 0); 
}
int VCAST_GLOBAL_SINGLE_BRANCH_INSTRUMENTATION_POINT_REALTIME(int id, VCAST_CONDITION_TYP condition)
{
  if ((vcast_coverage_bytes[id >> 3] & (((unsigned long)1) << (id % 8))) == 0)
  {
    vcast_coverage_bytes[id >> 3] |= (char)(((unsigned long)1) << (id % 8));
    VCAST_WRITE_GLOBAL_BRANCH_ID(id, "S");
  }
  return (int)condition;
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#else
#if !defined (VCAST_PACK_INSTRUMENTATION_STORAGE)
int VCAST_BRANCH_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id, VCAST_CONDITION_TYP condition)
{
  if (condition){
    int index = id * 2;
    if (covdata[index] == 0) {
        covdata[index] = 1;
        VCAST_WRITE_BRANCH_ID(unit, id, "T");
    }
    return 1;
  }else{
    int index = id * 2 + 1;
    if (covdata[index] == 0) {
        covdata[index] = 1;
        VCAST_WRITE_BRANCH_ID(unit, id, "F");
    }
    return 0;
  }
}

#else
int VCAST_BRANCH_INSTRUMENTATION_POINT_REALTIME(char* covdata, int unit, int id, VCAST_CONDITION_TYP condition)
{
  return condition ? 
    (((covdata[id >> 2] & (((unsigned long)1) << (id % 4 << 1))) == 0) ? 
     (covdata[id >> 2] |= (char)(((unsigned long)1) << (id % 4 << 1)), 
      VCAST_WRITE_BRANCH_ID(unit, id, "T"), 1) : 1) 
    : 
    (((covdata[id >> 2] & (((unsigned long)1) << ((id % 4 << 1) + 1))) == 0) ? 
     (covdata[id >> 2] |= (char)(((unsigned long)1) << ((id % 4 << 1) + 1)), 
      VCAST_WRITE_BRANCH_ID(unit, id, "F"), 0) : 0); 
}
#endif /* VCAST_PACK_INSTRUMENTATION_STORAGE */
#endif /* VCAST_GLOBAL_BUFFER_OPTIMIZATIONS */
#endif /*type of COVERAGE_IO*/
#endif /* Branch */
#endif /* VCAST_COVERAGE_POINTS_AS_MACROS */

#endif /*VCAST_COVER_IO_COVER_CODE*/
