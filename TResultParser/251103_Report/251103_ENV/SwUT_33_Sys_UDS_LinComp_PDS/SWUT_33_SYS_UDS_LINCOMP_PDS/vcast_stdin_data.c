
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
{{'C','-','0','0','0','0','9','6','.','H','A','R',0},153,84,},
{{'E','0','0','0','0','0','0','1','.','D','A','T',0},237,46}};
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
"SwUFN_3342.001\012"
"C-000096.HAR\012"
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
"*FILE:C-000096.HAR\012"
"0.0.0.0%13\012"
"0.0.0.3%9\012"
"0.0.14.4%1\012"
"0.9.0.13%1\012"
"0.9.13.1%0\012"
"0.0.14.4%1\012"
"*FILE:E0000001.DAT\012"
"1.9.13.1%0\012"
"1.9.0.13%0\012"
"*END\012"
;
