/*vcast_separate_expansion_start:S0000009.c*/
/*vcast_header_expansion_start:vcast_env_defines.h*/
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:EEPROM_driver_prefix.c*/
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:S0000009.h*/
void vectorcast_initialize_io (int inst_status, int inst_fd);
void vectorcast_terminate_io (void);
void vectorcast_write_vcast_end (void);
int  vectorcast_fflush(int fpn);
void vectorcast_fclose(int fpn);
int  vectorcast_feof(int fpn);
int  vectorcast_fopen( char *filename,  char *mode);
char *vectorcast_fgets (char *line, int maxline, int fpn);
int vectorcast_readline(char *vcast_buf, int fpn);
void vectorcast_fprint_char   (int fpn, char vcast_str);
void vectorcast_fprint_char_hex ( int fpn, char vcast_value );
void vectorcast_fprint_char_octl ( int fpn, char vcast_value );
void vectorcast_fprint_string (int fpn,  char *vcast_str);
void vectorcast_fprint_string_with_cr (int fpn,  char *vcast_str);
void vectorcast_print_string ( char *vcast_str);
void vectorcast_fprint_string_with_length(int fpn,  char *vcast_str, int length);
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
void vectorcast_write_to_std_out ( char *s);
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
 char *vcast_get_filename(enum vcast_env_file_kind kind);
void vectorcast_set_index(int index, int fpn);
int vectorcast_get_index(int fpn);
extern int vCAST_ITERATION_COUNTERS [3][9];
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
  typedef unsigned int   size_t;
  typedef signed int    ptrdiff_t;
  typedef unsigned char  wchar_t;
typedef unsigned long clock_t;
typedef unsigned long time_t;
typedef void (*PROC)(void);
  typedef  unsigned char      Byte;
  typedef    signed char      sByte;
  typedef  unsigned int       Word;
  typedef    signed int       sWord;
  typedef  unsigned long      LWord;
  typedef    signed long      sLWord;
typedef  unsigned char      uchar;
typedef  unsigned int       uint;
typedef  unsigned long      ulong;
typedef  unsigned long long ullong;
typedef  signed char        schar;
typedef  signed int         sint;
typedef  signed long        slong;
typedef  signed long long   sllong;
      typedef sWord  enum_t;
