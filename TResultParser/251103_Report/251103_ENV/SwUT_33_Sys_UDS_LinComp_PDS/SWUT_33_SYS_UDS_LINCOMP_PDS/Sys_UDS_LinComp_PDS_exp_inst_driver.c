/*vcast_separate_expansion_start:S0000009.c*/
/*vcast_header_expansion_start:vcast_env_defines.h*/
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:Sys_UDS_LinComp_PDS_driver_prefix.c*/
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:S0000009.h*/
void vectorcast_initialize_io (int inst_status, int inst_fd);
void vectorcast_terminate_io (void);
void vectorcast_write_vcast_end (void);
int  vectorcast_fflush(int fpn);
void vectorcast_fclose(int fpn);
int  vectorcast_feof(int fpn);
int  vectorcast_fopen(const char *filename, const char *mode);
char *vectorcast_fgets (char *line, int maxline, int fpn);
int vectorcast_readline(char *vcast_buf, int fpn);
void vectorcast_fprint_char   (int fpn, char vcast_str);
void vectorcast_fprint_char_hex ( int fpn, char vcast_value );
void vectorcast_fprint_char_octl ( int fpn, char vcast_value );
void vectorcast_fprint_string (int fpn, const char *vcast_str);
void vectorcast_fprint_string_with_cr (int fpn, const char *vcast_str);
void vectorcast_print_string (const char *vcast_str);
void vectorcast_fprint_string_with_length(int fpn, const char *vcast_str, int length);
void vectorcast_fprint_short     (int vcast_fpn, short vcast_value );
void vectorcast_fprint_integer   (int vcast_fpn, int vcast_value );
void vectorcast_fprint_long      (int vcast_fpn, long vcast_value );
void vectorcast_fprint_long_long (int vcast_fpn, long vcast_value );
void vectorcast_fprint_unsigned_short (int vcast_fpn,
                                       unsigned short vcast_value );
void vectorcast_fprint_unsigned_integer (int vcast_fpn,
                                         unsigned int vcast_value );
void vectorcast_fprint_unsigned_long (int vcast_fpn,
                                      unsigned long vcast_value );
void vectorcast_fprint_unsigned_long_long (int vcast_fpn,
                                           unsigned long vcast_value );
void vectorcast_fprint_long_float (int fpn, vCAST_long_double);
void vcast_signed_to_string ( char vcDest[],
                              long vcSrc );
void vcast_unsigned_to_string ( char vcDest[],
                                unsigned long vcSrc );
void vcast_float_to_string ( char *mixed_str, vCAST_long_double vcast_f );
void vectorcast_write_to_std_out (const char *s);
void vcast_char_to_based_string ( char vcDest[],
                                  unsigned char vcSrc,
                                  unsigned vcUseHex );
enum vcast_env_file_kind
{
   VCAST_ASCIIRES_DAT = 1,
   VCAST_EXPECTED_DAT = 2,
   VCAST_TEMP_DIF_DAT = 3,
   VCAST_TESTINSS_DAT = 4,
   VCAST_THISTORY_DAT = 5,
   VCAST_USERDATA_DAT = 6
};
const char *vcast_get_filename(enum vcast_env_file_kind kind);
void vectorcast_set_index(int index, int fpn);
int vectorcast_get_index(int fpn);
extern int vCAST_ITERATION_COUNTERS [3][65];
extern vCAST_array_boolean vCAST_GLOBALS_TOUCHED[5];
enum vCAST_testcase_options_type {
        vCAST_MULTI_RETURN_SPANS_RANGE,
        vCAST_MULTI_RETURN_SPANS_COMPOUND_ITERATIONS,
        vCAST_DISPLAY_INTEGER_RESULTS_IN_HEX,
        vCAST_DISPLAY_FULL_STRING_DATA,
        vCAST_HEX_NOTATION_FOR_UNPRINTABLE_CHARS,
        vCAST_DO_COMBINATION,
        vCAST_REFERENCED_GLOBALS,
        vCAST_FLOAT_POINT_DIGITS_OF_PRECISION,
        vCAST_FLOAT_POINT_TOLERANCE,
        vCAST_EVENT_LIMIT,
        vCAST_GLOBAL_DATA_DISPLAY,
        vCAST_EXPECTED_BEFORE_UUT_CALL,
        vCAST_DATA_PARTITIONS,
        vCAST_SHOW_ONLY_DATA_WITH_EXPECTED_RESULTS,
        vCAST_SHOW_ONLY_EVENTS_WITH_EXPECTED_RESULTS};
enum vCAST_globals_display_type {
        vCAST_EACH_EVENT,
        vCAST_RANGE_ITERATION,
        vCAST_SLOT_ITERATION,
        vCAST_TESTCASE};
void vCAST_INITIALIZE_PARAMETERS(void);
void vCAST_USER_CODE_INITIALIZE(int vcast_slot_index);
void vCAST_USER_CODE_CAPTURE (void);
void vCAST_USER_CODE_CAPTURE_GLOBALS (void);
void vCAST_ONE_SHOT_INIT(void);
void vCAST_ONE_SHOT_TERM(void);
void vCAST_GLOBAL_STUB_PROCESSING(void);
void vCAST_GLOBAL_BEGINNING_OF_STUB_PROCESSING(void);
typedef enum {
   VCAST_UCT_VALUE,
   VCAST_UCT_EXPECTED,
   VCAST_UCT_EXPECTED_GLOBALS
} VCAST_USER_CODE_TYPE;
void vCAST_USER_CODE( VCAST_USER_CODE_TYPE uct, int vcast_slot_index );
/*vcast_header_collapse_start:C:\\FREESCALE\\CWMCUV~1.7\\MCU\\S12LISA_SUPPORT\\S12LISAC\\INCLUDE\\stdlib.h*/
typedef const char * ConstString;
typedef const char * LIBDEF_ConstStringPtr;
typedef       char *  LIBDEF_StringPtr;
typedef const void *    ConstMem;
typedef const void *    LIBDEF_ConstMemPtr;
typedef       void *     LIBDEF_MemPtr;
typedef       char  LIBDEF_MemByte;
typedef       LIBDEF_MemByte *     LIBDEF_MemBytePtr;
typedef const LIBDEF_MemByte *     LIBDEF_ConstMemBytePtr;
typedef struct _div_t {
  int quot, rem;
} div_t;
typedef struct _ldiv_t {
  long int quot, rem;
} ldiv_t;
LIBDEF_StringPtr _itoa(int val, LIBDEF_StringPtr buf, int radix);
extern double            strtod  (LIBDEF_ConstStringPtr s, LIBDEF_StringPtr *end);
extern long int          strtol  (LIBDEF_ConstStringPtr s, LIBDEF_StringPtr *end, int base);
extern unsigned long int strtoul (LIBDEF_ConstStringPtr s, LIBDEF_StringPtr *end, int base);
extern int  rand  (void);
extern void srand (unsigned int seed);
extern void * calloc(size_t n, size_t size);
extern void                    free(void * ptr);
extern void * malloc(size_t size);
extern void * realloc(void * ptr, size_t size);
extern void  abort   (void);
extern int   atexit  (void (*func) (void));
extern void  exit    (int status);
extern LIBDEF_StringPtr getenv(LIBDEF_ConstStringPtr name);
extern int              system(LIBDEF_ConstStringPtr cmd);
extern LIBDEF_MemPtr bsearch (LIBDEF_ConstMemPtr look_for,
                           LIBDEF_ConstMemPtr base_addr,
                           size_t n, size_t size,
                           int (*cmp) (LIBDEF_ConstMemPtr, LIBDEF_ConstMemPtr));  
extern void qsort (LIBDEF_ConstMemPtr base,
                   size_t n, size_t size,
                   int (*cmp) (LIBDEF_ConstMemPtr, LIBDEF_ConstMemPtr));  
extern int      abs   (int j);
extern long int labs  (long int j);
extern div_t    div   (int dividend, int divisor);
extern ldiv_t   ldiv  (long int dividend, long int divisor);
extern int mblen(LIBDEF_ConstStringPtr mbs, size_t n);
extern int mbtowc(wchar_t *wc, LIBDEF_ConstStringPtr mb, size_t n);
extern int wctomb(LIBDEF_StringPtr mb, wchar_t wc);
extern size_t mbstowcs(wchar_t *wc, LIBDEF_ConstStringPtr mb, size_t n);
extern size_t wcstombs(LIBDEF_StringPtr mb, const wchar_t *wc, size_t n);
/*vcast_header_collapse_end*/
/*vcast_header_collapse_start:C:\\FREESCALE\\CWMCUV~1.7\\MCU\\S12LISA_SUPPORT\\S12LISAC\\INCLUDE\\setjmp.h*/
typedef struct JMPB
{
	void (*sp) (void);
	void (*pc) (void);
} jmp_buf[1];
extern int _setjmp (jmp_buf env);
extern void longjmp (jmp_buf env, int res);
/*vcast_header_collapse_end*/
/*vcast_header_collapse_start:C:\\FREESCALE\\CWMCUV~1.7\\MCU\\S12LISA_SUPPORT\\S12LISAC\\INCLUDE\\stdio.h*/
  typedef char *va_list;
