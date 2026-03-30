
#define MAX_FILE_LENGTH 13
#ifndef VCAST_INPUT_DATA_ARRAY_ATTRIBUTE
#define VCAST_INPUT_DATA_ARRAY_ATTRIBUTE
#endif
#ifndef VCAST_STDIN_DATA_SIZE_T 
#define VCAST_STDIN_DATA_SIZE_T unsigned short
#endif 
struct FileData {
	char    name[MAX_FILE_LENGTH]; 
	VCAST_STDIN_DATA_SIZE_T   offset; 
	VCAST_STDIN_DATA_SIZE_T   len; 
}; 
#ifdef __cplusplus
extern "C"
#endif
const struct FileData inputDataArrayTOC[] = {
{{'T','E','S','T','O','R','D','R','.','D','A','T',0},0,61,},
{{'H','A','R','N','O','P','T','S','.','D','A','T',0},61,92,},
{{'C','-','0','0','0','1','9','3','.','H','A','R',0},153,269,},
{{'E','0','0','0','0','0','0','1','.','D','A','T',0},422,234}};
#ifdef __cplusplus
extern "C"
#endif
#ifdef __cplusplus
extern "C"
#endif
const int NumInputFiles = 4;
#ifdef __cplusplus
extern "C"
#endif
const char* const VCAST_INPUT_DATA_ARRAY_ATTRIBUTE inputDataArray = 
"*FILE:TESTORDR.DAT\012"
"1000\012"
"SwUFn_2107.007\012"
"C-000193.HAR\012"
"1\012"
" \012"
"TRUE\012"
"*FILE:HARNOPTS.DAT\012"
"0.0.1.4%0\012"
"0.0.11.4%3\012"
"0.0.2.4%0\012"
"0.0.3.4%0\012"
"0.0.19.4%0\012"
"0.0.12.4%0\012"
"0.0.0.5%0\012"
"*FILE:C-000193.HAR\012"
"0.0.14.4%1\012"
"0.9.1.4%<<STUB>>\012"
"0.9.2.6%<<STUB>>\012"
"0.9.3.7%<<STUB>>\012"
"0.9.4.3%<<STUB>>\012"
"0.9.6.4%<<STUB>>\012"
"0.9.7.4%<<STUB>>\012"
"0.9.8.1%<<STUB>>\012"
"0.0.0.0%5\012"
"0.0.0.3%9\012"
"0.9.0.4.1%312\012"
"0.9.0.4.2.6%99\012"
"0.9.0.4.3.1%99\012"
"+.9.5.1%1\012"
"0.9.5.1.0%5001472305\012"
"0.9.5.2%70065\012"
"0.0.14.4%1\012"
"*FILE:E0000001.DAT\012"
"1.9.1.4%0\012"
"1.9.2.6%0\012"
"1.9.3.7%0\012"
"1.9.4.3%0\012"
"1.9.5.1.0%0\012"
"1.9.5.2%0\012"
"1.9.5.3%0\012"
"1.9.6.4%0\012"
"1.9.7.4%0\012"
"1.9.8.1%0\012"
"1.9.0.3.1%0\012"
"1.9.0.4.1%0\012"
"1.9.0.4.2.6%0\012"
"1.9.0.4.3.1%0\012"
"1.9.0.5.2.1.1%0\012"
"1.9.0.5.2.2.1%0\012"
"1.9.0.6.1%0\012"
"1.9.0.7.1%0\012"
"*END\012"
;