typedef int Bool;
typedef  char * ConstString;
typedef  char * LIBDEF_ConstStringPtr;
typedef       char *  LIBDEF_StringPtr;
typedef  void *    ConstMem;
typedef  void *    LIBDEF_ConstMemPtr;
typedef       void *     LIBDEF_MemPtr;
typedef       char  LIBDEF_MemByte;
typedef       LIBDEF_MemByte *     LIBDEF_MemBytePtr;
typedef  LIBDEF_MemByte *     LIBDEF_ConstMemBytePtr;
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
extern size_t wcstombs(LIBDEF_StringPtr mb,  wchar_t *wc, size_t n);
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
extern int      fsetpos (FILE * f,  fpos_t * pos);
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
extern FILE *   freopen ( char * name,  char * mode, FILE * f);
extern int      remove  (LIBDEF_ConstStringPtr name);
extern int      rename  ( char * old_name,  char * new_name);
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
extern size_t   fwrite  ( void * buf, size_t size, size_t n, FILE * f);
extern LIBDEF_StringPtr fgets   (LIBDEF_StringPtr s, int n, FILE * f);
extern int      fputs   (LIBDEF_ConstStringPtr s, FILE * f);
extern int      fscanf  (FILE * f,  char * s, ...);  
extern int      ungetc  (int c, FILE * f);
extern LIBDEF_StringPtr gets(LIBDEF_StringPtr s);
/*vcast_header_collapse_end*/
void VCAST_free (void * vcast_aptr);
void * VCAST_malloc (unsigned int vcast_size);
int VCAST_signed_strlen ( signed char *vcast_str );
void VCAST_signed_strcpy ( signed char *VC_S,  signed char *VC_T );
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
void vCAST_SET_TESTCASE_OPTIONS (  char vcast_options[] );
void vCAST_RUN_DATA_IF ( char *VCAST_PARAM, vCAST_boolean POST_CONSTRUCTOR_USER_CODE);
void vCAST_slice (char vcast_target[],  char vcast_source[], int vcast_first, int vcast_last);
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
void vcGetCommandDetails ( char* vcCommand, int* vcStartOfValue, int* vcNumberOfValues);
void vcResetRangeDataArray(void);
void vCAST_STORE_GLOBAL_ASCII_DATA (void);
void vCAST_CREATE_EVENT_FILE (void);
void vCAST_CREATE_HIST_FILE (void);
void vCAST_OPEN_HIST_FILE (void);
void vCAST_CREATE_INST_FILE (void);
void vCAST_openHarnessFiles (void);
void vCAST_closeHarnessFiles (void);
long VCAST_convert_encoded_field( char *vcast_str);
void vCAST_CREATE_INST_FILE (void);
void VCAST_WRITE_TO_INST_FILE ( char VC_S[]);
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
void vCAST_STORE_ASCII_DATA ( int, int,  char* );
vCAST_boolean vCAST_READ_NEXT_ORDER (void);
vCAST_boolean vCAST_SHOULD_DISPLAY_GLOBALS ( int,  char*);
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
int vcast_get_percent_pos ( char *vcast_command);
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
unsigned  *P_9_1_1;
unsigned  P_9_1_2;
unsigned  P_9_1_3;
unsigned char SBF_9_1 = 0;
unsigned  *P_9_2_1;
unsigned  P_9_2_2;
unsigned  P_9_2_3;
unsigned  *P_9_2_4;
unsigned char  R_9_2;
unsigned char SBF_9_2 = 0;
unsigned long  P_9_3_1;
unsigned  P_9_3_2;
unsigned  P_9_3_3;
unsigned  *P_9_3_4;
unsigned  *P_9_3_5;
unsigned char  R_9_3;
unsigned char SBF_9_3 = 0;
unsigned  *P_9_4_1;
unsigned char  R_9_4;
unsigned char SBF_9_4 = 0;
unsigned  *P_9_5_1;
unsigned  P_9_5_2;
unsigned char  R_9_5;
unsigned char SBF_9_5 = 0;
unsigned  *P_9_6_1;
unsigned char  P_9_6_2;
unsigned char  R_9_6;
unsigned char SBF_9_6 = 0;
unsigned  *P_9_7_1;
unsigned char  *P_9_7_2;
unsigned char  R_9_7;
unsigned char SBF_9_7 = 0;
unsigned char SBF_9_8 = 0;
/*vcast_header_expansion_end*/
/*vcast_header_expansion_start:vcast_stubs_9.c*/
volatile FCLKDIVSTR  _FCLKDIV 
;
volatile FCCOBIXSTR  _FCCOBIX 
;
volatile FSTATSTR  _FSTAT 
;
volatile FCCOB0STR  _FCCOB0 
;
volatile FCCOB1STR  _FCCOB1 
;
volatile FCCOB2STR  _FCCOB2 
;
/*vcast_header_expansion_end*/
void VCAST_DRIVER_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 0:
      vCAST_SET_HISTORY_FLAGS ( 9, 0);
      vCAST_USER_CODE_TIMER_START();
      break;
    case 1: {
      vCAST_SET_HISTORY_FLAGS ( 9, 1 );
      vCAST_USER_CODE_TIMER_START();
      ( BackupSector(
        ( P_9_1_1 ),
        ( P_9_1_2 ),
        ( P_9_1_3 ) ) );
      break; }
    case 2: {
      vCAST_SET_HISTORY_FLAGS ( 9, 2 );
      vCAST_USER_CODE_TIMER_START();
      R_9_2 = 
      ( WriteBlock(
        ( P_9_2_1 ),
        ( P_9_2_2 ),
        ( P_9_2_3 ),
        ( P_9_2_4 ) ) );
      break; }
    case 3: {
      vCAST_SET_HISTORY_FLAGS ( 9, 3 );
      vCAST_USER_CODE_TIMER_START();
      R_9_3 = 
      ( SetupFCCOB(
        ( P_9_3_1 ),
        ( P_9_3_2 ),
        ( P_9_3_3 ),
        ( P_9_3_4 ),
        ( P_9_3_5 ) ) );
      break; }
    case 4: {
      vCAST_SET_HISTORY_FLAGS ( 9, 4 );
      vCAST_USER_CODE_TIMER_START();
      R_9_4 = 
      ( EraseSectorInternal(
        ( P_9_4_1 ) ) );
      break; }
    case 5: {
      vCAST_SET_HISTORY_FLAGS ( 9, 5 );
      vCAST_USER_CODE_TIMER_START();
      R_9_5 = 
      ( WriteWord(
        ( P_9_5_1 ),
        ( P_9_5_2 ) ) );
      break; }
    case 6: {
      vCAST_SET_HISTORY_FLAGS ( 9, 6 );
      vCAST_USER_CODE_TIMER_START();
      R_9_6 = 
      ( EEPROM_SetByte(
        ( P_9_6_1 ),
        ( P_9_6_2 ) ) );
      break; }
    case 7: {
      vCAST_SET_HISTORY_FLAGS ( 9, 7 );
      vCAST_USER_CODE_TIMER_START();
      R_9_7 = 
      ( EEPROM_GetByte(
        ( P_9_7_1 ),
        ( P_9_7_2 ) ) );
      break; }
    case 8: {
      vCAST_SET_HISTORY_FLAGS ( 9, 8 );
      vCAST_USER_CODE_TIMER_START();
      ( EEPROM_Init( ) );
      break; }
    default:
      vectorcast_print_string("ERROR: Internal Tool Error\n");
      break;
  }  
  vCAST_USER_CODE_TIMER_STOP();
}
void VCAST_SBF_9( int VC_SUBPROGRAM ) {
  switch( VC_SUBPROGRAM ) {
    case 1: {
      SBF_9_1 = 0;
      break; }
    case 2: {
      SBF_9_2 = 0;
      break; }
    case 3: {
      SBF_9_3 = 0;
      break; }
    case 4: {
      SBF_9_4 = 0;
      break; }
    case 5: {
      SBF_9_5 = 0;
      break; }
    case 6: {
      SBF_9_6 = 0;
      break; }
    case 7: {
      SBF_9_7 = 0;
      break; }
    case 8: {
      SBF_9_8 = 0;
      break; }
    default:
      break;
  }  
}
/*vcast_header_expansion_start:vcast_ti_decls_9.h*/
void VCAST_TI_9_1 ( volatile FCLKDIVSTR  *vcast_param ) ;
void VCAST_TI_9_12 ( volatile FSTATSTR  *vcast_param ) ;
void VCAST_TI_9_17 ( volatile FCCOB0STR  *vcast_param ) ;
void VCAST_TI_9_20 ( unsigned  *vcast_param ) ;
void VCAST_TI_9_27 ( volatile FCCOB1STR  *vcast_param ) ;
void VCAST_TI_9_36 ( volatile FCCOB2STR  *vcast_param ) ;
void VCAST_TI_9_4 ( unsigned char  *vcast_param ) ;
void VCAST_TI_9_45 ( unsigned  vcast_param[0x2] ) ;
void VCAST_TI_9_46 ( unsigned  **vcast_param ) ;
void VCAST_TI_9_47 ( unsigned long  *vcast_param ) ;
void VCAST_TI_9_48 ( unsigned char  **vcast_param ) ;
void VCAST_TI_9_7 ( volatile FCCOBIXSTR  *vcast_param ) ;
/*vcast_header_expansion_end*/
void VCAST_RUN_DATA_IF_9( int VCAST_SUB_INDEX, int VCAST_PARAM_INDEX ) {
  switch ( VCAST_SUB_INDEX ) {
    case 0:  
      switch( VCAST_PARAM_INDEX ) {
        case 2:  
          VCAST_TI_9_1 ( ((volatile FCLKDIVSTR  *)(&(_FCLKDIV))));
          break;
        case 3:  
          VCAST_TI_9_7 ( ((volatile FCCOBIXSTR  *)(&(_FCCOBIX))));
          break;
        case 4:  
          VCAST_TI_9_12 ( ((volatile FSTATSTR  *)(&(_FSTAT))));
          break;
        case 5:  
          VCAST_TI_9_17 ( ((volatile FCCOB0STR  *)(&(_FCCOB0))));
          break;
        case 6:  
          VCAST_TI_9_27 ( ((volatile FCCOB1STR  *)(&(_FCCOB1))));
          break;
        case 7:  
          VCAST_TI_9_36 ( ((volatile FCCOB2STR  *)(&(_FCCOB2))));
          break;
        case 1:  
          VCAST_TI_9_45 ( BackupArray);
          break;
        default:
          vCAST_TOOL_ERROR = vCAST_true;
          break;
      }  
      break;  
    case 1:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_1_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_1_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_1_3));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_1 );
          break;
      }  
      break;  
    case 2:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_2_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_2_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_2_3));
          break;
        case 4:
          VCAST_TI_9_46 ( &(P_9_2_4));
          break;
        case 5:
          VCAST_TI_9_4 ( &(R_9_2));
          break;
        case 6:
          VCAST_TI_SBF_OBJECT( &SBF_9_2 );
          break;
      }  
      break;  
    case 3:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_47 ( &(P_9_3_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_3_2));
          break;
        case 3:
          VCAST_TI_9_20 ( &(P_9_3_3));
          break;
        case 4:
          VCAST_TI_9_46 ( &(P_9_3_4));
          break;
        case 5:
          VCAST_TI_9_46 ( &(P_9_3_5));
          break;
        case 6:
          VCAST_TI_9_4 ( &(R_9_3));
          break;
        case 7:
          VCAST_TI_SBF_OBJECT( &SBF_9_3 );
          break;
      }  
      break;  
    case 4:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_4_1));
          break;
        case 2:
          VCAST_TI_9_4 ( &(R_9_4));
          break;
        case 3:
          VCAST_TI_SBF_OBJECT( &SBF_9_4 );
          break;
      }  
      break;  
    case 5:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_5_1));
          break;
        case 2:
          VCAST_TI_9_20 ( &(P_9_5_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_5));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_5 );
          break;
      }  
      break;  
    case 6:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_6_1));
          break;
        case 2:
          VCAST_TI_9_4 ( &(P_9_6_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_6));
          break;
        case 4:
          VCAST_TI_SBF_OBJECT( &SBF_9_6 );
          break;
      }  
      break;  
    case 7:  
      switch ( VCAST_PARAM_INDEX ) {
        case 1:
          VCAST_TI_9_46 ( &(P_9_7_1));
          break;
        case 2:
          VCAST_TI_9_48 ( &(P_9_7_2));
          break;
        case 3:
          VCAST_TI_9_4 ( &(R_9_7));
          break;
        case 4:
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
    default:
      vCAST_TOOL_ERROR = vCAST_true;
      break;
  }  
}
void VCAST_TI_9_1 ( volatile FCLKDIVSTR  *vcast_param ) 
{
  {
    int VCAST_TI_9_3_jmpval;
    VCAST_TI_9_3_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_3_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 4: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 5: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 6: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIV5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIV5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 7: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIVLCK;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIVLCK = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 8: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FDIVLD;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FDIVLD = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->MergedBits.grpFDIV;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 6, vCAST_false );
                vcast_param->MergedBits.grpFDIV = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_7 ( volatile FCCOBIXSTR  *vcast_param ) 
{
  {
    int VCAST_TI_9_9_jmpval;
    VCAST_TI_9_9_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_9_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOBIX0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOBIX1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOBIX2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOBIX2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->MergedBits.grpCCOBIX;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 3, vCAST_false );
                vcast_param->MergedBits.grpCCOBIX = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_12 ( volatile FSTATSTR  *vcast_param ) 
{
  {
    int VCAST_TI_9_14_jmpval;
    VCAST_TI_9_14_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_14_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_4 ( &(vcast_param->Byte));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.MGSTAT0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGSTAT0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.MGSTAT1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGSTAT1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.MGBUSY;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.MGBUSY = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 4: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.FPVIOL;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.FPVIOL = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 5: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.ACCERR;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.ACCERR = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              case 6: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Bits.CCIF;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCIF = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->MergedBits.grpMGSTAT;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 2, vCAST_false );
                vcast_param->MergedBits.grpMGSTAT = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_17 ( volatile FCCOB0STR  *vcast_param ) 
{
  {
    int VCAST_TI_9_19_jmpval;
    VCAST_TI_9_19_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_19_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                {
                  int VCAST_TI_9_22_jmpval;
                  VCAST_TI_9_22_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_22_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB0HISTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              case 2: { 
                {
                  int VCAST_TI_9_24_jmpval;
                  VCAST_TI_9_24_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_24_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB0LOSTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB0LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 4: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 5: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 6: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 7: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 8: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 9: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 10: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 11: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 12: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 13: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 14: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 15: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 16: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_27 ( volatile FCCOB1STR  *vcast_param ) 
{
  {
    int VCAST_TI_9_29_jmpval;
    VCAST_TI_9_29_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_29_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                {
                  int VCAST_TI_9_31_jmpval;
                  VCAST_TI_9_31_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_31_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB1HISTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              case 2: { 
                {
                  int VCAST_TI_9_33_jmpval;
                  VCAST_TI_9_33_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_33_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB1LOSTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB1LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 4: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 5: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 6: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 7: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 8: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 9: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 10: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 11: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 12: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 13: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 14: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 15: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 16: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_36 ( volatile FCCOB2STR  *vcast_param ) 
{
  {
    int VCAST_TI_9_38_jmpval;
    VCAST_TI_9_38_jmpval = _setjmp(VCAST_env);
    vcast_is_in_union = vCAST_false;
    if ( VCAST_TI_9_38_jmpval == 0 ) {
      vcast_is_in_union = vCAST_true;
      switch ( vcast_get_param () ) {  
        case 1: { 
          VCAST_TI_9_20 ( &(vcast_param->Word));
          break;  
        }  
        case 2: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                {
                  int VCAST_TI_9_40_jmpval;
                  VCAST_TI_9_40_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_40_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB2HISTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB8;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB8 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB9;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB9 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB10;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB10 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB11;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB11 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB12;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB12 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB13;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB13 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB14;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB14 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB15;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2HISTR.Bits.CCOB15 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              case 2: { 
                {
                  int VCAST_TI_9_42_jmpval;
                  VCAST_TI_9_42_jmpval = _setjmp(VCAST_env);
                  vcast_is_in_union = vCAST_false;
                  if ( VCAST_TI_9_42_jmpval == 0 ) {
                    vcast_is_in_union = vCAST_true;
                    switch ( vcast_get_param () ) {  
                      case 1: { 
                        VCAST_TI_9_4 ( &(vcast_param->Overlap_STR.FCCOB2LOSTR.Byte));
                        break;  
                      }  
                      case 2: { 
                        {
                          switch ( vcast_get_param () ) {  
                            case 1: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB0;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB0 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 2: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB1;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB1 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 3: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB2;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB2 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 4: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB3;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB3 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 5: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB4;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB4 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 6: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB5;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB5 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 7: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB6;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB6 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            case 8: { 
                              long VCAST_TI_9_4_ti_bitfield_placeholder = (long) vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB7;
                              VCAST_TI_BITFIELD ( & VCAST_TI_9_4_ti_bitfield_placeholder, 1, vCAST_false );
                              vcast_param->Overlap_STR.FCCOB2LOSTR.Bits.CCOB7 = ( unsigned char   ) VCAST_TI_9_4_ti_bitfield_placeholder;
                              break;  
                            }  
                            default:
                              vCAST_TOOL_ERROR = vCAST_true;
                          }   
                        }
                        break;  
                      }  
                      default:
                        vCAST_TOOL_ERROR = vCAST_true;
                    }   
                  } else if ( vCAST_COMMAND == vCAST_PRINT )
                    vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
                }
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        case 3: { 
          {
            switch ( vcast_get_param () ) {  
              case 1: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB0;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB0 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 2: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB1;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB1 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 3: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB2;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB2 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 4: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB3;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB3 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 5: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB4;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB4 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 6: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB5;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB5 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 7: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB6;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB6 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 8: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB7;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB7 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 9: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB8;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB8 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 10: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB9;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB9 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 11: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB10;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB10 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 12: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB11;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB11 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 13: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB12;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB12 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 14: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB13;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB13 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 15: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB14;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB14 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              case 16: { 
                long VCAST_TI_9_20_ti_bitfield_placeholder = (long) vcast_param->Bits.CCOB15;
                VCAST_TI_BITFIELD ( & VCAST_TI_9_20_ti_bitfield_placeholder, 1, vCAST_false );
                vcast_param->Bits.CCOB15 = ( unsigned   ) VCAST_TI_9_20_ti_bitfield_placeholder;
                break;  
              }  
              default:
                vCAST_TOOL_ERROR = vCAST_true;
            }   
          }
          break;  
        }  
        default:
          vCAST_TOOL_ERROR = vCAST_true;
      }   
    } else if ( vCAST_COMMAND == vCAST_PRINT )
      vectorcast_fprint_string(vCAST_OUTPUT_FILE,"invalid address\n");
  }
}  
void VCAST_TI_9_45 ( unsigned  vcast_param[0x2] ) 
{
  {
    int VCAST_TI_9_45_array_index = 0;
    int VCAST_TI_9_45_index = 0;
    int VCAST_TI_9_45_first, VCAST_TI_9_45_last;
    int VCAST_TI_9_45_local_field = 0;
    int VCAST_TI_9_45_value_printed = 0;
    vcast_get_range_value (&VCAST_TI_9_45_first, &VCAST_TI_9_45_last);
    VCAST_TI_9_45_local_field = vCAST_DATA_FIELD;
    {
      int VCAST_TI_9_45_upper = 2;
      for (VCAST_TI_9_45_array_index=0; VCAST_TI_9_45_array_index< VCAST_TI_9_45_upper; VCAST_TI_9_45_array_index++){
        if ( (VCAST_TI_9_45_index >= VCAST_TI_9_45_first) && ( VCAST_TI_9_45_index <= VCAST_TI_9_45_last)){
          VCAST_TI_9_20 ( &(vcast_param[VCAST_TI_9_45_index]));
          VCAST_TI_9_45_value_printed = 1;
          vCAST_DATA_FIELD = VCAST_TI_9_45_local_field;
        }  
        if (VCAST_TI_9_45_index >= VCAST_TI_9_45_last)
          break;
        VCAST_TI_9_45_index++;
      }  
      if ((vCAST_COMMAND == vCAST_PRINT)&&(!VCAST_TI_9_45_value_printed))
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"<<past end of array>>\n");
    }
  }
}  
void VCAST_TI_9_46 ( unsigned  **vcast_param ) 
{
  {
    int VCAST_TI_9_46_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_46_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_46_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_46_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_46_array_size*(sizeof(unsigned  )));
          memset((void*)*vcast_param, 0x0, VCAST_TI_9_46_array_size*(sizeof(unsigned  )));
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        VCAST_TI_9_46_index = vcast_get_param();
        VCAST_TI_9_20 ( &((*vcast_param)[VCAST_TI_9_46_index]));
      }
    }
  }
}  
void VCAST_TI_9_20 ( unsigned  *vcast_param ) 
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
void VCAST_TI_9_4 ( unsigned char  *vcast_param ) 
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
void VCAST_TI_9_47 ( unsigned long  *vcast_param ) 
{
  switch (vCAST_COMMAND) {
    case vCAST_PRINT :
      if ( vcast_param == 0)
        vectorcast_fprint_string (vCAST_OUTPUT_FILE,"null\n");
      else {
        vectorcast_fprint_unsigned_long(vCAST_OUTPUT_FILE, *vcast_param);
        vectorcast_fprint_string(vCAST_OUTPUT_FILE, "\n");
      }
      break;
    case vCAST_KEEP_VAL:
      break;  
  case vCAST_SET_VAL :
    *vcast_param = ( unsigned long   ) VCAST_PARAM_AS_LONGEST_UNSIGNED();
    break;
  case vCAST_FIRST_VAL :
    *vcast_param = 0;
    break;
  case vCAST_MID_VAL :
    *vcast_param = (0 / 2) + (0xffffffff / 2);
    break;
  case vCAST_LAST_VAL :
    *vcast_param = 0xffffffff;
    break;
  case vCAST_MIN_MINUS_1_VAL :
    *vcast_param = 0;
    *vcast_param = *vcast_param - 1;
    break;
  case vCAST_MAX_PLUS_1_VAL :
    *vcast_param = 0xffffffff;
    *vcast_param = *vcast_param + 1;
    break;
  case vCAST_ZERO_VAL :
    *vcast_param = 0;
    break;
  default:
    break;
}  
}  
void VCAST_TI_9_48 ( unsigned char  **vcast_param ) 
{
  {
    int VCAST_TI_9_48_index;
    if (((*vcast_param) == 0) && (vCAST_COMMAND != vCAST_ALLOCATE)){
      if ( vCAST_COMMAND == vCAST_PRINT )
        vectorcast_fprint_string(vCAST_OUTPUT_FILE,"null\n");
    } else {
      if (vCAST_COMMAND == vCAST_ALLOCATE && vcast_proc_handles_command(1)) {
        int VCAST_TI_9_48_array_size = (int) VCAST_PARAM_AS_LONGEST_INT();
        if (VCAST_FIND_INDEX() == -1) {
          void **VCAST_TI_9_48_memory_ptr = (void**)vcast_param;
          *VCAST_TI_9_48_memory_ptr = (void*)VCAST_malloc(VCAST_TI_9_48_array_size*(sizeof(unsigned char  )));
          memset((void*)*vcast_param, 0x0, VCAST_TI_9_48_array_size*(sizeof(unsigned char  )));
        }
      } else if (vCAST_VALUE_NUL == vCAST_true && vcast_proc_handles_command(1)) {
        if (VCAST_FIND_INDEX() == -1)
          *vcast_param = 0;
      } else {
        if (VCAST_FIND_INDEX() == -1 )
          VCAST_TI_STRING ( (char**)vcast_param, 0,-1);
        else {
          VCAST_TI_9_48_index = vcast_get_param();
          VCAST_TI_9_4 ( &((*vcast_param)[VCAST_TI_9_48_index]));
        }
      }
    }
  }
}  
void VCAST_TI_RANGE_DATA_9 ( void ) {
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900010\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,(0 / 2) + (0xffff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_integer (vCAST_OUTPUT_FILE,0xffff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_ARRAY\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"100033\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,2);
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"%%\n");
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900017\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,(0 / 2) + (0xffffffff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_unsigned_long (vCAST_OUTPUT_FILE,0xffffffff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE, "NEW_SCALAR\n" );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"900003\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,0 );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,(0 / 2) + (0xff / 2) );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
  vectorcast_fprint_integer (vCAST_OUTPUT_FILE,0xff );
  vectorcast_fprint_string (vCAST_OUTPUT_FILE,"\n" );
}
/*vcast_header_expansion_start:EEPROM_uc.c*/
void vCAST_VALUE_USER_CODE_9 (
         int vcast_slot_index ) {
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.002" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x00100300UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.003" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003FFUL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.004" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003F0UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.008" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x00100300UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.009" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003FFUL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.010" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003F0UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.008" ) == 0 ) ) {
      {
          _FSTAT.Bits.CCIF = ( 1 );
      }
      {
          P_9_7_1 = ( (word *)0x001003F0UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.009" ) == 0 ) ) {
      {
          P_9_7_1 = ( (word *)0x001003F0UL );
      }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.010" ) == 0 ) ) {
      {
          _FSTAT.Bits.CCIF = ( 1 );
      }
      {
          P_9_7_1 = ( (word *)0x001003F1UL );
      }
         }  
}
void vCAST_EXPECTED_USER_CODE_9 (
         int vcast_slot_index ) {
}
void vCAST_EGLOBALS_USER_CODE_9 (
         int vcast_slot_index ) {
}
void vCAST_STUB_PROCESSING_9 (
         int UnitIndex,
         int SubprogramIndex ) {
    vCAST_GLOBAL_STUB_PROCESSING();
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 2 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2105.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  3)) {
          word *temp = P_9_3_5;
*temp = 3;
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.002" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x00100300UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.003" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x001003FFUL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.004" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x001003F0UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x00100300UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.009" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x001003FFUL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.010" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          P_9_6_1 = ( (word *)0x001003F0UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex == -1)) {
          _FSTAT.Bits.CCIF = ( 1 );
        }
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          P_9_7_1 = ( (word *)0x001003F0UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.009" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          P_9_7_1 = ( (word *)0x001003F0UL );
        }
         }  
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.010" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex == -1)) {
          _FSTAT.Bits.CCIF = ( 1 );
        }
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          P_9_7_1 = ( (word *)0x001003F1UL );
        }
         }  
}
void vCAST_BEGIN_STUB_PROC_9 (
         int UnitIndex,
         int SubprogramIndex ) {
    vCAST_GLOBAL_BEGINNING_OF_STUB_PROCESSING();
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