extern LIBDEF_MemPtr memchr  (LIBDEF_ConstMemPtr buffer, int chr, size_t count);
extern int           memcmp  (LIBDEF_ConstMemPtr buf1, LIBDEF_ConstMemPtr buf2, size_t count);
extern LIBDEF_MemPtr memcpy  (LIBDEF_MemPtr dest, LIBDEF_ConstMemPtr source, size_t count);
extern void          memcpy2(LIBDEF_MemPtr dest, LIBDEF_ConstMemPtr source, size_t count);
extern void _memcpy_8bitCount(LIBDEF_MemPtr dest, LIBDEF_ConstMemPtr source, unsigned char count);
extern LIBDEF_MemPtr memmove (LIBDEF_MemPtr dest, LIBDEF_ConstMemPtr source, size_t count);
extern LIBDEF_MemPtr memset  (LIBDEF_MemPtr buffer, int chr, size_t count);
extern void _memset_clear_8bitCount(LIBDEF_MemPtr buffer, unsigned char count);
extern size_t  strlen  (LIBDEF_ConstStringPtr str);
extern LIBDEF_StringPtr strset  (LIBDEF_StringPtr str, int chr);
extern LIBDEF_StringPtr strcat  (LIBDEF_StringPtr str_d, LIBDEF_ConstStringPtr str_s);
extern LIBDEF_StringPtr strncat (LIBDEF_StringPtr str_d, LIBDEF_ConstStringPtr str_s, size_t count);
extern LIBDEF_StringPtr strcpy  (LIBDEF_StringPtr str_d, LIBDEF_ConstStringPtr str_s);
extern LIBDEF_StringPtr strncpy (LIBDEF_StringPtr str_d, LIBDEF_ConstStringPtr str_s, size_t count);
extern int     strcmp  (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2);
extern int     strncmp (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2, size_t count);
extern LIBDEF_StringPtr strchr  (LIBDEF_ConstStringPtr str, int chr);
extern LIBDEF_StringPtr strrchr (LIBDEF_ConstStringPtr str, int chr);
extern size_t  strspn  (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2);
extern size_t  strcspn (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2);
extern LIBDEF_StringPtr strpbrk (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2);
extern LIBDEF_StringPtr strstr  (LIBDEF_ConstStringPtr str1, LIBDEF_ConstStringPtr str2);
extern LIBDEF_StringPtr strtok  (LIBDEF_StringPtr str1, LIBDEF_ConstStringPtr str2);
extern LIBDEF_StringPtr strerror(int errnum);
extern int strcoll(LIBDEF_ConstStringPtr string1, LIBDEF_ConstStringPtr string2);
extern size_t strxfrm(LIBDEF_StringPtr strDest, LIBDEF_ConstStringPtr strSource, size_t count);
extern int errno;
typedef struct chnl {
  char *channel_name;         
  char *port_addr;            
  char  flags;                
  char  lastchar;             
  int   (*open_channel)();    
  int   (*close_channel)();   
  int   (*read_channel)();    
  int   (*write_channel)();   
} FILE;
extern FILE channels[1];
typedef long      fpos_t;
int fputc(int c, FILE *stream);
extern FILE *   fopen   (LIBDEF_ConstStringPtr name, LIBDEF_ConstStringPtr mode);
extern int      fsetpos (FILE * f, const fpos_t * pos);
extern int      scanf(LIBDEF_ConstStringPtr s, ...);                                      
extern int      sscanf(LIBDEF_ConstStringPtr s, LIBDEF_ConstStringPtr format, ...);       
extern int      vsscanf(LIBDEF_ConstStringPtr s, LIBDEF_ConstStringPtr format, va_list args);
extern int      puts(LIBDEF_ConstStringPtr s);
extern int      printf(LIBDEF_ConstStringPtr s, ...);                                      
extern int      fprintf(FILE *f, LIBDEF_ConstStringPtr, ...);                              
extern int      vfprintf(FILE *f, LIBDEF_ConstStringPtr s, va_list args);
extern int      sprintf(LIBDEF_StringPtr s, LIBDEF_ConstStringPtr format, ...);            
extern int      vsprintf(LIBDEF_StringPtr s, LIBDEF_ConstStringPtr format, va_list args);
extern int      snprintf(LIBDEF_StringPtr s, size_t n, LIBDEF_ConstStringPtr format, ...);           
extern int      vsnprintf(LIBDEF_StringPtr s, size_t n, LIBDEF_ConstStringPtr format, va_list args);
extern void set_printf(void (*f)(char));  
extern int vprintf(LIBDEF_ConstStringPtr format, va_list args);
extern int      fclose  (FILE * f);
extern FILE *   freopen (const char * name, const char * mode, FILE * f);
extern int      remove  (LIBDEF_ConstStringPtr name);
extern int      rename  (const char * old_name, const char * new_name);
extern FILE *   tmpfile (void);
extern char *   tmpnam  (char * name);
extern int      fflush  (FILE * f);
extern void     setbuf  (FILE * f, char * buf);
extern int      setvbuf (FILE * f, char * buf, int mode, size_t size);
extern int      fgetpos (FILE * f, long *pos);
extern int      fseek   (FILE * f, long offset, int mode);
extern long int ftell   (FILE * f);
extern void     rewind  (FILE * f);
extern int      fgetc   (FILE * f);
extern size_t   fread   (void * buf, size_t size, size_t n, FILE * f);
extern size_t   fwrite  (const void * buf, size_t size, size_t n, FILE * f);
extern LIBDEF_StringPtr fgets   (LIBDEF_StringPtr s, int n, FILE * f);
extern int      fputs   (LIBDEF_ConstStringPtr s, FILE * f);
extern int      fscanf  (FILE * f, const char * s, ...);  
extern int      ungetc  (int c, FILE * f);
extern LIBDEF_StringPtr gets(LIBDEF_StringPtr s);
/*vcast_header_collapse_end*/
void * VCAST_malloc (unsigned int vcast_size);
int VCAST_signed_strlen (const signed char *vcast_str );
void VCAST_signed_strcpy ( signed char *VC_S, const signed char *VC_T );
 extern jmp_buf VCAST_env;
typedef long int vCAST_BIG_INT;
enum    vCAST_COMMAND_TYPE { vCAST_SET_VAL,
                             vCAST_PRINT,
                             vCAST_FIRST_VAL,
                             vCAST_MID_VAL,
                             vCAST_LAST_VAL,
                             vCAST_POS_INF_VAL,
                             vCAST_NEG_INF_VAL,
                             vCAST_NAN_VAL,
                             vCAST_MIN_MINUS_1_VAL,
                             vCAST_MAX_PLUS_1_VAL,
                             vCAST_ZERO_VAL,
                             vCAST_KEEP_VAL,
                             vCAST_ALLOCATE,
                             vCAST_STUB_FUNCTION,
                             vCAST_FUNCTION }; 
struct vCAST_HIST_ENTRY {
  int VC_U;
  int VC_S;
};
struct vCAST_ORDER_ENTRY {
  int  slotIterations;                             
  char testFilename[13];        
  char testName[256];          
  char slotDescriptor[256];
  char printEventData[256];
};
enum vcTypeOfRangeExpression { 
   VCAST_NULL_TYPE = 0,
   VCAST_RANGE_TYPE,
   VCAST_LIST_TYPE
};
struct vcRangeDataType
{
  char  *vCAST_COMMAND;                        
  enum  vcTypeOfRangeExpression rangeType;     
  vCAST_long_double vCAST_MIN;                 
  vCAST_long_double vCAST_MAX;                 
  vCAST_long_double vCAST_INC;                 
  char  *vCAST_list;                           
  int isInteger;               
  int vCAST_COMBO_GROUPING;  
  int vCAST_NUM_VALS;
};
vCAST_double      vCAST_power (short vcast_bits);
vCAST_long_double VCAST_itod  ( char vcastStringParam[] );
void vCAST_SET_TESTCASE_CONFIGURATION_OPTIONS( int VCAST_option,int VCAST_value, int VCAST_set_default);
void vCAST_SET_TESTCASE_OPTIONS (const  char vcast_options[] );
void vCAST_RUN_DATA_IF (const char *VCAST_PARAM, vCAST_boolean POST_CONSTRUCTOR_USER_CODE);
void vCAST_slice (char vcast_target[], const char vcast_source[], int vcast_first, int vcast_last);
void vCAST_EXTRACT_DATA_FROM_COMMAND_LINE (char *vcast_buf, char VCAST_PARAM[], int VC_POSITION);
void vCAST_STR_TO_LONG_DOUBLE(char vcastStringParam[], vCAST_long_double * vcastFloatParam);
void vCAST_DOUBLE_TO_STR (vCAST_long_double VC_F, char VC_S[], int VC_AS_INT);
void vCAST_RESET_LIST_VALUES(void);
void vCAST_ITERATION_COUNTER_RESET(void);
void vCAST_RESET_ITERATION_COUNTERS(enum vCAST_testcase_options_type );
int  vCAST_GET_ITERATION_COUNTER_VALUE(int, int);
void vCAST_INCREMENT_ITERATION_COUNTER(int, int);
void vCAST_EXECUTE_RANGE_COMMANDS (int);
int vCAST_ITERATION_COUNTER_SWITCH(int);
void vCAST_GET_RANGE_VALUES(char *vcast_S, struct vcRangeDataType *vcast_range_data);
typedef unsigned char vcast_sbf_object_type;
void VCAST_TI_SBF_OBJECT(vcast_sbf_object_type* vcast_param);
void vCAST_RESET_RANGE_VALUES (void);
void vCAST_INITIALIZE_RANGE_VALUES (void);
void vcGetCommandDetails (const char* vcCommand, int* vcStartOfValue, int* vcNumberOfValues);
void vcResetRangeDataArray(void);
void vCAST_STORE_GLOBAL_ASCII_DATA (void);
void vCAST_CREATE_EVENT_FILE (void);
void vCAST_CREATE_HIST_FILE (void);
void vCAST_OPEN_HIST_FILE (void);
void vCAST_CREATE_INST_FILE (void);
void vCAST_openHarnessFiles (void);
void vCAST_closeHarnessFiles (void);
long VCAST_convert_encoded_field(const char *vcast_str);
void vCAST_CREATE_INST_FILE (void);
void VCAST_WRITE_TO_INST_FILE (const char VC_S[]);
void vCAST_CLOSE_INST_FILE (void);
void vCAST_CLOSE_INST_FILE (void);
void vCAST_CLOSE_EVENT_FILE (void);
void vCAST_CLOSE_HIST_FILE (void);
void vCAST_WRITE_END_FILE(void);
void vCAST_OPEN_E0_FILE (void);
void vcastSetHarnessOptionsFromFile(void);
void vcastSetTestCaseOptionsToDefault(void);
void vCAST_OPEN_TESTORDR_FILE (void);
void VCAST_READ_TESTORDER_LINE ( char[] );
void vCAST_STORE_ASCII_DATA ( int, int, const char* );
vCAST_boolean vCAST_READ_NEXT_ORDER (void);
vCAST_boolean vCAST_SHOULD_DISPLAY_GLOBALS ( int, const char*);
void vcastStartOfSlot (void);
void vcastStartOfSlotIteration (void);
void vcastStartOfRangeIteration (void);
vCAST_boolean vcastEndOfIteration (int slotIteration, int rangeIteration);
void vcastGetKeyTestValues (void);
extern int    vcast_user_file;
extern int    VCAST_EXP_FILE;
extern int    vCAST_UNIT;
extern int    vCAST_SUBPROGRAM;
extern int    vCAST_CURRENT_SLOT;
extern unsigned int    vCAST_HIST_INDEX;
extern unsigned int    vCAST_HIST_LIMIT;
extern unsigned int    vCAST_ENV_HIST_LIMIT;
extern int    vcRangeIterationsForThisTest;
extern int    vCAST_RANGE_COUNTER;
extern int    vcSlotIteration;
extern int    vcRangeIteration;
extern vCAST_boolean vCAST_DO_DATA_IF;
extern vCAST_boolean vCAST_HAS_RANGE;
extern vCAST_boolean vCAST_SKIP_ITER;
extern int    vcRangeDataIndex;
extern struct vcRangeDataType vcRangeCommands[];
extern struct vCAST_ORDER_ENTRY vCAST_ORDER_OBJECT;
extern vCAST_long_double vCAST_PARTITIONS;
extern int vCAST_INST_FILE;
extern int vCAST_ASCIIRES_FILE;
extern int vCAST_THISTORY_FILE;
extern int vCAST_ORDER_FILE;
extern int vCAST_E0_FILE;
extern int vCAST_OUTPUT_FILE;
extern int vCAST_COUNT;
extern int vCAST_CURRENT_COUNT;
extern vCAST_array_boolean vCAST_TESTCASE_OPTIONS[15];
extern vCAST_boolean vcast_is_in_union;
extern vCAST_boolean vCAST_INST_FILE_OPEN;
extern vCAST_boolean vCAST_ASCIIRES_FILE_OPEN;
extern vCAST_boolean vCAST_THISTORY_FILE_OPEN;
extern vCAST_boolean VCAST_DEFAULT_FULL_STRINGS;
extern vCAST_boolean VCAST_DEFAULT_HEX_NOTATION;
extern vCAST_boolean VCAST_DEFAULT_PROBE_POINTS_AS_EVENTS;
extern vCAST_boolean VCAST_DEFAULT_DO_COMBINATION;
extern unsigned short VCAST_GLOBALS_DISPLAY;  
extern vCAST_boolean VCAST_GLOBAL_FIRST_EVENT;
extern vCAST_boolean vCAST_HEX_NOTATION;   
extern vCAST_boolean vCAST_PROBE_POINTS_AS_EVENTS;   
extern vCAST_boolean vCAST_DO_COMBINATION_TESTING; 
void VCAST_driver_termination(int vcast_status, int eventCode);
int vcast_get_hc_id (char *vcast_command);
void vcast_get_unit_id_str (char *vcast_command, char *vcast_unit);
int vcast_get_unit_id (char *vcast_command);
void vcast_get_subprogram_id_str (char *vcast_command, char *vcast_subprogram);
int vcast_get_subprogram_id (char *vcast_command);
void vcast_get_parameter_id_str (char *vcast_command, char *vcast_subprogram);
int vcast_get_parameter_id (char *vcast_command);
int vcast_get_percent_pos (const char *vcast_command);
void vCAST_END(void);
void VCAST_SLOT_SEPARATOR ( vCAST_boolean VC_EndOfSlot);
void vcastInitializeS2Data (void);
void vcastInitializeB2Data (void);
void vCAST_RE_OPEN_HIST_FILE(void);
/*vcast_header_collapse_start:C:\\FREESCALE\\CWMCUV~1.7\\MCU\\S12LISA_SUPPORT\\S12LISAC\\INCLUDE\\limits.h*/
/*vcast_header_collapse_end*/
void VCAST_get_indices(char *str_val, int *array_size);
void vcast_not_supported (void);
void vcast_get_range_value ( int *vCAST_FIRST_VAL,
                             int *vCAST_LAST_VAL);
int vcast_get_param (void);
int VCAST_FIND_INDEX (void);
vCAST_double vCAST_power (short vcast_bits);
void VCAST_TI_BITFIELD ( long *vc_VAL, int Bits,  vCAST_boolean is_signed );
void VCAST_TI_STRING ( 
      char **vcast_param, 
      int from_bounded_array,
      int size_of_bounded_array );
int vcast_add_to_hex(int previousNumber, char latestDigit);
char vcast_get_non_numerical_escape(char character);
int vcast_convert_size(char * input);
char * VCAST_convert(char * input);
vCAST_boolean vcast_proc_handles_command(int vc_m);
void VCAST_SET_GLOBAL_SIZE(unsigned int *vcast_size);
unsigned int *VCAST_GET_GLOBAL_SIZE(void);
extern int vCAST_FILE;
extern char vCAST_PARAMETER[256];
extern char vCAST_PARAMETER_KEY[256];
long VCAST_PARAM_AS_LONGEST_INT(void);
unsigned long VCAST_PARAM_AS_LONGEST_UNSIGNED(void);
vCAST_long_double VCAST_PARAM_AS_LONGEST_FLOAT(void);
extern int vCAST_INDEX;
extern int vCAST_DATA_FIELD;
extern enum vCAST_COMMAND_TYPE vCAST_COMMAND;
extern vCAST_boolean vCAST_VALUE_NUL;
extern vCAST_boolean vCAST_can_print_constructor;
struct VCAST_CSU_Data_Item
{
  void *vcast_item;
  char *vcast_command;
  struct VCAST_CSU_Data_Item *vcast_next;
};
struct VCAST_CSU_Data;
void VCAST_Add_CSU_Data (struct VCAST_CSU_Data **vcast_data, 
                         struct VCAST_CSU_Data_Item *vcast_data_item);
struct VCAST_CSU_Data_Item *VCAST_Get_CSU_Data ( 
                         struct VCAST_CSU_Data **vcast_data,
                         char *vcast_command);
void vcastInitializeB1Data(void);
void VCAST_DRIVER_8( int VC_SUBPROGRAM );
void VCAST_DRIVER_9( int VC_SUBPROGRAM );void VCAST_SBF_9( int VC_SUBPROGRAM );
/*vcast_header_expansion_end*/
/*vcast_header_collapse_start:vcast_undef_9.h*/
/*vcast_header_collapse_end*/
/*vcast_header_expansion_start:vcast_uc_prototypes.h*/
void vCAST_VALUE_USER_CODE_8(int vcast_slot_index );
void vCAST_EXPECTED_USER_CODE_8(int vcast_slot_index );
void vCAST_EGLOBALS_USER_CODE_8(int vcast_slot_index );
void vCAST_STUB_PROCESSING_8(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_BEGIN_STUB_PROC_8(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_COMMON_STUB_PROC_8(
            int unitIndex,
            int subprogramIndex,
            int robjectIndex,
            int readEobjectData );
void vCAST_VALUE_USER_CODE_9(int vcast_slot_index );
void vCAST_EXPECTED_USER_CODE_9(int vcast_slot_index );
void vCAST_EGLOBALS_USER_CODE_9(int vcast_slot_index );
void vCAST_STUB_PROCESSING_9(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_BEGIN_STUB_PROC_9(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_COMMON_STUB_PROC_9(
            int unitIndex,
            int subprogramIndex,
            int robjectIndex,
            int readEobjectData );
void vCAST_VALUE_USER_CODE_9(int vcast_slot_index );
void vCAST_EXPECTED_USER_CODE_9(int vcast_slot_index );
void vCAST_EGLOBALS_USER_CODE_9(int vcast_slot_index );
void vCAST_STUB_PROCESSING_9(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_BEGIN_STUB_PROC_9(
        int  UnitIndex, 
        int  SubprogramIndex );
void vCAST_COMMON_STUB_PROC_9(
            int unitIndex,
            int subprogramIndex,
            int robjectIndex,
            int readEobjectData );
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:vcast_objs_9.c*/
unsigned char  *P_9_1_1;
unsigned char  P_9_1_2;
unsigned char  P_9_1_3;
unsigned char SBF_9_1 = 0;
unsigned  *P_9_2_1;
unsigned  P_9_2_2;
unsigned char  P_9_2_3;
unsigned char SBF_9_2 = 0;
unsigned char  P_9_3_1;
unsigned char  P_9_3_2;
unsigned char  P_9_3_3;
unsigned char  R_9_3;
unsigned char SBF_9_3 = 0;
unsigned  P_9_4_1;
unsigned  P_9_4_2;
unsigned  P_9_4_3;
unsigned char  R_9_4;
unsigned char SBF_9_4 = 0;
signed int  P_9_5_1;
signed int  P_9_5_2;
signed int  P_9_5_3;
unsigned char  R_9_5;
unsigned char SBF_9_5 = 0;
unsigned  P_9_6_1;
unsigned  R_9_6;
unsigned char SBF_9_6 = 0;
unsigned char  P_9_7_1;
unsigned  R_9_7;
unsigned char SBF_9_7 = 0;
unsigned char SBF_9_8 = 0;
unsigned char SBF_9_9 = 0;
unsigned  P_9_10_1;
unsigned char SBF_9_10 = 0;
unsigned  P_9_11_1;
unsigned char SBF_9_11 = 0;
unsigned  P_9_12_1;
unsigned char SBF_9_12 = 0;
unsigned  P_9_13_1;
unsigned char SBF_9_13 = 0;
unsigned char SBF_9_14 = 0;
unsigned char SBF_9_15 = 0;
unsigned char SBF_9_16 = 0;
unsigned char SBF_9_17 = 0;
unsigned char SBF_9_18 = 0;
unsigned char SBF_9_19 = 0;
unsigned char SBF_9_20 = 0;
unsigned char SBF_9_21 = 0;
unsigned char SBF_9_22 = 0;
unsigned char SBF_9_23 = 0;
unsigned char SBF_9_24 = 0;
unsigned char SBF_9_25 = 0;
unsigned char SBF_9_26 = 0;
unsigned char SBF_9_27 = 0;
unsigned char SBF_9_28 = 0;
unsigned char SBF_9_29 = 0;
unsigned char  P_9_30_1;
unsigned char SBF_9_30 = 0;
unsigned char  P_9_31_1;
unsigned char SBF_9_31 = 0;
unsigned char SBF_9_32 = 0;
unsigned char SBF_9_33 = 0;
unsigned char SBF_9_34 = 0;
unsigned char SBF_9_35 = 0;
unsigned char SBF_9_36 = 0;
unsigned char SBF_9_37 = 0;
unsigned char SBF_9_38 = 0;
unsigned char SBF_9_39 = 0;
unsigned char SBF_9_40 = 0;
unsigned char SBF_9_41 = 0;
unsigned char SBF_9_42 = 0;
unsigned char SBF_9_43 = 0;
unsigned char SBF_9_44 = 0;
unsigned char SBF_9_45 = 0;
unsigned char SBF_9_46 = 0;
unsigned char SBF_9_47 = 0;
unsigned char SBF_9_48 = 0;
unsigned char SBF_9_49 = 0;
unsigned char SBF_9_50 = 0;
unsigned char SBF_9_51 = 0;
unsigned char SBF_9_52 = 0;
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:vcast_stubs_9.c*/
U8  u8g_Lib_Sha256_Hash[(U8 )32U] 
;
lin_transport_layer_queue  lin_tl_rx_queue 
;
U16  u16g_SysDiag_SystemStatus 
;
U16  u16g_SysDiag_BuzzerLevelMax 
;
U8  u8g_SysDiag_MotorOverHeatActiveHold_F 
;
U8  u8g_SysEepromCtrl_SleepMode 
;
U8  u8g_SysEepromCtrl_MotorA1A2Output 
;
U16  u16g_SysOptCtrl_OverOpenDeg 
;
S16  s16g_SysOptCtrl_OverPos 
;
U8  u8g_ApiIn_MotorDirection 
;
U8  u8g_ApiIn_MotorCountSpeed 
;
U8  u8g_ApiIn_MotorRps 
;
U16  u16g_ApiIn_MotorLevel_A1 
;
U16  u16g_ApiIn_MotorLevel_A2 
;
S16  s16g_ApiIn_MotorCurrLvl 
;
U16  u16g_ApiIn_MotorTempLvl 
;
U16  u16g_ApiIn_HallSnsrLevel 
;
U16  u16g_ApiIn_Vsup 
;
U16  u16g_ApiIn_BandGap 
;
S16  s16g_ApiIn_MotorPosition 
;
U8  u8g_ApiOut_DoorAngle 
;
U8  u8g_ApiOut_DoorState 
;
U8  u8g_ApiOut_MotorCurrent 
;
U8  u8g_ApiOut_Vsup 
;
U8  u8g_DoorPreCtrl_MotorOverHeat_F 
;
E_LIB_SHA256_NB_STATE  R_10_1;
E_LIB_SHA256_NB_STATE  g_Lib_Sha256_Nb_GetState(void)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    vCAST_COMMON_STUB_PROC_9( 10, 1, 1, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_1;
}
unsigned short  P_10_2_1;
unsigned char  *P_10_2_2;
void  ld_send_message(l_u16  length, const l_u8  *const data)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_2_1 = length;
    P_10_2_2 = ((unsigned char  *)(data));
    vCAST_COMMON_STUB_PROC_9( 10, 2, 3, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return;
}
unsigned  P_10_3_1;
unsigned char  R_10_3;
U8  u8g_SysEepromCtrl_ReadInlineData(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_3_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 3, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_3;
}
unsigned  P_10_4_1;
unsigned char  R_10_4;
U8  u8g_SysEepromCtrl_ReadDiagData(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_4_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 4, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_4;
}
unsigned  P_10_5_1;
unsigned char  R_10_5;
U8  u8g_SysEepromCtrl_ReadProdDate(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_5_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 5, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_5;
}
unsigned  P_10_6_1;
unsigned char  R_10_6;
U8  u8g_SysEepromCtrl_ReadPartNo(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_6_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 6, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_6;
}
unsigned  P_10_7_1;
unsigned char  R_10_7;
U8  u8g_SysEepromCtrl_ReadHwVer(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_7_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 7, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_7;
}
unsigned  P_10_8_1;
unsigned char  R_10_8;
U8  u8g_SysEepromCtrl_ReadDbVer(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_8_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 8, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_8;
}
unsigned  P_10_9_1;
unsigned char  R_10_9;
U8  u8g_SysEepromCtrl_ReadCrcByte(U16  u16t_Offset)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_9_1 = u16t_Offset;
    vCAST_COMMON_STUB_PROC_9( 10, 9, 2, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_9;
}
unsigned  P_10_10_1;
unsigned  P_10_10_2;
unsigned char  R_10_10;
U8  u8g_SysEepromCtrl_ReadUdsData(U16  u16t_Addr1, U16  u16t_Addr2)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    P_10_10_1 = u16t_Addr1;
    P_10_10_2 = u16t_Addr2;
    vCAST_COMMON_STUB_PROC_9( 10, 10, 3, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return R_10_10;
}
void  g_SysEepromCtrl_Reset(void)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    vCAST_COMMON_STUB_PROC_9( 10, 11, 1, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return;
}
void  g_SysOptionCtrl(void)
{
  vCAST_USER_CODE_TIMER_STOP();
  if ( vcast_is_in_driver ) {
    vCAST_COMMON_STUB_PROC_9( 10, 12, 1, 0 );
  }  
  vCAST_USER_CODE_TIMER_START();
  return;
}
/*vcast_header_expansion_end*/
void VCAST_DRIVER_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 0:
      vCAST_SET_HISTORY_FLAGS ( 9, 0);
      vCAST_USER_CODE_TIMER_START();
      break;
    case 7: {
      vCAST_SET_HISTORY_FLAGS ( 9, 7 );
      vCAST_USER_CODE_TIMER_START();
      R_9_7 = 
      ( u16s_Pwm2Spd_Conv(
        ( P_9_7_1 ) ) );
      break; }
    case 8: {
      vCAST_SET_HISTORY_FLAGS ( 9, 8 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_RDBI_Paser( ) );
      break; }
    case 9: {
      vCAST_SET_HISTORY_FLAGS ( 9, 9 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ExtractParams( ) );
      break; }
    case 10: {
      vCAST_SET_HISTORY_FLAGS ( 9, 10 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessDatePartInfo(
        ( P_9_10_1 ) ) );
      break; }
    case 11: {
      vCAST_SET_HISTORY_FLAGS ( 9, 11 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessVersionInfo(
        ( P_9_11_1 ) ) );
      break; }
    case 12: {
      vCAST_SET_HISTORY_FLAGS ( 9, 12 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessSystemInfo(
        ( P_9_12_1 ) ) );
      break; }
    case 13: {
      vCAST_SET_HISTORY_FLAGS ( 9, 13 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProcessSystemStatus(
        ( P_9_13_1 ) ) );
      break; }
    case 14: {
      vCAST_SET_HISTORY_FLAGS ( 9, 14 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_ProdDate( ) );
      break; }
    case 15: {
      vCAST_SET_HISTORY_FLAGS ( 9, 15 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_PartNumber( ) );
      break; }
    case 16: {
      vCAST_SET_HISTORY_FLAGS ( 9, 16 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Version( ) );
      break; }
    case 17: {
      vCAST_SET_HISTORY_FLAGS ( 9, 17 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_HW_Version( ) );
      break; }
    case 18: {
      vCAST_SET_HISTORY_FLAGS ( 9, 18 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_DB_Version( ) );
      break; }
    case 19: {
      vCAST_SET_HISTORY_FLAGS ( 9, 19 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Unit1_Version( ) );
      break; }
    case 20: {
      vCAST_SET_HISTORY_FLAGS ( 9, 20 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_SW_Unit1_IVD( ) );
      break; }
    case 21: {
      vCAST_SET_HISTORY_FLAGS ( 9, 21 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck1( ) );
      break; }
    case 22: {
      vCAST_SET_HISTORY_FLAGS ( 9, 22 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck2( ) );
      break; }
    case 23: {
      vCAST_SET_HISTORY_FLAGS ( 9, 23 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_RDBI_StatusCheck3( ) );
      break; }
    case 24: {
      vCAST_SET_HISTORY_FLAGS ( 9, 24 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_WDBI_Paser( ) );
      break; }
    case 25: {
      vCAST_SET_HISTORY_FLAGS ( 9, 25 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UserOptRecordId( ) );
      break; }
    case 26: {
      vCAST_SET_HISTORY_FLAGS ( 9, 26 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOptMain( ) );
      break; }
    case 27: {
      vCAST_SET_HISTORY_FLAGS ( 9, 27 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_F1G( ) );
      break; }
    case 28: {
      vCAST_SET_HISTORY_FLAGS ( 9, 28 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_1( ) );
      break; }
    case 29: {
      vCAST_SET_HISTORY_FLAGS ( 9, 29 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2( ) );
      break; }
    case 30: {
      vCAST_SET_HISTORY_FLAGS ( 9, 30 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup1(
        ( P_9_30_1 ) ) );
      break; }
    case 31: {
      vCAST_SET_HISTORY_FLAGS ( 9, 31 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_2_ProcessGroup2(
        ( P_9_31_1 ) ) );
      break; }
    case 32: {
      vCAST_SET_HISTORY_FLAGS ( 9, 32 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_UsOpt_E2G_3( ) );
      break; }
    case 33: {
      vCAST_SET_HISTORY_FLAGS ( 9, 33 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_ProdDate( ) );
      break; }
    case 34: {
      vCAST_SET_HISTORY_FLAGS ( 9, 34 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_PartNumber( ) );
      break; }
    case 35: {
      vCAST_SET_HISTORY_FLAGS ( 9, 35 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_HW_Version( ) );
      break; }
    case 36: {
      vCAST_SET_HISTORY_FLAGS ( 9, 36 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_DB_Version( ) );
      break; }
    case 37: {
      vCAST_SET_HISTORY_FLAGS ( 9, 37 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ReadEeprom( ) );
      break; }
    case 38: {
      vCAST_SET_HISTORY_FLAGS ( 9, 38 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_WiteEeprom( ) );
      break; }
    case 39: {
      vCAST_SET_HISTORY_FLAGS ( 9, 39 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ApplyParam( ) );
      break; }
    case 40: {
      vCAST_SET_HISTORY_FLAGS ( 9, 40 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ClearEeprom( ) );
      break; }
    case 41: {
      vCAST_SET_HISTORY_FLAGS ( 9, 41 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_ReadSysSts( ) );
      break; }
    case 42: {
      vCAST_SET_HISTORY_FLAGS ( 9, 42 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_UserCtrl( ) );
      break; }
    case 43: {
      vCAST_SET_HISTORY_FLAGS ( 9, 43 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_OpDataRead( ) );
      break; }
    case 44: {
      vCAST_SET_HISTORY_FLAGS ( 9, 44 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_SysOpt( ) );
      break; }
    case 45: {
      vCAST_SET_HISTORY_FLAGS ( 9, 45 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_BuzzTest( ) );
      break; }
    case 46: {
      vCAST_SET_HISTORY_FLAGS ( 9, 46 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Reprogram( ) );
      break; }
    case 47: {
      vCAST_SET_HISTORY_FLAGS ( 9, 47 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Write_Checksum( ) );
      break; }
    case 48: {
      vCAST_SET_HISTORY_FLAGS ( 9, 48 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_WDBI_US_Read_Checksum( ) );
      break; }
    case 49: {
      vCAST_SET_HISTORY_FLAGS ( 9, 49 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_SessionCtrl( ) );
      break; }
    case 50: {
      vCAST_SET_HISTORY_FLAGS ( 9, 50 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_DSC_ProgSession( ) );
      break; }
    case 51: {
      vCAST_SET_HISTORY_FLAGS ( 9, 51 );
      vCAST_USER_CODE_TIMER_START();
      ( s_UDS_SendNRC22_ConditionsNotCorrect( ) );
      break; }
    case 52: {
      vCAST_SET_HISTORY_FLAGS ( 9, 52 );
      vCAST_USER_CODE_TIMER_START();
      ( g_UDS_LinComp_Reset( ) );
      break; }
    default:
      vectorcast_print_string("ERROR: Internal Tool Error\n");
      break;
  }  
  vCAST_USER_CODE_TIMER_STOP();
}
void VCAST_SBF_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 7: {
      SBF_9_7 = 0;
      break; }
    case 8: {
      SBF_9_8 = 0;
      break; }
    case 9: {
      SBF_9_9 = 0;
      break; }
    case 10: {
      SBF_9_10 = 0;
      break; }
    case 11: {
      SBF_9_11 = 0;
      break; }
    case 12: {
      SBF_9_12 = 0;
      break; }
    case 13: {
      SBF_9_13 = 0;
      break; }
    case 14: {
      SBF_9_14 = 0;
      break; }
    case 15: {
      SBF_9_15 = 0;
      break; }
    case 16: {
      SBF_9_16 = 0;
      break; }
    case 17: {
      SBF_9_17 = 0;
      break; }
    case 18: {
      SBF_9_18 = 0;
      break; }
    case 19: {
      SBF_9_19 = 0;
      break; }
    case 20: {
      SBF_9_20 = 0;
      break; }
    case 21: {
      SBF_9_21 = 0;
      break; }
    case 22: {
      SBF_9_22 = 0;
      break; }
    case 23: {
      SBF_9_23 = 0;
      break; }
    case 24: {
      SBF_9_24 = 0;
      break; }
    case 25: {
      SBF_9_25 = 0;
      break; }
    case 26: {
      SBF_9_26 = 0;
      break; }
    case 27: {
      SBF_9_27 = 0;
      break; }
    case 28: {
      SBF_9_28 = 0;
      break; }
    case 29: {
      SBF_9_29 = 0;
      break; }
    case 30: {
      SBF_9_30 = 0;
      break; }
    case 31: {
      SBF_9_31 = 0;
      break; }
    case 32: {
      SBF_9_32 = 0;
      break; }
    case 33: {
      SBF_9_33 = 0;
      break; }
    case 34: {
      SBF_9_34 = 0;
      break; }
    case 35: {
      SBF_9_35 = 0;
      break; }
    case 36: {
      SBF_9_36 = 0;
      break; }
    case 37: {
      SBF_9_37 = 0;
      break; }
    case 38: {
      SBF_9_38 = 0;
      break; }
    case 39: {
      SBF_9_39 = 0;
      break; }
    case 40: {
      SBF_9_40 = 0;
      break; }
    case 41: {
      SBF_9_41 = 0;
      break; }
    case 42: {
      SBF_9_42 = 0;
      break; }
    case 43: {
      SBF_9_43 = 0;
      break; }
    case 44: {
      SBF_9_44 = 0;
      break; }
    case 45: {
      SBF_9_45 = 0;
      break; }
    case 46: {
      SBF_9_46 = 0;
      break; }
    case 47: {
      SBF_9_47 = 0;
      break; }
    case 48: {
      SBF_9_48 = 0;
      break; }
    case 49: {
      SBF_9_49 = 0;
      break; }
    case 50: {
      SBF_9_50 = 0;
      break; }
    case 51: {
      SBF_9_51 = 0;
      break; }
    case 52: {
      SBF_9_52 = 0;
      break; }
    default:
      break;
  }  
}
/*vcast_header_expansion_start:vcast_ti_decls_9.h*/
void VCAST_TI_9_1 ( unsigned char  vcast_param[(U8 )32U] ) ;
void VCAST_TI_9_10 ( unsigned  *vcast_param ) ;
void VCAST_TI_9_11 ( signed int  *vcast_param ) ;
void VCAST_TI_9_12 ( unsigned char  vcast_param[10] ) ;
void VCAST_TI_9_13 ( unsigned char  vcast_param[60] ) ;
void VCAST_TI_9_14 ( unsigned char  **vcast_param ) ;
void VCAST_TI_9_15 ( unsigned  **vcast_param ) ;
void VCAST_TI_9_16 ( E_LIB_SHA256_NB_STATE  *vcast_param ) ;
void VCAST_TI_9_2 ( unsigned char  *vcast_param ) ;
void VCAST_TI_9_3 ( lin_transport_layer_queue  *vcast_param ) ;
void VCAST_TI_9_5 ( unsigned short  *vcast_param ) ;
void VCAST_TI_9_6 ( ld_queue_status  *vcast_param ) ;
void VCAST_TI_9_8 ( unsigned char  (**vcast_param)[8] ) ;
void VCAST_TI_9_9 ( unsigned char  vcast_param[8] ) ;
/*vcast_header_expansion_end*/
void VCAST_RUN_DATA_IF_9( int VCAST_SUB_INDEX, int VCAST_PARAM_INDEX ) {
  switch ( VCAST_SUB_INDEX ) {
    case 0:  
      switch( VCAST_PARAM_INDEX ) {
        case 18:  
          VCAST_TI_9_1 ( u8g_Lib_Sha256_Hash);
          break;
        case 19:  
          VCAST_TI_9_3 ( &(lin_tl_rx_queue));
          break;
        case 20:  
          VCAST_TI_9_10 ( &(u16g_SysDiag_SystemStatus));
          break;
        case 21:  
          VCAST_TI_9_10 ( &(u16g_SysDiag_BuzzerLevelMax));
          break;
        case 22:  
          VCAST_TI_9_2 ( &(u8g_SysDiag_MotorOverHeatActiveHold_F));
          break;
        case 23:  
          VCAST_TI_9_2 ( &(u8g_SysEepromCtrl_SleepMode));
          break;
        case 24:  
          VCAST_TI_9_2 ( &(u8g_SysEepromCtrl_MotorA1A2Output));
          break;
        case 25:  
          VCAST_TI_9_10 ( &(u16g_SysOptCtrl_OverOpenDeg));
          break;
        case 26:  
          VCAST_TI_9_11 ( &(s16g_SysOptCtrl_OverPos));
          break;
        case 27:  
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorDirection));
          break;
        case 28:  
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorCountSpeed));
          break;
        case 29:  
          VCAST_TI_9_2 ( &(u8g_ApiIn_MotorRps));
          break;
        case 30:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorLevel_A1));
          break;
        case 31:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorLevel_A2));
          break;
        case 32:  
          VCAST_TI_9_11 ( &(s16g_ApiIn_MotorCurrLvl));
          break;
        case 33:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_MotorTempLvl));
          break;
        case 34:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_HallSnsrLevel));
          break;
        case 35:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_Vsup));
          break;
        case 36:  
          VCAST_TI_9_10 ( &(u16g_ApiIn_BandGap));
          break;
        case 37:  
          VCAST_TI_9_11 ( &(s16g_ApiIn_MotorPosition));
          break;
        case 38:  
          VCAST_TI_9_2 ( &(u8g_ApiOut_DoorAngle));
          break;
        case 39:  
          VCAST_TI_9_2 ( &(u8g_ApiOut_DoorState));
          break;
        case 40:  
          VCAST_TI_9_2 ( &(u8g_ApiOut_MotorCurrent));
          break;
        case 41:  
          VCAST_TI_9_2 ( &(u8g_ApiOut_Vsup));
          break;
        case 42:  
          VCAST_TI_9_2 ( &(u8g_DoorPreCtrl_MotorOverHeat_F));
          break;
        case 1:  
          VCAST_TI_9_2 ( &(u8g_SysUds_UsDoorCtrl));
          break;
        case 2:  
          VCAST_TI_9_2 ( &(u8g_SysUds_UsAutoOpenEn_F));
          break;
        case 3:  
          VCAST_TI_9_2 ( &(u8g_SysUds_UsDir));
          break;
        case 4:  
          VCAST_TI_9_2 ( &(u8g_SysUds_UsStepMsb));
          break;
        case 5:  
          VCAST_TI_9_2 ( &(u8g_SysUds_UsStepLsb));
          break;
        case 6:  
          VCAST_TI_9_2 ( &(u8g_SysUds_WdbiCmd));
          break;
        case 7:  
          VCAST_TI_9_2 ( &(u8g_SysUds_BuzzerTest_F));
          break;
        case 8:  
          VCAST_TI_9_12 ( u8g_SysUds_WriteData);
          break;
        case 9:  
          VCAST_TI_9_10 ( &(u16g_SysUds_UsMotorPwm));
          break;
        case 10:  
          VCAST_TI_9_10 ( &(u16g_SysUds_UsStep));
          break;
        case 11:  
          VCAST_TI_9_2 ( &(u8s_UdsSid));
          break;
        case 12:  
          VCAST_TI_9_2 ( &(u8s_DidMsb));
          break;
        case 13:  
          VCAST_TI_9_2 ( &(u8s_DidLsb));
          break;
        case 14:  
          VCAST_TI_9_2 ( &(u8s_SwIntVer));
          break;
        case 15:  
          VCAST_TI_9_13 ( u8s_DataBuffer);
          break;
        case 16:  
          VCAST_TI_9_2 ( &(u8s_UserServiceIdMsb));
          break;
        case 17:  
          VCAST_TI_9_2 ( &(u8s_UserServiceIdLsb));
          break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      }  
      break;  
    case 1:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_14 ( &(P_9_1_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_1_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_1_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_1 );
          break;
      }  
      break;  
    case 2:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_15 ( &(P_9_2_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_9_2_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_2_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_2 );
          break;
      }  
      break;  
    case 3:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_3_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(P_9_3_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(P_9_3_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_3));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_3 );
          break;
      }  
      break;  
    case 4:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_4_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_9_4_2));
          break;
        case 3:
          VCAST_TI_9_10 ( &(P_9_4_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_4));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_4 );
          break;
      }  
      break;  
    case 5:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_11 ( &(P_9_5_1));
          break;
        case 2:
          VCAST_TI_9_11 ( &(P_9_5_2));
          break;
        case 3:
          VCAST_TI_9_11 ( &(P_9_5_3));
          break;
        case 4:
          VCAST_TI_9_2 ( &(R_9_5));
          break;
        case 5:
          VCAST_TI_SBF_OBJECT( &SBF_9_5 );
          break;
      }  
      break;  
    case 53:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_16 ( &(R_10_1));
          break;
      }  
      break;  
    case 54:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_5 ( &(P_10_2_1));
          break;
        case 2:
          VCAST_TI_9_14 ( &(P_10_2_2));
          break;
      }  
      break;  
    case 55:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_3_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_3));
          break;
      }  
      break;  
    case 56:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_4_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_4));
          break;
      }  
      break;  
    case 57:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_5_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_5));
          break;
      }  
      break;  
    case 58:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_6_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_6));
          break;
      }  
      break;  
    case 59:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_7_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_7));
          break;
      }  
      break;  
    case 60:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_8_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_8));
          break;
      }  
      break;  
    case 61:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_9_1));
          break;
        case 2:
          VCAST_TI_9_2 ( &(R_10_9));
          break;
      }  
      break;  
    case 62:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_10_10_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(P_10_10_2));
          break;
        case 3:
          VCAST_TI_9_2 ( &(R_10_10));
          break;
      }  
      break;  
    case 6:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_6_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(R_9_6));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_6 );
          break;
      }  
      break;  
    case 7:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_7_1));
          break;
        case 2:
          VCAST_TI_9_10 ( &(R_9_7));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_7 );
          break;
      }  
      break;  
    case 8:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_8 );
          break;
      }  
      break;  
    case 9:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_9 );
          break;
      }  
      break;  
    case 10:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_10_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_10 );
          break;
      }  
      break;  
    case 11:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_11_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_11 );
          break;
      }  
      break;  
    case 12:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_12_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_12 );
          break;
      }  
      break;  
    case 13:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_10 ( &(P_9_13_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_13 );
          break;
      }  
      break;  
    case 14:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_14 );
          break;
      }  
      break;  
    case 15:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_15 );
          break;
      }  
      break;  
    case 16:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_16 );
          break;
      }  
      break;  
    case 17:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_17 );
          break;
      }  
      break;  
    case 18:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_18 );
          break;
      }  
      break;  
    case 19:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_19 );
          break;
      }  
      break;  
    case 20:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_20 );
          break;
      }  
      break;  
    case 21:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_21 );
          break;
      }  
      break;  
    case 22:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_22 );
          break;
      }  
      break;  
    case 23:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_23 );
          break;
      }  
      break;  
    case 24:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_24 );
          break;
      }  
      break;  
    case 25:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_25 );
          break;
      }  
      break;  
    case 26:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_26 );
          break;
      }  
      break;  
    case 27:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_27 );
          break;
      }  
      break;  
    case 28:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_28 );
          break;
      }  
      break;  
    case 29:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_29 );
          break;
      }  
      break;  
    case 30:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_30_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_30 );
          break;
      }  
      break;  
    case 31:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_2 ( &(P_9_31_1));
          break;
        case 2:
          VCAST_TI_SBF_OBJECT( &SBF_9_31 );
          break;
      }  
      break;  
    case 32:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_32 );
          break;
      }  
      break;  
    case 33:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_33 );
          break;
      }  
      break;  
    case 34:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_34 );
          break;
      }  
      break;  
    case 35:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_35 );
          break;
      }  
      break;  
    case 36:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_36 );
          break;
      }  
      break;  
    case 37:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_37 );
          break;
      }  
      break;  
    case 38:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_38 );
          break;
      }  
      break;  
    case 39:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_39 );
          break;
      }  
      break;  
    case 40:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_40 );
          break;
      }  
      break;  
    case 41:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_41 );
          break;
      }  
      break;  
    case 42:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_42 );
          break;
      }  
      break;  
    case 43:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_43 );
          break;
      }  
      break;  
    case 44:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_44 );
          break;
      }  
      break;  
    case 45:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_45 );
          break;
      }  
      break;  
    case 46:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_46 );
          break;
      }  
      break;  
    case 47:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_47 );
          break;
      }  
      break;  
    case 48:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_48 );
          break;
      }  
      break;  
    case 49:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_49 );
          break;
      }  
      break;  
    case 50:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_50 );
          break;
      }  
      break;  
    case 51:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_51 );
          break;
      }  
      break;  
    case 52:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_SBF_OBJECT( &SBF_9_52 );
          break;
      }  
      break;  
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  }  
}
void VCAST_TI_9_1 ( unsigned char  vcast_param[(U8 )32U] ) 
{
  {
    int VCAST_TI_9_1_array_index = 0;
    int VCAST_TI_9_1_index = 0;
    int VCAST_TI_9_1_first, VCAST_TI_9_1_last;
    int VCAST_TI_9_1_local_field = 0;
    int VCAST_TI_9_1_value_printed = 0;
    int VCAST_TI_9_1_is_string = (VCAST_FIND_INDEX()==-1);
    vcast_get_range_value (&VCAST_TI_9_1_first, &VCAST_TI_9_1_last);
    VCAST_TI_9_1_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_1_upper = 32;
      for (VCAST_TI_9_1_array_index=0; VCAST_TI_9_1_array_index< VCAST_TI_9_1_upper; VCAST_TI_9_1_array_index++){
        if ( (VCAST_TI_9_1_index >= VCAST_TI_9_1_first) && ( VCAST_TI_9_1_index <= VCAST_TI_9_1_last)){
          if ( VCAST_TI_9_1_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_1_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_1_index]));
          VCAST_TI_9_1_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_1_local_field;
        }  
        if (VCAST_TI_9_1_index >= VCAST_TI_9_1_last)
          break;
        VCAST_TI_9_1_index++;
      }  
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_1_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
}  
void VCAST_TI_9_3 ( lin_transport_layer_queue  *vcast_param ) 
{
  {
    switch ( vcast_get_param () ) {  
      case 1: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_header));
        break;  
      }  
      case 2: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_tail));
        break;  
      }  
      case 3: { 
        VCAST_TI_9_6 ( &(vcast_param->queue_status));
        break;  
      }  
      case 4: { 
        VCAST_TI_9_5 ( &(vcast_param->queue_current_size));
        break;  
      }  
      case 5: { 
        vcast_not_supported();
        break;  
      }  
      case 6: { 
        VCAST_TI_9_8 ( &(vcast_param->tl_pdu));
        break;  
      }  
      default:
        vCAST_TOOL_ERROR = vCAST_true;
    }   
  }
}  
void VCAST_TI_9_10 ( unsigned  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned   ) VCAST_PARAM_AS_LONGEST_UNSIGNED();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = 0;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (0 / 2) + (0xffff / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = 0xffff;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = 0;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = 0xffff;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
}  
}  
void VCAST_TI_9_2 ( unsigned char  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned char   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = 0;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (0 / 2) + (0xff / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = 0xff;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = 0;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = 0xff;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
}  
}  
void VCAST_TI_9_11 ( signed int  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_integer(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL :
    *vcast_param = ( signed int   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = (-32767-1);
    break;
  case vCAST_MID_VAL :
    *vcast_param = ((-32767-1) / 2) + (32767 / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = 32767;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = (-32767-1);
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = 32767;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
}  
}  
void VCAST_TI_9_12 ( unsigned char  vcast_param[10] ) 
{
  {
    int VCAST_TI_9_12_array_index = 0;
    int VCAST_TI_9_12_index = 0;
    int VCAST_TI_9_12_first, VCAST_TI_9_12_last;
    int VCAST_TI_9_12_local_field = 0;
    int VCAST_TI_9_12_value_printed = 0;
    int VCAST_TI_9_12_is_string = (VCAST_FIND_INDEX()==-1);
    vcast_get_range_value (&VCAST_TI_9_12_first, &VCAST_TI_9_12_last);
    VCAST_TI_9_12_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_12_upper = 10;
      for (VCAST_TI_9_12_array_index=0; VCAST_TI_9_12_array_index< VCAST_TI_9_12_upper; VCAST_TI_9_12_array_index++){
        if ( (VCAST_TI_9_12_index >= VCAST_TI_9_12_first) && ( VCAST_TI_9_12_index <= VCAST_TI_9_12_last)){
          if ( VCAST_TI_9_12_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_12_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_12_index]));
          VCAST_TI_9_12_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_12_local_field;
        }  
        if (VCAST_TI_9_12_index >= VCAST_TI_9_12_last)
          break;
        VCAST_TI_9_12_index++;
      }  
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_12_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
}  
void VCAST_TI_9_13 ( unsigned char  vcast_param[60] ) 
{
  {
    int VCAST_TI_9_13_array_index = 0;
    int VCAST_TI_9_13_index = 0;
    int VCAST_TI_9_13_first, VCAST_TI_9_13_last;
    int VCAST_TI_9_13_local_field = 0;
    int VCAST_TI_9_13_value_printed = 0;
    int VCAST_TI_9_13_is_string = (VCAST_FIND_INDEX()==-1);
    vcast_get_range_value (&VCAST_TI_9_13_first, &VCAST_TI_9_13_last);
    VCAST_TI_9_13_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_13_upper = 60;
      for (VCAST_TI_9_13_array_index=0; VCAST_TI_9_13_array_index< VCAST_TI_9_13_upper; VCAST_TI_9_13_array_index++){
        if ( (VCAST_TI_9_13_index >= VCAST_TI_9_13_first) && ( VCAST_TI_9_13_index <= VCAST_TI_9_13_last)){
          if ( VCAST_TI_9_13_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_13_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_13_index]));
          VCAST_TI_9_13_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_13_local_field;
        }  
        if (VCAST_TI_9_13_index >= VCAST_TI_9_13_last)
          break;
        VCAST_TI_9_13_index++;
      }  
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_13_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
}  
void VCAST_TI_9_14 ( unsigned char  **vcast_param ) 
{
  {
    int VCAST_TI_9_14_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_14_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_14_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_14_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_14_array_size*(sizeof(unsigned char  )));
          memset((void*)*vcast_param, 0x0, VCAST_TI_9_14_array_size*(sizeof(unsigned char  )));
          ;
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        if (VCAST_FIND_INDEX() == -1 )
          VCAST_TI_STRING ( (char**)vcast_param, 0,-1);
        else {
          VCAST_TI_9_14_index = vcast_get_param();
          VCAST_TI_9_2 ( &((*vcast_param)[VCAST_TI_9_14_index]));
        }
      }
    }
  }
}  
void VCAST_TI_9_15 ( unsigned  **vcast_param ) 
{
  {
    int VCAST_TI_9_15_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_15_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_15_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_15_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_15_array_size*(sizeof(unsigned  )));
          memset((void*)*vcast_param, 0x0, VCAST_TI_9_15_array_size*(sizeof(unsigned  )));
          ;
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_15_index = vcast_get_param();
        VCAST_TI_9_10 ( &((*vcast_param)[VCAST_TI_9_15_index]));
      }
    }
  }
}  
void VCAST_TI_9_16 ( E_LIB_SHA256_NB_STATE  *vcast_param ) 
{
  switch ( vCAST_COMMAND ) {
    case vCAST_PRINT: {
      if ( vcast_param == 0 )
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_long_long(vCAST_OUTPUT_FILE, (long)*vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }  
      }  
      break;  
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL:
    *vcast_param = (E_LIB_SHA256_NB_STATE  )VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL:
    *vcast_param = E_LIB_SHA256_NB_STATE_IDLE;
    break;  
  case vCAST_LAST_VAL:
    *vcast_param = E_LIB_SHA256_NB_STATE_ERROR;
    break;  
  default:
    vCAST_TOOL_ERROR = vCAST_true;
    break;  
}  
}  
void VCAST_TI_9_5 ( unsigned short  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_short(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned short   ) VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = 0;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (0 / 2) + (0xffff / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = 0xffff;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = 0;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = 0xffff;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
}  
}  
void VCAST_TI_9_6 ( ld_queue_status  *vcast_param ) 
{
  switch ( vCAST_COMMAND ) {
    case vCAST_PRINT: {
      if ( vcast_param == 0 )
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_long_long(vCAST_OUTPUT_FILE, (long)*vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }  
      }  
      break;  
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL:
    *vcast_param = (ld_queue_status  )VCAST_PARAM_AS_LONGEST_INT();
    break;
  case vCAST_FIRST_VAL:
    *vcast_param = LD_NO_DATA;
    break;  
  case vCAST_LAST_VAL:
    *vcast_param = LD_TRANSMIT_ERROR;
    break;  
  default:
    vCAST_TOOL_ERROR = vCAST_true;
    break;  
}  
}  
void VCAST_TI_9_8 ( unsigned char  (**vcast_param)[8] ) 
{
  {
    int VCAST_TI_9_8_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_8_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_8_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_8_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_8_array_size*(sizeof(unsigned char  [8])));
          memset((void*)*vcast_param, 0x0, VCAST_TI_9_8_array_size*(sizeof(unsigned char  [8])));
          ;
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_8_index = vcast_get_param();
        VCAST_TI_9_9 ( (*vcast_param)[VCAST_TI_9_8_index]);
      }
    }
  }
}  
void VCAST_TI_9_9 ( unsigned char  vcast_param[8] ) 
{
  {
    int VCAST_TI_9_9_array_index = 0;
    int VCAST_TI_9_9_index = 0;
    int VCAST_TI_9_9_first, VCAST_TI_9_9_last;
    int VCAST_TI_9_9_local_field = 0;
    int VCAST_TI_9_9_value_printed = 0;
    int VCAST_TI_9_9_is_string = (VCAST_FIND_INDEX()==-1);
    vcast_get_range_value (&VCAST_TI_9_9_first, &VCAST_TI_9_9_last);
    VCAST_TI_9_9_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_9_upper = 8;
      for (VCAST_TI_9_9_array_index=0; VCAST_TI_9_9_array_index< VCAST_TI_9_9_upper; VCAST_TI_9_9_array_index++){
        if ( (VCAST_TI_9_9_index >= VCAST_TI_9_9_first) && ( VCAST_TI_9_9_index <= VCAST_TI_9_9_last)){
          if ( VCAST_TI_9_9_is_string )
            VCAST_TI_STRING ( (char**)&vcast_param, 1,VCAST_TI_9_9_upper);
          else
            VCAST_TI_9_2 ( &(vcast_param[VCAST_TI_9_9_index]));
          VCAST_TI_9_9_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_9_local_field;
        }  
        if (VCAST_TI_9_9_index >= VCAST_TI_9_9_last)
          break;
        VCAST_TI_9_9_index++;
      }  
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_9_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
}  
void VCAST_TI_RANGE_DATA_9 ( void ) {
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900006\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,(0 / 2) + (0xffff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,0xffff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_ARRAY\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100008\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,60);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_ARRAY\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,32);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_ARRAY\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100007\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,10);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900001\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(0 / 2) + (0xff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,0xff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900007\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(-32767-1) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,((-32767-1) / 2) + (32767 / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,32767 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900003\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,(0 / 2) + (0xffff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_short (vCAST_OUTPUT_FILE,0xffff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_ARRAY\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100006\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,8);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
}
/*vcast_header_expansion_start:Sys_UDS_LinComp_PDS_uc.c*/
void vCAST_VALUE_USER_CODE_9(int vcast_slot_index ) {
  {
  }
}
void vCAST_EXPECTED_USER_CODE_9(int vcast_slot_index ) {
  {
  }
}
void vCAST_EGLOBALS_USER_CODE_9(int vcast_slot_index ) {
  {
  }
}
void vCAST_STUB_PROCESSING_9(
        int  UnitIndex, 
        int  SubprogramIndex ) {
  vCAST_GLOBAL_STUB_PROCESSING();
  {
  }
}
void vCAST_BEGIN_STUB_PROC_9(
        int  UnitIndex, 
        int  SubprogramIndex ) {
  vCAST_GLOBAL_BEGINNING_OF_STUB_PROCESSING();
  {
  }
}
void VCAST_USER_CODE_UNIT_9( VCAST_USER_CODE_TYPE uct, int vcast_slot_index ) {
  switch( uct ) {
    case VCAST_UCT_VALUE:
      vCAST_VALUE_USER_CODE_9(vcast_slot_index);
      break;
    case VCAST_UCT_EXPECTED:
      vCAST_EXPECTED_USER_CODE_9(vcast_slot_index);
      break;
    case VCAST_UCT_EXPECTED_GLOBALS:
      vCAST_EGLOBALS_USER_CODE_9(vcast_slot_index);
      break;
  }  
}
/*vcast_header_expansion_end*/
void vCAST_COMMON_STUB_PROC_9(
            int unitIndex,
            int subprogramIndex,
            int robjectIndex,
            int readEobjectData )
{
   vCAST_BEGIN_STUB_PROC_9(unitIndex, subprogramIndex);
   if ( robjectIndex )
      vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM( unitIndex, subprogramIndex, robjectIndex );
   if ( readEobjectData )
      vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM( unitIndex, subprogramIndex, 0 );
   vCAST_SET_HISTORY( unitIndex, subprogramIndex );
   vCAST_READ_COMMAND_DATA( vCAST_CURRENT_SLOT, unitIndex, subprogramIndex, vCAST_true, vCAST_false );
   vCAST_READ_COMMAND_DATA_FOR_USER_GLOBALS();
   vCAST_STUB_PROCESSING_9(unitIndex, subprogramIndex);
}
/*vcast_separate_expansion_end*/
