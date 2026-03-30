# 1 "vcast_preprocess.15656.1010.c"
# 1 "vcast_preprocess.15656.1008.c"

typedef int VECTORCAST_MARKER__UNIT_PREFIX_START;

typedef int VECTORCAST_MARKER__UNIT_PREFIX_END;
# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/EEPROM.c"

























































 





          



          


 

 
 
 
 
 
 
 
 

# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/EEPROM.h"

























































 





          



          




 

 

# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"


















































 






          



          




 


 
# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"















































 







          



          

 
 
   





 
# 77 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

# 85 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

 
typedef unsigned char       VUINT8;
typedef signed char         VINT8;
typedef unsigned short int  VUINT16;
typedef signed short int    VINT16;
typedef unsigned long int   VUINT32;

 

typedef signed char int8_t;


typedef signed int   int16_t;


typedef signed long int    int32_t;



typedef unsigned char       uint8_t;


typedef unsigned int  uint16_t;


typedef unsigned long int   uint32_t;


typedef float TPE_Float;


typedef char char_t;


 
typedef unsigned char bool;
typedef unsigned char byte;
typedef unsigned int word;
typedef unsigned long dword;
typedef unsigned long dlong[2];
typedef void (*tIntFunc)(void);
typedef uint8_t TPE_ErrCode;

 
 
 
 
# 147 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

 
 
 





 



 
# 173 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

 
# 184 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

 
 
 





 



 
# 210 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

 
# 221 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"
 






 

# 246 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"
 
# 254 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Types.h"

typedef struct {                 
  word width;                    
  word height;                   
   byte *pixmap;            
  word size;                     
   char_t *name;            
} TIMAGE;
typedef TIMAGE* PIMAGE ;         

 
 
typedef union {
   word w;
   struct {
     byte high,low;
   } b;
} TWREG;
 




 







 
# 72 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"
# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Error.h"













































 






          



          




 

# 93 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Error.h"




 







 
# 73 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"
# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Const.h"














































 






          



          




 




 
# 75 "C:/workspace/NE1AW_PORTING/Generated_Code/PE_Const.h"




 







 
# 74 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"
# 1 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
















































 







          



          



 

 
 


 
 
 



/*vcast_scrub*/

 
 
 
 
 

 
# 210 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

 
# 336 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

 

 
typedef union {
  dword Dword;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte ID0         :8;                                        
      } Bits;
    } PARTID0STR;


     

    


    

     
    union {
      byte Byte;
      struct {
        byte ID1         :8;                                        
      } Bits;
    } PARTID1STR;


    


    

     
    union {
      byte Byte;
      struct {
        byte ID2         :8;                                        
      } Bits;
    } PARTID2STR;


    


    

     
    union {
      byte Byte;
      struct {
        byte ID3         :8;                                        
      } Bits;
    } PARTID3STR;


    


    
  } Overlap_STR;

} PARTIDSTR;
extern volatile PARTIDSTR _PARTID @0x00000000;



 
typedef union {
  word Word;
  struct {
    word             :1; 
    word IVB_ADDR    :15;                                       
  } Bits;
} IVBRSTR;
extern volatile IVBRSTR _IVBR @0x00000010;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte INT_CFADDR_grp :4;                                       
    byte             :1; 
  } Bits;
} INT_CFADDRSTR;
extern volatile INT_CFADDRSTR _INT_CFADDR @0x00000017;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA0STR;
extern volatile INT_CFDATA0STR _INT_CFDATA0 @0x00000018;


 






 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA1STR;
extern volatile INT_CFDATA1STR _INT_CFDATA1 @0x00000019;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA2STR;
extern volatile INT_CFDATA2STR _INT_CFDATA2 @0x0000001A;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA3STR;
extern volatile INT_CFDATA3STR _INT_CFDATA3 @0x0000001B;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA4STR;
extern volatile INT_CFDATA4STR _INT_CFDATA4 @0x0000001C;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA5STR;
extern volatile INT_CFDATA5STR _INT_CFDATA5 @0x0000001D;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA6STR;
extern volatile INT_CFDATA6STR _INT_CFDATA6 @0x0000001E;







 
typedef union {
  byte Byte;
  struct {
    byte PRIOLVL     :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} INT_CFDATA7STR;
extern volatile INT_CFDATA7STR _INT_CFDATA7 @0x0000001F;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte MODC        :1;                                        
  } Bits;
} MODESTR;
extern volatile MODESTR _MODE @0x00000070;






 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte TGT         :4;                                        
        byte ITR         :4;                                        
      } Bits;
    } MMCECHSTR;



    




    

     
    union {
      byte Byte;
      struct {
        byte ERR         :4;                                        
        byte ACC         :4;                                        
      } Bits;
    } MMCECLSTR;



    




    
  } Overlap_STR;

  struct {
    word ERR         :4;                                        
    word ACC         :4;                                        
    word TGT         :4;                                        
    word ITR         :4;                                        
  } Bits;
} MMCECSTR;
extern volatile MMCECSTR _MMCEC @0x00000080;






# 690 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte CPUU        :1;                                        
      } Bits;
    } MMCCCRHSTR;


    

    

     
    union {
      byte Byte;
      struct {
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte CPUI        :1;                                        
        byte             :1; 
        byte CPUX        :1;                                        
        byte             :1; 
      } Bits;
    } MMCCCRLSTR;



    


    
  } Overlap_STR;

  struct {
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word CPUI        :1;                                        
    word             :1; 
    word CPUX        :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word CPUU        :1;                                        
  } Bits;
} MMCCCRSTR;
extern volatile MMCCCRSTR _MMCCCR @0x00000082;










 
typedef union {
  byte Byte;
  struct {
    byte CPUPC       :8;                                        
  } Bits;
} MMCPCHSTR;
extern volatile MMCPCHSTR _MMCPCH @0x00000085;







 
typedef union {
  byte Byte;
  struct {
    byte CPUPC       :8;                                        
  } Bits;
} MMCPCMSTR;
extern volatile MMCPCMSTR _MMCPCM @0x00000086;







 
typedef union {
  byte Byte;
  struct {
    byte CPUPC       :8;                                        
  } Bits;
} MMCPCLSTR;
extern volatile MMCPCLSTR _MMCPCL @0x00000087;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte EEVE1       :1;                                        
    byte             :1; 
    byte BRKCPU      :1;                                        
    byte BDMBP       :1;                                        
    byte             :1; 
    byte TRIG        :1;                                        
    byte ARM         :1;                                        
  } Bits;
} DBGC1STR;
extern volatile DBGC1STR _DBGC1 @0x00000100;
# 836 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte ABCM        :2;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} DBGC2STR;
extern volatile DBGC2STR _DBGC2 @0x00000101;







 
typedef union {
  byte Byte;
  struct {
    byte C0SC        :2;                                        
    byte C1SC        :2;                                        
    byte             :1; 
    byte             :1; 
    byte C3SC        :2;                                        
  } Bits;
} DBGSCR1STR;
extern volatile DBGSCR1STR _DBGSCR1 @0x00000107;





# 888 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0SC        :2;                                        
    byte C1SC        :2;                                        
    byte             :1; 
    byte             :1; 
    byte C3SC        :2;                                        
  } Bits;
} DBGSCR2STR;
extern volatile DBGSCR2STR _DBGSCR2 @0x00000108;





# 913 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0SC        :2;                                        
    byte C1SC        :2;                                        
    byte             :1; 
    byte             :1; 
    byte C3SC        :2;                                        
  } Bits;
} DBGSCR3STR;
extern volatile DBGSCR3STR _DBGSCR3 @0x00000109;





# 938 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ME0         :1;                                        
    byte ME1         :1;                                        
    byte             :1; 
    byte ME3         :1;                                        
    byte EEVF        :1;                                        
    byte             :1; 
    byte TRIGF       :1;                                        
    byte             :1; 
  } Bits;
  struct {
    byte grpME   :2;
    byte         :1;
    byte grpME_3 :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} DBGEFRSTR;
extern volatile DBGEFRSTR _DBGEFR @0x0000010A;
# 971 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 979 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SSF0        :1;                                        
    byte SSF1        :1;                                        
    byte SSF2        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpSSF  :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} DBGSRSTR;
extern volatile DBGSRSTR _DBGSR @0x0000010B;













 
typedef union {
  byte Byte;
  struct {
    byte COMPE       :1;                                        
    byte             :1; 
    byte RWE         :1;                                        
    byte RW          :1;                                        
    byte             :1; 
    byte INST        :1;                                        
    byte NDB         :1;                                        
    byte             :1; 
  } Bits;
} DBGACTLSTR;
extern volatile DBGACTLSTR _DBGACTL @0x00000110;
# 1038 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte DBGAA       :8;                                        
  } Bits;
} DBGAAHSTR;
extern volatile DBGAAHSTR _DBGAAH @0x00000115;







 
typedef union {
  byte Byte;
  struct {
    byte DBGAA       :8;                                        
  } Bits;
} DBGAAMSTR;
extern volatile DBGAAMSTR _DBGAAM @0x00000116;







 
typedef union {
  byte Byte;
  struct {
    byte DBGAA       :8;                                        
  } Bits;
} DBGAALSTR;
extern volatile DBGAALSTR _DBGAAL @0x00000117;







 
typedef union {
  byte Byte;
  struct {
    byte BIT24       :1;                                        
    byte BIT25       :1;                                        
    byte BIT26       :1;                                        
    byte BIT27       :1;                                        
    byte BIT28       :1;                                        
    byte BIT29       :1;                                        
    byte BIT30       :1;                                        
    byte BIT31       :1;                                        
  } Bits;
} DBGAD0STR;
extern volatile DBGAD0STR _DBGAD0 @0x00000118;
# 1115 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 1126 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT16       :1;                                        
    byte BIT17       :1;                                        
    byte BIT18       :1;                                        
    byte BIT19       :1;                                        
    byte BIT20       :1;                                        
    byte BIT21       :1;                                        
    byte BIT22       :1;                                        
    byte BIT23       :1;                                        
  } Bits;
} DBGAD1STR;
extern volatile DBGAD1STR _DBGAD1 @0x00000119;
# 1152 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1161 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT8        :1;                                        
    byte BIT9        :1;                                        
    byte BIT10       :1;                                        
    byte BIT11       :1;                                        
    byte BIT12       :1;                                        
    byte BIT13       :1;                                        
    byte BIT14       :1;                                        
    byte BIT15       :1;                                        
  } Bits;
} DBGAD2STR;
extern volatile DBGAD2STR _DBGAD2 @0x0000011A;
# 1187 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1196 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} DBGAD3STR;
extern volatile DBGAD3STR _DBGAD3 @0x0000011B;
# 1222 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1231 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT24       :1;                                        
    byte BIT25       :1;                                        
    byte BIT26       :1;                                        
    byte BIT27       :1;                                        
    byte BIT28       :1;                                        
    byte BIT29       :1;                                        
    byte BIT30       :1;                                        
    byte BIT31       :1;                                        
  } Bits;
} DBGADM0STR;
extern volatile DBGADM0STR _DBGADM0 @0x0000011C;
# 1257 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 1268 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT16       :1;                                        
    byte BIT17       :1;                                        
    byte BIT18       :1;                                        
    byte BIT19       :1;                                        
    byte BIT20       :1;                                        
    byte BIT21       :1;                                        
    byte BIT22       :1;                                        
    byte BIT23       :1;                                        
  } Bits;
} DBGADM1STR;
extern volatile DBGADM1STR _DBGADM1 @0x0000011D;
# 1294 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1303 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT8        :1;                                        
    byte BIT9        :1;                                        
    byte BIT10       :1;                                        
    byte BIT11       :1;                                        
    byte BIT12       :1;                                        
    byte BIT13       :1;                                        
    byte BIT14       :1;                                        
    byte BIT15       :1;                                        
  } Bits;
} DBGADM2STR;
extern volatile DBGADM2STR _DBGADM2 @0x0000011E;
# 1329 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1338 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} DBGADM3STR;
extern volatile DBGADM3STR _DBGADM3 @0x0000011F;
# 1364 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1373 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte COMPE       :1;                                        
    byte             :1; 
    byte RWE         :1;                                        
    byte RW          :1;                                        
    byte             :1; 
    byte INST        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} DBGBCTLSTR;
extern volatile DBGBCTLSTR _DBGBCTL @0x00000120;












 
typedef union {
  byte Byte;
  struct {
    byte DBGBA       :8;                                        
  } Bits;
} DBGBAHSTR;
extern volatile DBGBAHSTR _DBGBAH @0x00000125;







 
typedef union {
  byte Byte;
  struct {
    byte DBGBA       :8;                                        
  } Bits;
} DBGBAMSTR;
extern volatile DBGBAMSTR _DBGBAM @0x00000126;







 
typedef union {
  byte Byte;
  struct {
    byte DBGBA       :8;                                        
  } Bits;
} DBGBALSTR;
extern volatile DBGBALSTR _DBGBAL @0x00000127;







 
typedef union {
  byte Byte;
  struct {
    byte COMPE       :1;                                        
    byte             :1; 
    byte RWE         :1;                                        
    byte RW          :1;                                        
    byte             :1; 
    byte INST        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} DBGDCTLSTR;
extern volatile DBGDCTLSTR _DBGDCTL @0x00000140;












 
typedef union {
  byte Byte;
  struct {
    byte DBGDA       :8;                                        
  } Bits;
} DBGDAHSTR;
extern volatile DBGDAHSTR _DBGDAH @0x00000145;







 
typedef union {
  byte Byte;
  struct {
    byte DBGDA       :8;                                        
  } Bits;
} DBGDAMSTR;
extern volatile DBGDAMSTR _DBGDAM @0x00000146;







 
typedef union {
  byte Byte;
  struct {
    byte DBGDA       :8;                                        
  } Bits;
} DBGDALSTR;
extern volatile DBGDALSTR _DBGDAL @0x00000147;







 
typedef union {
  byte Byte;
  struct {
    byte S0L0RR      :3;                                        
    byte SCI1RR      :1;                                        
    byte IIC0RR      :1;                                        
    byte CAN0RR      :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} MODRR0STR;
extern volatile MODRR0STR _MODRR0 @0x00000200;





 









 
typedef union {
  byte Byte;
  struct {
    byte PWM0RR      :1;                                        
    byte             :1; 
    byte PWM2RR      :1;                                        
    byte             :1; 
    byte PWM4RR      :1;                                        
    byte PWM5RR      :1;                                        
    byte PWM6RR      :1;                                        
    byte PWM7RR      :1;                                        
  } Bits;
} MODRR1STR;
extern volatile MODRR1STR _MODRR1 @0x00000201;
# 1569 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1576 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte T0C2RR      :1;                                        
    byte T0C3RR      :1;                                        
    byte T0C4RR      :1;                                        
    byte T0C5RR      :1;                                        
    byte T1C0RR      :1;                                        
    byte T1C1RR      :1;                                        
  } Bits;
} MODRR2STR;
extern volatile MODRR2STR _MODRR2 @0x00000202;
# 1600 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 1607 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte TRIG0RR     :2;                                        
    byte TRIG0NEG    :1;                                        
    byte TRIG0RR2    :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} MODRR3STR;
extern volatile MODRR3STR _MODRR3 @0x00000203;











 
typedef union {
  byte Byte;
  struct {
    byte T0IC3RR     :2;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} MODRR4STR;
extern volatile MODRR4STR _MODRR4 @0x00000204;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte NECLK       :1;                                        
  } Bits;
} ECLKCTLSTR;
extern volatile ECLKCTLSTR _ECLKCTL @0x00000208;






 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte IRQEN       :1;                                        
    byte IRQE        :1;                                        
  } Bits;
} IRQCRSTR;
extern volatile IRQCRSTR _IRQCR @0x00000209;








 
typedef union {
  byte Byte;
  struct {
    byte PTE0        :1;                                        
    byte PTE1        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTE  :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTESTR;
extern volatile PTESTR _PTE @0x00000260;











 
typedef union {
  byte Byte;
  struct {
    byte PTIE0       :1;                                        
    byte PTIE1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTIE :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTIESTR;
extern volatile PTIESTR _PTIE @0x00000262;











 
typedef union {
  byte Byte;
  struct {
    byte DDRE0       :1;                                        
    byte DDRE1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpDDRE :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} DDRESTR;
extern volatile DDRESTR _DDRE @0x00000264;











 
typedef union {
  byte Byte;
  struct {
    byte PERE0       :1;                                        
    byte PERE1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPERE :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PERESTR;
extern volatile PERESTR _PERE @0x00000266;











 
typedef union {
  byte Byte;
  struct {
    byte PPSE0       :1;                                        
    byte PPSE1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPPSE :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PPSESTR;
extern volatile PPSESTR _PPSE @0x00000268;











 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PTADH0      :1;                                        
        byte PTADH1      :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPTADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PTADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PTADL0      :1;                                        
        byte PTADL1      :1;                                        
        byte PTADL2      :1;                                        
        byte PTADL3      :1;                                        
        byte PTADL4      :1;                                        
        byte PTADL5      :1;                                        
        byte PTADL6      :1;                                        
        byte PTADL7      :1;                                        
      } Bits;
    } PTADLSTR;
# 1936 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 1945 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PTADL0      :1;                                        
    word PTADL1      :1;                                        
    word PTADL2      :1;                                        
    word PTADL3      :1;                                        
    word PTADL4      :1;                                        
    word PTADL5      :1;                                        
    word PTADL6      :1;                                        
    word PTADL7      :1;                                        
    word PTADH0      :1;                                        
    word PTADH1      :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPTADL :8;
    word grpPTADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PTADSTR;
extern volatile PTADSTR _PTAD @0x00000280;
# 1991 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2006 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PTIADH0     :1;                                        
        byte PTIADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPTIADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PTIADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PTIADL0     :1;                                        
        byte PTIADL1     :1;                                        
        byte PTIADL2     :1;                                        
        byte PTIADL3     :1;                                        
        byte PTIADL4     :1;                                        
        byte PTIADL5     :1;                                        
        byte PTIADL6     :1;                                        
        byte PTIADL7     :1;                                        
      } Bits;
    } PTIADLSTR;
# 2070 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2079 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PTIADL0     :1;                                        
    word PTIADL1     :1;                                        
    word PTIADL2     :1;                                        
    word PTIADL3     :1;                                        
    word PTIADL4     :1;                                        
    word PTIADL5     :1;                                        
    word PTIADL6     :1;                                        
    word PTIADL7     :1;                                        
    word PTIADH0     :1;                                        
    word PTIADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPTIADL :8;
    word grpPTIADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PTIADSTR;
extern volatile PTIADSTR _PTIAD @0x00000282;
# 2125 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2140 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte DDRADH0     :1;                                        
        byte DDRADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpDDRADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } DDRADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte DDRADL0     :1;                                        
        byte DDRADL1     :1;                                        
        byte DDRADL2     :1;                                        
        byte DDRADL3     :1;                                        
        byte DDRADL4     :1;                                        
        byte DDRADL5     :1;                                        
        byte DDRADL6     :1;                                        
        byte DDRADL7     :1;                                        
      } Bits;
    } DDRADLSTR;
# 2204 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2213 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word DDRADL0     :1;                                        
    word DDRADL1     :1;                                        
    word DDRADL2     :1;                                        
    word DDRADL3     :1;                                        
    word DDRADL4     :1;                                        
    word DDRADL5     :1;                                        
    word DDRADL6     :1;                                        
    word DDRADL7     :1;                                        
    word DDRADH0     :1;                                        
    word DDRADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpDDRADL :8;
    word grpDDRADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} DDRADSTR;
extern volatile DDRADSTR _DDRAD @0x00000284;
# 2259 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2274 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PERADH0     :1;                                        
        byte PERADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPERADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PERADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PERADL0     :1;                                        
        byte PERADL1     :1;                                        
        byte PERADL2     :1;                                        
        byte PERADL3     :1;                                        
        byte PERADL4     :1;                                        
        byte PERADL5     :1;                                        
        byte PERADL6     :1;                                        
        byte PERADL7     :1;                                        
      } Bits;
    } PERADLSTR;
# 2338 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2347 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PERADL0     :1;                                        
    word PERADL1     :1;                                        
    word PERADL2     :1;                                        
    word PERADL3     :1;                                        
    word PERADL4     :1;                                        
    word PERADL5     :1;                                        
    word PERADL6     :1;                                        
    word PERADL7     :1;                                        
    word PERADH0     :1;                                        
    word PERADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPERADL :8;
    word grpPERADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PERADSTR;
extern volatile PERADSTR _PERAD @0x00000286;
# 2393 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2408 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PPSADH0     :1;                                        
        byte PPSADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPPSADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PPSADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PPSADL0     :1;                                        
        byte PPSADL1     :1;                                        
        byte PPSADL2     :1;                                        
        byte PPSADL3     :1;                                        
        byte PPSADL4     :1;                                        
        byte PPSADL5     :1;                                        
        byte PPSADL6     :1;                                        
        byte PPSADL7     :1;                                        
      } Bits;
    } PPSADLSTR;
# 2472 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2481 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PPSADL0     :1;                                        
    word PPSADL1     :1;                                        
    word PPSADL2     :1;                                        
    word PPSADL3     :1;                                        
    word PPSADL4     :1;                                        
    word PPSADL5     :1;                                        
    word PPSADL6     :1;                                        
    word PPSADL7     :1;                                        
    word PPSADH0     :1;                                        
    word PPSADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPPSADL :8;
    word grpPPSADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PPSADSTR;
extern volatile PPSADSTR _PPSAD @0x00000288;
# 2527 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2542 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PIEADH0     :1;                                        
        byte PIEADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPIEADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PIEADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PIEADL0     :1;                                        
        byte PIEADL1     :1;                                        
        byte PIEADL2     :1;                                        
        byte PIEADL3     :1;                                        
        byte PIEADL4     :1;                                        
        byte PIEADL5     :1;                                        
        byte PIEADL6     :1;                                        
        byte PIEADL7     :1;                                        
      } Bits;
    } PIEADLSTR;
# 2606 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2615 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PIEADL0     :1;                                        
    word PIEADL1     :1;                                        
    word PIEADL2     :1;                                        
    word PIEADL3     :1;                                        
    word PIEADL4     :1;                                        
    word PIEADL5     :1;                                        
    word PIEADL6     :1;                                        
    word PIEADL7     :1;                                        
    word PIEADH0     :1;                                        
    word PIEADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPIEADL :8;
    word grpPIEADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PIEADSTR;
extern volatile PIEADSTR _PIEAD @0x0000028C;
# 2661 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2676 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte PIFADH0     :1;                                        
        byte PIFADH1     :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpPIFADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } PIFADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte PIFADL0     :1;                                        
        byte PIFADL1     :1;                                        
        byte PIFADL2     :1;                                        
        byte PIFADL3     :1;                                        
        byte PIFADL4     :1;                                        
        byte PIFADL5     :1;                                        
        byte PIFADL6     :1;                                        
        byte PIFADL7     :1;                                        
      } Bits;
    } PIFADLSTR;
# 2740 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2749 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word PIFADL0     :1;                                        
    word PIFADL1     :1;                                        
    word PIFADL2     :1;                                        
    word PIFADL3     :1;                                        
    word PIFADL4     :1;                                        
    word PIFADL5     :1;                                        
    word PIFADL6     :1;                                        
    word PIFADL7     :1;                                        
    word PIFADH0     :1;                                        
    word PIFADH1     :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpPIFADL :8;
    word grpPIFADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} PIFADSTR;
extern volatile PIFADSTR _PIFAD @0x0000028E;
# 2795 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2810 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte DIENADH0    :1;                                        
        byte DIENADH1    :1;                                        
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
      } Bits;
      struct {
        byte grpDIENADH :2;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
        byte     :1;
      } MergedBits;
    } DIENADHSTR;




    




    

     
    union {
      byte Byte;
      struct {
        byte DIENADL0    :1;                                        
        byte DIENADL1    :1;                                        
        byte DIENADL2    :1;                                        
        byte DIENADL3    :1;                                        
        byte DIENADL4    :1;                                        
        byte DIENADL5    :1;                                        
        byte DIENADL6    :1;                                        
        byte DIENADL7    :1;                                        
      } Bits;
    } DIENADLSTR;
# 2874 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 2883 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word DIENADL0    :1;                                        
    word DIENADL1    :1;                                        
    word DIENADL2    :1;                                        
    word DIENADL3    :1;                                        
    word DIENADL4    :1;                                        
    word DIENADL5    :1;                                        
    word DIENADL6    :1;                                        
    word DIENADL7    :1;                                        
    word DIENADH0    :1;                                        
    word DIENADH1    :1;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
  } Bits;
  struct {
    word grpDIENADL :8;
    word grpDIENADH :2;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
    word         :1;
  } MergedBits;
} DIENADSTR;
extern volatile DIENADSTR _DIENAD @0x00000298;
# 2929 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2944 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTT0        :1;                                        
    byte PTT1        :1;                                        
    byte PTT2        :1;                                        
    byte PTT3        :1;                                        
    byte PTT4        :1;                                        
    byte PTT5        :1;                                        
    byte PTT6        :1;                                        
    byte PTT7        :1;                                        
  } Bits;
} PTTSTR;
extern volatile PTTSTR _PTT @0x000002C0;
# 2970 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 2979 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTIT0       :1;                                        
    byte PTIT1       :1;                                        
    byte PTIT2       :1;                                        
    byte PTIT3       :1;                                        
    byte PTIT4       :1;                                        
    byte PTIT5       :1;                                        
    byte PTIT6       :1;                                        
    byte PTIT7       :1;                                        
  } Bits;
} PTITSTR;
extern volatile PTITSTR _PTIT @0x000002C1;
# 3005 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3014 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DDRT0       :1;                                        
    byte DDRT1       :1;                                        
    byte DDRT2       :1;                                        
    byte DDRT3       :1;                                        
    byte DDRT4       :1;                                        
    byte DDRT5       :1;                                        
    byte DDRT6       :1;                                        
    byte DDRT7       :1;                                        
  } Bits;
} DDRTSTR;
extern volatile DDRTSTR _DDRT @0x000002C2;
# 3040 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3049 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PERT0       :1;                                        
    byte PERT1       :1;                                        
    byte PERT2       :1;                                        
    byte PERT3       :1;                                        
    byte PERT4       :1;                                        
    byte PERT5       :1;                                        
    byte PERT6       :1;                                        
    byte PERT7       :1;                                        
  } Bits;
} PERTSTR;
extern volatile PERTSTR _PERT @0x000002C3;
# 3075 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3084 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PPST0       :1;                                        
    byte PPST1       :1;                                        
    byte PPST2       :1;                                        
    byte PPST3       :1;                                        
    byte PPST4       :1;                                        
    byte PPST5       :1;                                        
    byte PPST6       :1;                                        
    byte PPST7       :1;                                        
  } Bits;
} PPSTSTR;
extern volatile PPSTSTR _PPST @0x000002C4;
# 3110 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3119 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTS0        :1;                                        
    byte PTS1        :1;                                        
    byte PTS2        :1;                                        
    byte PTS3        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTS  :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTSSTR;
extern volatile PTSSTR _PTS @0x000002D0;
# 3149 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3156 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTIS0       :1;                                        
    byte PTIS1       :1;                                        
    byte PTIS2       :1;                                        
    byte PTIS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTIS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTISSTR;
extern volatile PTISSTR _PTIS @0x000002D1;
# 3186 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3193 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DDRS0       :1;                                        
    byte DDRS1       :1;                                        
    byte DDRS2       :1;                                        
    byte DDRS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpDDRS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} DDRSSTR;
extern volatile DDRSSTR _DDRS @0x000002D2;
# 3223 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3230 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PERS0       :1;                                        
    byte PERS1       :1;                                        
    byte PERS2       :1;                                        
    byte PERS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPERS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PERSSTR;
extern volatile PERSSTR _PERS @0x000002D3;
# 3260 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3267 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PPSS0       :1;                                        
    byte PPSS1       :1;                                        
    byte PPSS2       :1;                                        
    byte PPSS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPPSS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PPSSSTR;
extern volatile PPSSSTR _PPSS @0x000002D4;
# 3297 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3304 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PIES0       :1;                                        
    byte PIES1       :1;                                        
    byte PIES2       :1;                                        
    byte PIES3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPIES :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PIESSTR;
extern volatile PIESSTR _PIES @0x000002D6;
# 3334 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3341 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PIFS0       :1;                                        
    byte PIFS1       :1;                                        
    byte PIFS2       :1;                                        
    byte PIFS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPIFS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PIFSSTR;
extern volatile PIFSSTR _PIFS @0x000002D7;
# 3371 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3378 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte WOMS0       :1;                                        
    byte WOMS1       :1;                                        
    byte WOMS2       :1;                                        
    byte WOMS3       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpWOMS :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} WOMSSTR;
extern volatile WOMSSTR _WOMS @0x000002DF;
# 3408 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3415 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTP0        :1;                                        
    byte PTP1        :1;                                        
    byte PTP2        :1;                                        
    byte PTP3        :1;                                        
    byte PTP4        :1;                                        
    byte PTP5        :1;                                        
    byte PTP6        :1;                                        
    byte PTP7        :1;                                        
  } Bits;
} PTPSTR;
extern volatile PTPSTR _PTP @0x000002F0;
# 3441 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3450 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTIP0       :1;                                        
    byte PTIP1       :1;                                        
    byte PTIP2       :1;                                        
    byte PTIP3       :1;                                        
    byte PTIP4       :1;                                        
    byte PTIP5       :1;                                        
    byte PTIP6       :1;                                        
    byte PTIP7       :1;                                        
  } Bits;
} PTIPSTR;
extern volatile PTIPSTR _PTIP @0x000002F1;
# 3476 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3485 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DDRP0       :1;                                        
    byte DDRP1       :1;                                        
    byte DDRP2       :1;                                        
    byte DDRP3       :1;                                        
    byte DDRP4       :1;                                        
    byte DDRP5       :1;                                        
    byte DDRP6       :1;                                        
    byte DDRP7       :1;                                        
  } Bits;
} DDRPSTR;
extern volatile DDRPSTR _DDRP @0x000002F2;
# 3511 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3520 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PERP0       :1;                                        
    byte PERP1       :1;                                        
    byte PERP2       :1;                                        
    byte PERP3       :1;                                        
    byte PERP4       :1;                                        
    byte PERP5       :1;                                        
    byte PERP6       :1;                                        
    byte PERP7       :1;                                        
  } Bits;
} PERPSTR;
extern volatile PERPSTR _PERP @0x000002F3;
# 3546 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3555 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PPSP0       :1;                                        
    byte PPSP1       :1;                                        
    byte PPSP2       :1;                                        
    byte PPSP3       :1;                                        
    byte PPSP4       :1;                                        
    byte PPSP5       :1;                                        
    byte PPSP6       :1;                                        
    byte PPSP7       :1;                                        
  } Bits;
} PPSPSTR;
extern volatile PPSPSTR _PPSP @0x000002F4;
# 3581 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3590 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PIEP0       :1;                                        
    byte PIEP1       :1;                                        
    byte PIEP2       :1;                                        
    byte PIEP3       :1;                                        
    byte PIEP4       :1;                                        
    byte PIEP5       :1;                                        
    byte PIEP6       :1;                                        
    byte PIEP7       :1;                                        
  } Bits;
} PIEPSTR;
extern volatile PIEPSTR _PIEP @0x000002F6;
# 3616 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3625 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PIFP0       :1;                                        
    byte PIFP1       :1;                                        
    byte PIFP2       :1;                                        
    byte PIFP3       :1;                                        
    byte PIFP4       :1;                                        
    byte PIFP5       :1;                                        
    byte PIFP6       :1;                                        
    byte PIFP7       :1;                                        
  } Bits;
} PIFPSTR;
extern volatile PIFPSTR _PIFP @0x000002F7;
# 3651 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 3660 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte OCPEP1      :1;                                        
    byte             :1; 
    byte OCPEP3      :1;                                        
    byte             :1; 
    byte OCPEP5      :1;                                        
    byte             :1; 
    byte OCPEP7      :1;                                        
  } Bits;
} OCPEPSTR;
extern volatile OCPEPSTR _OCPEP @0x000002F9;












 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte OCIEP1      :1;                                        
    byte             :1; 
    byte OCIEP3      :1;                                        
    byte             :1; 
    byte OCIEP5      :1;                                        
    byte             :1; 
    byte OCIEP7      :1;                                        
  } Bits;
} OCIEPSTR;
extern volatile OCIEPSTR _OCIEP @0x000002FA;












 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte OCIFP1      :1;                                        
    byte             :1; 
    byte OCIFP3      :1;                                        
    byte             :1; 
    byte OCIFP5      :1;                                        
    byte             :1; 
    byte OCIFP7      :1;                                        
  } Bits;
} OCIFPSTR;
extern volatile OCIFPSTR _OCIFP @0x000002FB;












 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte RDRP1       :1;                                        
    byte             :1; 
    byte RDRP3       :1;                                        
    byte             :1; 
    byte RDRP5       :1;                                        
    byte             :1; 
    byte RDRP7       :1;                                        
  } Bits;
} RDRPSTR;
extern volatile RDRPSTR _RDRP @0x000002FD;












 
typedef union {
  byte Byte;
  struct {
    byte PTJ0        :1;                                        
    byte PTJ1        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTJ  :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTJSTR;
extern volatile PTJSTR _PTJ @0x00000310;











 
typedef union {
  byte Byte;
  struct {
    byte PTIJ0       :1;                                        
    byte PTIJ1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPTIJ :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PTIJSTR;
extern volatile PTIJSTR _PTIJ @0x00000311;











 
typedef union {
  byte Byte;
  struct {
    byte DDRJ0       :1;                                        
    byte DDRJ1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpDDRJ :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} DDRJSTR;
extern volatile DDRJSTR _DDRJ @0x00000312;











 
typedef union {
  byte Byte;
  struct {
    byte PERJ0       :1;                                        
    byte PERJ1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPERJ :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PERJSTR;
extern volatile PERJSTR _PERJ @0x00000313;











 
typedef union {
  byte Byte;
  struct {
    byte PPSJ0       :1;                                        
    byte PPSJ1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPPSJ :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} PPSJSTR;
extern volatile PPSJSTR _PPSJ @0x00000314;











 
typedef union {
  byte Byte;
  struct {
    byte WOMJ0       :1;                                        
    byte WOMJ1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpWOMJ :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} WOMJSTR;
extern volatile WOMJSTR _WOMJ @0x0000031F;











 
typedef union {
  byte Byte;
  struct {
    byte PTIL0       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PTILSTR;
extern volatile PTILSTR _PTIL @0x00000331;






 
typedef union {
  byte Byte;
  struct {
    byte PPSL0       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PPSLSTR;
extern volatile PPSLSTR _PPSL @0x00000334;






 
typedef union {
  byte Byte;
  struct {
    byte PIEL0       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PIELSTR;
extern volatile PIELSTR _PIEL @0x00000336;






 
typedef union {
  byte Byte;
  struct {
    byte PIFL0       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PIFLSTR;
extern volatile PIFLSTR _PIFL @0x00000337;






 
typedef union {
  byte Byte;
  struct {
    byte DIENL0      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} DIENLSTR;
extern volatile DIENLSTR _DIENL @0x0000033C;






 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte PTAENL      :1;                                        
    byte PTADIRL     :1;                                        
    byte PTABYPL     :1;                                        
    byte PTPSL       :1;                                        
    byte PTTEL       :1;                                        
  } Bits;
} PTALSTR;
extern volatile PTALSTR _PTAL @0x0000033D;
# 4106 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte PIRL0       :2; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PIRLSTR;
extern volatile PIRLSTR _PIRL @0x0000033E;







 
typedef union {
  byte Byte;
  struct {
    byte FDIV0       :1;                                        
    byte FDIV1       :1;                                        
    byte FDIV2       :1;                                        
    byte FDIV3       :1;                                        
    byte FDIV4       :1;                                        
    byte FDIV5       :1;                                        
    byte FDIVLCK     :1;                                        
    byte FDIVLD      :1;                                        
  } Bits;
  struct {
    byte grpFDIV :6;
    byte         :1;
    byte         :1;
  } MergedBits;
} FCLKDIVSTR;
extern volatile FCLKDIVSTR _FCLKDIV @0x00000380;
# 4165 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4176 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SEC0        :1;                                        
    byte SEC1        :1;                                        
    byte RNV2        :1;                                        
    byte RNV3        :1;                                        
    byte RNV4        :1;                                        
    byte RNV5        :1;                                        
    byte KEYEN0      :1;                                        
    byte KEYEN1      :1;                                        
  } Bits;
  struct {
    byte grpSEC  :2;
    byte grpRNV_2 :4;
    byte grpKEYEN :2;
  } MergedBits;
} FSECSTR;
extern volatile FSECSTR _FSEC @0x00000381;
# 4211 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4226 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte CCOBIX0     :1;                                        
    byte CCOBIX1     :1;                                        
    byte CCOBIX2     :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpCCOBIX :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} FCCOBIXSTR;
extern volatile FCCOBIXSTR _FCCOBIX @0x00000382;













 
typedef union {
  byte Byte;
  struct {
    byte WSTATACK    :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte FPOVRD      :1;                                        
  } Bits;
} FPSTATSTR;
extern volatile FPSTATSTR _FPSTAT @0x00000383;








 
typedef union {
  byte Byte;
  struct {
    byte FSFD        :1;                                        
    byte FDFD        :1;                                        
    byte WSTAT       :2;                                        
    byte IGNSF       :1;                                        
    byte ERSAREQ     :1;                                        
    byte             :1; 
    byte CCIE        :1;                                        
  } Bits;
} FCNFGSTR;
extern volatile FCNFGSTR _FCNFG @0x00000384;
# 4308 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4316 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SFDIE       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} FERCNFGSTR;
extern volatile FERCNFGSTR _FERCNFG @0x00000385;






 
typedef union {
  byte Byte;
  struct {
    byte MGSTAT0     :1;                                        
    byte MGSTAT1     :1;                                        
    byte             :1; 
    byte MGBUSY      :1;                                        
    byte FPVIOL      :1;                                        
    byte ACCERR      :1;                                        
    byte             :1; 
    byte CCIF        :1;                                        
  } Bits;
  struct {
    byte grpMGSTAT :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} FSTATSTR;
extern volatile FSTATSTR _FSTAT @0x00000386;
# 4371 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4380 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SFDIF       :1;                                        
    byte DFDF        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} FERSTATSTR;
extern volatile FERSTATSTR _FERSTAT @0x00000387;








 
typedef union {
  byte Byte;
  struct {
    byte FPLS0       :1;                                        
    byte FPLS1       :1;                                        
    byte FPLDIS      :1;                                        
    byte FPHS0       :1;                                        
    byte FPHS1       :1;                                        
    byte FPHDIS      :1;                                        
    byte RNV6        :1;                                        
    byte FPOPEN      :1;                                        
  } Bits;
  struct {
    byte grpFPLS :2;
    byte         :1;
    byte grpFPHS :2;
    byte         :1;
    byte grpRNV_6 :1;
    byte         :1;
  } MergedBits;
} FPROTSTR;
extern volatile FPROTSTR _FPROT @0x00000388;
# 4439 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4452 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DPS0        :1;                                        
    byte DPS1        :1;                                        
    byte DPS2        :1;                                        
    byte DPS3        :1;                                        
    byte DPS4        :1;                                        
    byte DPS5        :1;                                        
    byte DPS6        :1;                                        
    byte DPOPEN      :1;                                        
  } Bits;
  struct {
    byte grpDPS  :7;
    byte         :1;
  } MergedBits;
} DFPROTSTR;
extern volatile DFPROTSTR _DFPROT @0x00000389;
# 4483 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4494 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte NV0         :1;                                        
    byte NV1         :1;                                        
    byte NV2         :1;                                        
    byte NV3         :1;                                        
    byte NV4         :1;                                        
    byte NV5         :1;                                        
    byte NV6         :1;                                        
    byte NV7         :1;                                        
  } Bits;
} FOPTSTR;
extern volatile FOPTSTR _FOPT @0x0000038A;
# 4520 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4529 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB0HISTR;
# 4559 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4568 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB0LOSTR;
# 4593 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4602 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB0STR;
extern volatile FCCOB0STR _FCCOB0 @0x0000038C;
# 4642 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 4661 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB1HISTR;
# 4691 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4700 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB1LOSTR;
# 4725 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4734 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB1STR;
extern volatile FCCOB1STR _FCCOB1 @0x0000038E;
# 4774 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4791 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB2HISTR;
# 4821 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4830 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB2LOSTR;
# 4855 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4864 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB2STR;
extern volatile FCCOB2STR _FCCOB2 @0x00000390;
# 4904 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 4921 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB3HISTR;
# 4951 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4960 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB3LOSTR;
# 4985 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 4994 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB3STR;
extern volatile FCCOB3STR _FCCOB3 @0x00000392;
# 5034 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5051 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB4HISTR;
# 5081 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 5090 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB4LOSTR;
# 5115 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 5124 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB4STR;
extern volatile FCCOB4STR _FCCOB4 @0x00000394;
# 5164 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5181 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CCOB8       :1;                                        
        byte CCOB9       :1;                                        
        byte CCOB10      :1;                                        
        byte CCOB11      :1;                                        
        byte CCOB12      :1;                                        
        byte CCOB13      :1;                                        
        byte CCOB14      :1;                                        
        byte CCOB15      :1;                                        
      } Bits;
    } FCCOB5HISTR;
# 5211 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 5220 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte CCOB0       :1;                                        
        byte CCOB1       :1;                                        
        byte CCOB2       :1;                                        
        byte CCOB3       :1;                                        
        byte CCOB4       :1;                                        
        byte CCOB5       :1;                                        
        byte CCOB6       :1;                                        
        byte CCOB7       :1;                                        
      } Bits;
    } FCCOB5LOSTR;
# 5245 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 5254 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word CCOB0       :1;                                        
    word CCOB1       :1;                                        
    word CCOB2       :1;                                        
    word CCOB3       :1;                                        
    word CCOB4       :1;                                        
    word CCOB5       :1;                                        
    word CCOB6       :1;                                        
    word CCOB7       :1;                                        
    word CCOB8       :1;                                        
    word CCOB9       :1;                                        
    word CCOB10      :1;                                        
    word CCOB11      :1;                                        
    word CCOB12      :1;                                        
    word CCOB13      :1;                                        
    word CCOB14      :1;                                        
    word CCOB15      :1;                                        
  } Bits;
} FCCOB5STR;
extern volatile FCCOB5STR _FCCOB5 @0x00000396;
# 5294 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5311 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RDY         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} ECCSTATSTR;
extern volatile ECCSTATSTR _ECCSTAT @0x000003C0;






 
typedef union {
  byte Byte;
  struct {
    byte SBEEIE      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} ECCIESTR;
extern volatile ECCIESTR _ECCIE @0x000003C1;






 
typedef union {
  byte Byte;
  struct {
    byte SBEEIF      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} ECCIFSTR;
extern volatile ECCIFSTR _ECCIF @0x000003C2;






 
typedef union {
  byte Byte;
  struct {
    byte DPTR        :8;                                        
  } Bits;
} ECCDPTRHSTR;
extern volatile ECCDPTRHSTR _ECCDPTRH @0x000003C7;







 
typedef union {
  byte Byte;
  struct {
    byte DPTR        :8;                                        
  } Bits;
} ECCDPTRMSTR;
extern volatile ECCDPTRMSTR _ECCDPTRM @0x000003C8;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte DPTR        :7;                                        
  } Bits;
} ECCDPTRLSTR;
extern volatile ECCDPTRLSTR _ECCDPTRL @0x000003C9;







 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte DDATA       :8;                                        
      } Bits;
    } ECCDDHSTR;


    


    

     
    union {
      byte Byte;
      struct {
        byte DDATA       :8;                                        
      } Bits;
    } ECCDDLSTR;


    


    
  } Overlap_STR;

  struct {
    word DDATA       :16;                                       
  } Bits;
} ECCDDSTR;
extern volatile ECCDDSTR _ECCDD @0x000003CC;







 
typedef union {
  byte Byte;
  struct {
    byte DECC        :6;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} ECCDESTR;
extern volatile ECCDESTR _ECCDE @0x000003CE;







 
typedef union {
  byte Byte;
  struct {
    byte ECCDR       :1;                                        
    byte ECCDW       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte ECCDRR      :1;                                        
  } Bits;
} ECCDCMDSTR;
extern volatile ECCDCMDSTR _ECCDCMD @0x000003CF;










 
typedef union {
  byte Byte;
  struct {
    byte IOS0        :1;                                        
    byte IOS1        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpIOS  :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1TIOSSTR;
extern volatile TIM1TIOSSTR _TIM1TIOS @0x00000400;











 
typedef union {
  byte Byte;
  struct {
    byte FOC0        :1;                                        
    byte FOC1        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpFOC  :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1CFORCSTR;
extern volatile TIM1CFORCSTR _TIM1CFORC @0x00000401;











 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM1TCNTHiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM1TCNTLoSTR;
    
  } Overlap_STR;

} TIM1TCNTSTR;
extern volatile TIM1TCNTSTR _TIM1TCNT @0x00000404;



 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte PRNT        :1;                                        
    byte TFFCA       :1;                                        
    byte TSFRZ       :1;                                        
    byte TSWAI       :1;                                        
    byte TEN         :1;                                        
  } Bits;
} TIM1TSCR1STR;
extern volatile TIM1TSCR1STR _TIM1TSCR1 @0x00000406;
# 5636 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte TOV0        :1;                                        
    byte TOV1        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpTOV  :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1TTOVSTR;
extern volatile TIM1TTOVSTR _TIM1TTOV @0x00000407;











 
typedef union {
  byte Byte;
  struct {
    byte OL0         :1;                                        
    byte OM0         :1;                                        
    byte OL1         :1;                                        
    byte OM1         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM1TCTL2STR;
extern volatile TIM1TCTL2STR _TIM1TCTL2 @0x00000409;












 
typedef union {
  byte Byte;
  struct {
    byte EDG0A       :1;                                        
    byte EDG0B       :1;                                        
    byte EDG1A       :1;                                        
    byte EDG1B       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpEDG0x :2;
    byte grpEDG1x :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1TCTL4STR;
extern volatile TIM1TCTL4STR _TIM1TCTL4 @0x0000040B;
# 5736 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5745 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0I         :1;                                        
    byte C1I         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM1TIESTR;
extern volatile TIM1TIESTR _TIM1TIE @0x0000040C;








 
typedef union {
  byte Byte;
  struct {
    byte PR0         :1;                                        
    byte PR1         :1;                                        
    byte PR2         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte TOI         :1;                                        
  } Bits;
  struct {
    byte grpPR   :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1TSCR2STR;
extern volatile TIM1TSCR2STR _TIM1TSCR2 @0x0000040D;
# 5799 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5806 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0F         :1;                                        
    byte C1F         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM1TFLG1STR;
extern volatile TIM1TFLG1STR _TIM1TFLG1 @0x0000040E;








 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte TOF         :1;                                        
  } Bits;
} TIM1TFLG2STR;
extern volatile TIM1TFLG2STR _TIM1TFLG2 @0x0000040F;






 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM1TC0HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM1TC0LoSTR;
    
  } Overlap_STR;

} TIM1TC0STR;
extern volatile TIM1TC0STR _TIM1TC0 @0x00000410;

 



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM1TC1HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM1TC1LoSTR;
    
  } Overlap_STR;

} TIM1TC1STR;
extern volatile TIM1TC1STR _TIM1TC1 @0x00000412;



 
typedef union {
  byte Byte;
  struct {
    byte OCPD0       :1;                                        
    byte OCPD1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpOCPD :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM1OCPDSTR;
extern volatile TIM1OCPDSTR _TIM1OCPD @0x0000042C;











 
typedef union {
  byte Byte;
  struct {
    byte PTPS0       :1;                                        
    byte PTPS1       :1;                                        
    byte PTPS2       :1;                                        
    byte PTPS3       :1;                                        
    byte PTPS4       :1;                                        
    byte PTPS5       :1;                                        
    byte PTPS6       :1;                                        
    byte PTPS7       :1;                                        
  } Bits;
} TIM1PTPSRSTR;
extern volatile TIM1PTPSRSTR _TIM1PTPSR @0x0000042E;
# 5983 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 5992 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PWME0       :1;                                        
    byte PWME1       :1;                                        
    byte PWME2       :1;                                        
    byte PWME3       :1;                                        
    byte PWME4       :1;                                        
    byte PWME5       :1;                                        
    byte PWME6       :1;                                        
    byte PWME7       :1;                                        
  } Bits;
} PWM0ESTR;
extern volatile PWM0ESTR _PWM0E @0x00000480;
# 6018 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6027 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PPOL0       :1;                                        
    byte PPOL1       :1;                                        
    byte PPOL2       :1;                                        
    byte PPOL3       :1;                                        
    byte PPOL4       :1;                                        
    byte PPOL5       :1;                                        
    byte PPOL6       :1;                                        
    byte PPOL7       :1;                                        
  } Bits;
} PWM0POLSTR;
extern volatile PWM0POLSTR _PWM0POL @0x00000481;
# 6053 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6062 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCLK0       :1;                                        
    byte PCLK1       :1;                                        
    byte PCLK2       :1;                                        
    byte PCLK3       :1;                                        
    byte PCLK4       :1;                                        
    byte PCLK5       :1;                                        
    byte PCLK6       :1;                                        
    byte PCLK7       :1;                                        
  } Bits;
} PWM0CLKSTR;
extern volatile PWM0CLKSTR _PWM0CLK @0x00000482;
# 6088 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6097 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCKA0       :1;                                        
    byte PCKA1       :1;                                        
    byte PCKA2       :1;                                        
    byte             :1; 
    byte PCKB0       :1;                                        
    byte PCKB1       :1;                                        
    byte PCKB2       :1;                                        
    byte             :1; 
  } Bits;
  struct {
    byte grpPCKA :3;
    byte         :1;
    byte grpPCKB :3;
    byte         :1;
  } MergedBits;
} PWM0PRCLKSTR;
extern volatile PWM0PRCLKSTR _PWM0PRCLK @0x00000483;
# 6129 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6140 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte CAE0        :1;                                        
    byte CAE1        :1;                                        
    byte CAE2        :1;                                        
    byte CAE3        :1;                                        
    byte CAE4        :1;                                        
    byte CAE5        :1;                                        
    byte CAE6        :1;                                        
    byte CAE7        :1;                                        
  } Bits;
} PWM0CAESTR;
extern volatile PWM0CAESTR _PWM0CAE @0x00000484;
# 6166 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6175 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte PFRZ        :1;                                        
    byte PSWAI       :1;                                        
    byte CON01       :1;                                        
    byte CON23       :1;                                        
    byte CON45       :1;                                        
    byte CON67       :1;                                        
  } Bits;
} PWM0CTLSTR;
extern volatile PWM0CTLSTR _PWM0CTL @0x00000485;
# 6199 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6206 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCLKAB0     :1;                                        
    byte PCLKAB1     :1;                                        
    byte PCLKAB2     :1;                                        
    byte PCLKAB3     :1;                                        
    byte PCLKAB4     :1;                                        
    byte PCLKAB5     :1;                                        
    byte PCLKAB6     :1;                                        
    byte PCLKAB7     :1;                                        
  } Bits;
} PWM0CLKABSTR;
extern volatile PWM0CLKABSTR _PWM0CLKAB @0x00000486;
# 6232 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6241 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} PWM0SCLASTR;
extern volatile PWM0SCLASTR _PWM0SCLA @0x00000488;
# 6267 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6276 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} PWM0SCLBSTR;
extern volatile PWM0SCLBSTR _PWM0SCLB @0x00000489;
# 6302 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6311 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0CNT0STR;

     

    

     
    union {
      byte Byte;
    } PWM0CNT1STR;

    
  } Overlap_STR;

} PWM0CNT01STR;
extern volatile PWM0CNT01STR _PWM0CNT01 @0x0000048C;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0CNT2STR;

    

     
    union {
      byte Byte;
    } PWM0CNT3STR;

    
  } Overlap_STR;

} PWM0CNT23STR;
extern volatile PWM0CNT23STR _PWM0CNT23 @0x0000048E;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0CNT4STR;

    

     
    union {
      byte Byte;
    } PWM0CNT5STR;

    
  } Overlap_STR;

} PWM0CNT45STR;
extern volatile PWM0CNT45STR _PWM0CNT45 @0x00000490;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0CNT6STR;

    

     
    union {
      byte Byte;
    } PWM0CNT7STR;

    
  } Overlap_STR;

} PWM0CNT67STR;
extern volatile PWM0CNT67STR _PWM0CNT67 @0x00000492;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0PER0STR;

     

    

     
    union {
      byte Byte;
    } PWM0PER1STR;

    
  } Overlap_STR;

} PWM0PER01STR;
extern volatile PWM0PER01STR _PWM0PER01 @0x00000494;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0PER2STR;

    

     
    union {
      byte Byte;
    } PWM0PER3STR;

    
  } Overlap_STR;

} PWM0PER23STR;
extern volatile PWM0PER23STR _PWM0PER23 @0x00000496;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0PER4STR;

    

     
    union {
      byte Byte;
    } PWM0PER5STR;

    
  } Overlap_STR;

} PWM0PER45STR;
extern volatile PWM0PER45STR _PWM0PER45 @0x00000498;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0PER6STR;

    

     
    union {
      byte Byte;
    } PWM0PER7STR;

    
  } Overlap_STR;

} PWM0PER67STR;
extern volatile PWM0PER67STR _PWM0PER67 @0x0000049A;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0DTY0STR;

     

    

     
    union {
      byte Byte;
    } PWM0DTY1STR;

    
  } Overlap_STR;

} PWM0DTY01STR;
extern volatile PWM0DTY01STR _PWM0DTY01 @0x0000049C;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0DTY2STR;

    

     
    union {
      byte Byte;
    } PWM0DTY3STR;

    
  } Overlap_STR;

} PWM0DTY23STR;
extern volatile PWM0DTY23STR _PWM0DTY23 @0x0000049E;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0DTY4STR;

    

     
    union {
      byte Byte;
    } PWM0DTY5STR;

    
  } Overlap_STR;

} PWM0DTY45STR;
extern volatile PWM0DTY45STR _PWM0DTY45 @0x000004A0;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM0DTY6STR;

    

     
    union {
      byte Byte;
    } PWM0DTY7STR;

    
  } Overlap_STR;

} PWM0DTY67STR;
extern volatile PWM0DTY67STR _PWM0DTY67 @0x000004A2;



 
typedef union {
  byte Byte;
  struct {
    byte PWME0       :1;                                        
    byte PWME1       :1;                                        
    byte PWME2       :1;                                        
    byte PWME3       :1;                                        
    byte PWME4       :1;                                        
    byte PWME5       :1;                                        
    byte PWME6       :1;                                        
    byte PWME7       :1;                                        
  } Bits;
} PWM1ESTR;
extern volatile PWM1ESTR _PWM1E @0x00000500;
# 6643 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6652 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PPOL0       :1;                                        
    byte PPOL1       :1;                                        
    byte PPOL2       :1;                                        
    byte PPOL3       :1;                                        
    byte PPOL4       :1;                                        
    byte PPOL5       :1;                                        
    byte PPOL6       :1;                                        
    byte PPOL7       :1;                                        
  } Bits;
} PWM1POLSTR;
extern volatile PWM1POLSTR _PWM1POL @0x00000501;
# 6678 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6687 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCLK0       :1;                                        
    byte PCLK1       :1;                                        
    byte PCLK2       :1;                                        
    byte PCLK3       :1;                                        
    byte PCLK4       :1;                                        
    byte PCLK5       :1;                                        
    byte PCLK6       :1;                                        
    byte PCLK7       :1;                                        
  } Bits;
} PWM1CLKSTR;
extern volatile PWM1CLKSTR _PWM1CLK @0x00000502;
# 6713 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6722 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCKA0       :1;                                        
    byte PCKA1       :1;                                        
    byte PCKA2       :1;                                        
    byte             :1; 
    byte PCKB0       :1;                                        
    byte PCKB1       :1;                                        
    byte PCKB2       :1;                                        
    byte             :1; 
  } Bits;
  struct {
    byte grpPCKA :3;
    byte         :1;
    byte grpPCKB :3;
    byte         :1;
  } MergedBits;
} PWM1PRCLKSTR;
extern volatile PWM1PRCLKSTR _PWM1PRCLK @0x00000503;
# 6754 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6765 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte CAE0        :1;                                        
    byte CAE1        :1;                                        
    byte CAE2        :1;                                        
    byte CAE3        :1;                                        
    byte CAE4        :1;                                        
    byte CAE5        :1;                                        
    byte CAE6        :1;                                        
    byte CAE7        :1;                                        
  } Bits;
} PWM1CAESTR;
extern volatile PWM1CAESTR _PWM1CAE @0x00000504;
# 6791 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6800 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte PFRZ        :1;                                        
    byte PSWAI       :1;                                        
    byte CON01       :1;                                        
    byte CON23       :1;                                        
    byte CON45       :1;                                        
    byte CON67       :1;                                        
  } Bits;
} PWM1CTLSTR;
extern volatile PWM1CTLSTR _PWM1CTL @0x00000505;
# 6824 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6831 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PCLKAB0     :1;                                        
    byte PCLKAB1     :1;                                        
    byte PCLKAB2     :1;                                        
    byte PCLKAB3     :1;                                        
    byte PCLKAB4     :1;                                        
    byte PCLKAB5     :1;                                        
    byte PCLKAB6     :1;                                        
    byte PCLKAB7     :1;                                        
  } Bits;
} PWM1CLKABSTR;
extern volatile PWM1CLKABSTR _PWM1CLKAB @0x00000506;
# 6857 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6866 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} PWM1SCLASTR;
extern volatile PWM1SCLASTR _PWM1SCLA @0x00000508;
# 6892 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6901 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} PWM1SCLBSTR;
extern volatile PWM1SCLBSTR _PWM1SCLB @0x00000509;
# 6927 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 6936 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1CNT0STR;

     

    

     
    union {
      byte Byte;
    } PWM1CNT1STR;

    
  } Overlap_STR;

} PWM1CNT01STR;
extern volatile PWM1CNT01STR _PWM1CNT01 @0x0000050C;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1CNT2STR;

    

     
    union {
      byte Byte;
    } PWM1CNT3STR;

    
  } Overlap_STR;

} PWM1CNT23STR;
extern volatile PWM1CNT23STR _PWM1CNT23 @0x0000050E;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1CNT4STR;

    

     
    union {
      byte Byte;
    } PWM1CNT5STR;

    
  } Overlap_STR;

} PWM1CNT45STR;
extern volatile PWM1CNT45STR _PWM1CNT45 @0x00000510;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1CNT6STR;

    

     
    union {
      byte Byte;
    } PWM1CNT7STR;

    
  } Overlap_STR;

} PWM1CNT67STR;
extern volatile PWM1CNT67STR _PWM1CNT67 @0x00000512;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1PER0STR;

     

    

     
    union {
      byte Byte;
    } PWM1PER1STR;

    
  } Overlap_STR;

} PWM1PER01STR;
extern volatile PWM1PER01STR _PWM1PER01 @0x00000514;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1PER2STR;

    

     
    union {
      byte Byte;
    } PWM1PER3STR;

    
  } Overlap_STR;

} PWM1PER23STR;
extern volatile PWM1PER23STR _PWM1PER23 @0x00000516;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1PER4STR;

    

     
    union {
      byte Byte;
    } PWM1PER5STR;

    
  } Overlap_STR;

} PWM1PER45STR;
extern volatile PWM1PER45STR _PWM1PER45 @0x00000518;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1PER6STR;

    

     
    union {
      byte Byte;
    } PWM1PER7STR;

    
  } Overlap_STR;

} PWM1PER67STR;
extern volatile PWM1PER67STR _PWM1PER67 @0x0000051A;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1DTY0STR;

     

    

     
    union {
      byte Byte;
    } PWM1DTY1STR;

    
  } Overlap_STR;

} PWM1DTY01STR;
extern volatile PWM1DTY01STR _PWM1DTY01 @0x0000051C;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1DTY2STR;

    

     
    union {
      byte Byte;
    } PWM1DTY3STR;

    
  } Overlap_STR;

} PWM1DTY23STR;
extern volatile PWM1DTY23STR _PWM1DTY23 @0x0000051E;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1DTY4STR;

    

     
    union {
      byte Byte;
    } PWM1DTY5STR;

    
  } Overlap_STR;

} PWM1DTY45STR;
extern volatile PWM1DTY45STR _PWM1DTY45 @0x00000520;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
    } PWM1DTY6STR;

    

     
    union {
      byte Byte;
    } PWM1DTY7STR;

    
  } Overlap_STR;

} PWM1DTY67STR;
extern volatile PWM1DTY67STR _PWM1DTY67 @0x00000522;



 
typedef union {
  byte Byte;
  struct {
    byte IOS0        :1;                                        
    byte IOS1        :1;                                        
    byte IOS2        :1;                                        
    byte IOS3        :1;                                        
    byte IOS4        :1;                                        
    byte IOS5        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpIOS  :6;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0TIOSSTR;
extern volatile TIM0TIOSSTR _TIM0TIOS @0x000005C0;
# 7272 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7281 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte FOC0        :1;                                        
    byte FOC1        :1;                                        
    byte FOC2        :1;                                        
    byte FOC3        :1;                                        
    byte FOC4        :1;                                        
    byte FOC5        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpFOC  :6;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0CFORCSTR;
extern volatile TIM0CFORCSTR _TIM0CFORC @0x000005C1;
# 7311 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7320 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TCNTHiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TCNTLoSTR;
    
  } Overlap_STR;

} TIM0TCNTSTR;
extern volatile TIM0TCNTSTR _TIM0TCNT @0x000005C4;



 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte PRNT        :1;                                        
    byte TFFCA       :1;                                        
    byte TSFRZ       :1;                                        
    byte TSWAI       :1;                                        
    byte TEN         :1;                                        
  } Bits;
} TIM0TSCR1STR;
extern volatile TIM0TSCR1STR _TIM0TSCR1 @0x000005C6;
# 7378 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte TOV0        :1;                                        
    byte TOV1        :1;                                        
    byte TOV2        :1;                                        
    byte TOV3        :1;                                        
    byte TOV4        :1;                                        
    byte TOV5        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpTOV  :6;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0TTOVSTR;
extern volatile TIM0TTOVSTR _TIM0TTOV @0x000005C7;
# 7414 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7423 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte OL4         :1;                                        
    byte OM4         :1;                                        
    byte OL5         :1;                                        
    byte OM5         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM0TCTL1STR;
extern volatile TIM0TCTL1STR _TIM0TCTL1 @0x000005C8;












 
typedef union {
  byte Byte;
  struct {
    byte OL0         :1;                                        
    byte OM0         :1;                                        
    byte OL1         :1;                                        
    byte OM1         :1;                                        
    byte OL2         :1;                                        
    byte OM2         :1;                                        
    byte OL3         :1;                                        
    byte OM3         :1;                                        
  } Bits;
} TIM0TCTL2STR;
extern volatile TIM0TCTL2STR _TIM0TCTL2 @0x000005C9;
# 7476 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7485 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte EDG4A       :1;                                        
    byte EDG4B       :1;                                        
    byte EDG5A       :1;                                        
    byte EDG5B       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpEDG4x :2;
    byte grpEDG5x :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0TCTL3STR;
extern volatile TIM0TCTL3STR _TIM0TCTL3 @0x000005CA;
# 7517 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7526 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte EDG0A       :1;                                        
    byte EDG0B       :1;                                        
    byte EDG1A       :1;                                        
    byte EDG1B       :1;                                        
    byte EDG2A       :1;                                        
    byte EDG2B       :1;                                        
    byte EDG3A       :1;                                        
    byte EDG3B       :1;                                        
  } Bits;
  struct {
    byte grpEDG0x :2;
    byte grpEDG1x :2;
    byte grpEDG2x :2;
    byte grpEDG3x :2;
  } MergedBits;
} TIM0TCTL4STR;
extern volatile TIM0TCTL4STR _TIM0TCTL4 @0x000005CB;
# 7562 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7579 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0I         :1;                                        
    byte C1I         :1;                                        
    byte C2I         :1;                                        
    byte C3I         :1;                                        
    byte C4I         :1;                                        
    byte C5I         :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM0TIESTR;
extern volatile TIM0TIESTR _TIM0TIE @0x000005CC;
# 7603 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7610 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PR0         :1;                                        
    byte PR1         :1;                                        
    byte PR2         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte TOI         :1;                                        
  } Bits;
  struct {
    byte grpPR   :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0TSCR2STR;
extern volatile TIM0TSCR2STR _TIM0TSCR2 @0x000005CD;
# 7641 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7648 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte C0F         :1;                                        
    byte C1F         :1;                                        
    byte C2F         :1;                                        
    byte C3F         :1;                                        
    byte C4F         :1;                                        
    byte C5F         :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} TIM0TFLG1STR;
extern volatile TIM0TFLG1STR _TIM0TFLG1 @0x000005CE;
# 7672 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7679 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte TOF         :1;                                        
  } Bits;
} TIM0TFLG2STR;
extern volatile TIM0TFLG2STR _TIM0TFLG2 @0x000005CF;






 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC0HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC0LoSTR;
    
  } Overlap_STR;

} TIM0TC0STR;
extern volatile TIM0TC0STR _TIM0TC0 @0x000005D0;

 



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC1HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC1LoSTR;
    
  } Overlap_STR;

} TIM0TC1STR;
extern volatile TIM0TC1STR _TIM0TC1 @0x000005D2;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC2HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC2LoSTR;
    
  } Overlap_STR;

} TIM0TC2STR;
extern volatile TIM0TC2STR _TIM0TC2 @0x000005D4;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC3HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC3LoSTR;
    
  } Overlap_STR;

} TIM0TC3STR;
extern volatile TIM0TC3STR _TIM0TC3 @0x000005D6;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC4HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC4LoSTR;
    
  } Overlap_STR;

} TIM0TC4STR;
extern volatile TIM0TC4STR _TIM0TC4 @0x000005D8;



 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC5HiSTR;
    

     
    union {
      byte Byte;
       

      
       

      
    } TIM0TC5LoSTR;
    
  } Overlap_STR;

} TIM0TC5STR;
extern volatile TIM0TC5STR _TIM0TC5 @0x000005DA;



 
typedef union {
  byte Byte;
  struct {
    byte OCPD0       :1;                                        
    byte OCPD1       :1;                                        
    byte OCPD2       :1;                                        
    byte OCPD3       :1;                                        
    byte OCPD4       :1;                                        
    byte OCPD5       :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpOCPD :6;
    byte         :1;
    byte         :1;
  } MergedBits;
} TIM0OCPDSTR;
extern volatile TIM0OCPDSTR _TIM0OCPD @0x000005EC;
# 7942 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7951 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PTPS0       :1;                                        
    byte PTPS1       :1;                                        
    byte PTPS2       :1;                                        
    byte PTPS3       :1;                                        
    byte PTPS4       :1;                                        
    byte PTPS5       :1;                                        
    byte PTPS6       :1;                                        
    byte PTPS7       :1;                                        
  } Bits;
} TIM0PTPSRSTR;
extern volatile TIM0PTPSRSTR _TIM0PTPSR @0x000005EE;
# 7977 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 7986 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte MOD_CFG     :1;                                        
        byte STR_SEQA    :1;                                        
        byte ACC_CFG     :2;                                        
        byte SWAI        :1;                                        
        byte FRZ_MOD     :1;                                        
        byte ADC_SR      :1;                                        
        byte ADC_EN      :1;                                        
      } Bits;
    } ADC0CTL_0STR;
# 8014 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
     

    
# 8025 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte AUT_RSTA    :1;                                        
        byte SMOD_ACC    :1;                                        
        byte RVL_BMOD    :1;                                        
        byte CSL_BMOD    :1;                                        
      } Bits;
    } ADC0CTL_1STR;





    




    
  } Overlap_STR;

  struct {
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word AUT_RSTA    :1;                                        
    word SMOD_ACC    :1;                                        
    word RVL_BMOD    :1;                                        
    word CSL_BMOD    :1;                                        
    word MOD_CFG     :1;                                        
    word STR_SEQA    :1;                                        
    word ACC_CFG     :2;                                        
    word SWAI        :1;                                        
    word FRZ_MOD     :1;                                        
    word ADC_SR      :1;                                        
    word ADC_EN      :1;                                        
  } Bits;
} ADC0CTLSTR;
extern volatile ADC0CTLSTR _ADC0CTL @0x00000600;
# 8085 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 8098 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte READY       :1;                                        
    byte             :1; 
    byte DBECC_ERR   :1;                                        
    byte RVL_SEL     :1;                                        
    byte CSL_SEL     :1;                                        
  } Bits;
} ADC0STSSTR;
extern volatile ADC0STSSTR _ADC0STS @0x00000602;












 
typedef union {
  byte Byte;
  struct {
    byte PRS         :7;                                        
    byte             :1; 
  } Bits;
} ADC0TIMSTR;
extern volatile ADC0TIMSTR _ADC0TIM @0x00000603;







 
typedef union {
  byte Byte;
  struct {
    byte SRES        :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte DJM         :1;                                        
  } Bits;
} ADC0FMTSTR;
extern volatile ADC0FMTSTR _ADC0FMT @0x00000604;









 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte LDOK        :1;                                        
    byte RSTA        :1;                                        
    byte TRIG        :1;                                        
    byte SEQA        :1;                                        
  } Bits;
} ADC0FLWCTLSTR;
extern volatile ADC0FLWCTLSTR _ADC0FLWCTL @0x00000605;












 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte LDOK_EIE    :1;                                        
    byte RSTAR_EIE   :1;                                        
    byte TRIG_EIE    :1;                                        
    byte             :1; 
    byte EOL_EIE     :1;                                        
    byte CMD_EIE     :1;                                        
    byte IA_EIE      :1;                                        
  } Bits;
} ADC0EIESTR;
extern volatile ADC0EIESTR _ADC0EIE @0x00000606;
# 8214 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 8221 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte CONIF_OIE   :1;                                        
    byte SEQAD_IE    :1;                                        
  } Bits;
} ADC0IESTR;
extern volatile ADC0IESTR _ADC0IE @0x00000607;








 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte LDOK_EIF    :1;                                        
    byte RSTAR_EIF   :1;                                        
    byte TRIG_EIF    :1;                                        
    byte             :1; 
    byte EOL_EIF     :1;                                        
    byte CMD_EIF     :1;                                        
    byte IA_EIF      :1;                                        
  } Bits;
} ADC0EIFSTR;
extern volatile ADC0EIFSTR _ADC0EIF @0x00000608;
# 8268 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 8275 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte CONIF_OIF   :1;                                        
    byte SEQAD_IF    :1;                                        
  } Bits;
} ADC0IFSTR;
extern volatile ADC0IFSTR _ADC0IF @0x00000609;








 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CON_IE8     :1;                                        
        byte CON_IE9     :1;                                        
        byte CON_IE10    :1;                                        
        byte CON_IE11    :1;                                        
        byte CON_IE12    :1;                                        
        byte CON_IE13    :1;                                        
        byte CON_IE14    :1;                                        
        byte CON_IE15    :1;                                        
      } Bits;
    } ADC0CONIE_0STR;
# 8328 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
     

    
# 8339 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte EOL_IE      :1;                                        
        byte CON_IE1     :1;                                        
        byte CON_IE2     :1;                                        
        byte CON_IE3     :1;                                        
        byte CON_IE4     :1;                                        
        byte CON_IE5     :1;                                        
        byte CON_IE6     :1;                                        
        byte CON_IE7     :1;                                        
      } Bits;
      struct {
        byte     :1;
        byte grpCON_IE_1 :7;
      } MergedBits;
    } ADC0CONIE_1STR;
# 8370 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 8381 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word EOL_IE      :1;                                        
    word CON_IE1     :1;                                        
    word CON_IE2     :1;                                        
    word CON_IE3     :1;                                        
    word CON_IE4     :1;                                        
    word CON_IE5     :1;                                        
    word CON_IE6     :1;                                        
    word CON_IE7     :1;                                        
    word CON_IE8     :1;                                        
    word CON_IE9     :1;                                        
    word CON_IE10    :1;                                        
    word CON_IE11    :1;                                        
    word CON_IE12    :1;                                        
    word CON_IE13    :1;                                        
    word CON_IE14    :1;                                        
    word CON_IE15    :1;                                        
  } Bits;
  struct {
    word         :1;
    word grpCON_IE_1 :15;
  } MergedBits;
} ADC0CONIESTR;
extern volatile ADC0CONIESTR _ADC0CONIE @0x0000060A;
# 8427 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 8446 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte CON_IF8     :1;                                        
        byte CON_IF9     :1;                                        
        byte CON_IF10    :1;                                        
        byte CON_IF11    :1;                                        
        byte CON_IF12    :1;                                        
        byte CON_IF13    :1;                                        
        byte CON_IF14    :1;                                        
        byte CON_IF15    :1;                                        
      } Bits;
    } ADC0CONIF_0STR;
# 8476 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
     

    
# 8487 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte EOL_IF      :1;                                        
        byte CON_IF1     :1;                                        
        byte CON_IF2     :1;                                        
        byte CON_IF3     :1;                                        
        byte CON_IF4     :1;                                        
        byte CON_IF5     :1;                                        
        byte CON_IF6     :1;                                        
        byte CON_IF7     :1;                                        
      } Bits;
      struct {
        byte     :1;
        byte grpCON_IF_1 :7;
      } MergedBits;
    } ADC0CONIF_1STR;
# 8518 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 8529 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word EOL_IF      :1;                                        
    word CON_IF1     :1;                                        
    word CON_IF2     :1;                                        
    word CON_IF3     :1;                                        
    word CON_IF4     :1;                                        
    word CON_IF5     :1;                                        
    word CON_IF6     :1;                                        
    word CON_IF7     :1;                                        
    word CON_IF8     :1;                                        
    word CON_IF9     :1;                                        
    word CON_IF10    :1;                                        
    word CON_IF11    :1;                                        
    word CON_IF12    :1;                                        
    word CON_IF13    :1;                                        
    word CON_IF14    :1;                                        
    word CON_IF15    :1;                                        
  } Bits;
  struct {
    word         :1;
    word grpCON_IF_1 :15;
  } MergedBits;
} ADC0CONIFSTR;
extern volatile ADC0CONIFSTR _ADC0CONIF @0x0000060C;
# 8575 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 8594 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte             :1; 
        byte RVL_IMD     :1;                                        
        byte CSL_IMD     :1;                                        
      } Bits;
    } ADC0IMDRI_0STR;



     

    


    

     
    union {
      byte Byte;
      struct {
        byte RIDX_IMD    :6;                                        
        byte             :1; 
        byte             :1; 
      } Bits;
    } ADC0IMDRI_1STR;


    


    
  } Overlap_STR;

  struct {
    word RIDX_IMD    :6;                                        
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word             :1; 
    word RVL_IMD     :1;                                        
    word CSL_IMD     :1;                                        
  } Bits;
} ADC0IMDRISTR;
extern volatile ADC0IMDRISTR _ADC0IMDRI @0x0000060E;











 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte RVL_EOL     :1;                                        
    byte CSL_EOL     :1;                                        
  } Bits;
} ADC0EOLRISTR;
extern volatile ADC0EOLRISTR _ADC0EOLRI @0x00000610;








 
typedef union {
  dword Dword;
    
  struct {
     
    union {
      word Word;
        
      struct {
         
        union {
          byte Byte;
          struct {
            byte INTFLG_SEL  :4;                                        
            byte OPT         :2;                                        
            byte CMD_SEL     :2;                                        
          } Bits;
        } ADC0CMD_0STR;




         

        
# 8723 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
    
         
        union {
          byte Byte;
          struct {
            byte CH_SEL      :6;                                        
            byte VRL_SEL     :1;                                        
            byte VRH_SEL     :1;                                        
          } Bits;
        } ADC0CMD_1STR;




        




        
      } Overlap_STR;
    
      struct {
        word CH_SEL      :6;                                        
        word VRL_SEL     :1;                                        
        word VRH_SEL     :1;                                        
        word INTFLG_SEL  :4;                                        
        word OPT         :2;                                        
        word CMD_SEL     :2;                                        
      } Bits;
    } ADC0CMD_01STR;
# 8762 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 8773 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      word Word;
        
      struct {
         
        union {
          byte Byte;
          struct {
            byte             :1; 
            byte OPT         :2;                                        
            byte SMP         :5;                                        
          } Bits;
        } ADC0CMD_2STR;



        




        
    
         
        union {
          byte Byte;
          struct {
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
          } Bits;
        } ADC0CMD_3STR;

        
      } Overlap_STR;
    
      struct {
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word             :1; 
        word OPT         :2;                                        
        word SMP         :5;                                        
      } Bits;
    } ADC0CMD_23STR;



    




    
  } Overlap_STR;

} ADC0CMDSTR;
extern volatile ADC0CMDSTR _ADC0CMD @0x00000614;



 
typedef union {
  byte Byte;
  struct {
    byte CMD_IDX     :6;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} ADC0CIDXSTR;
extern volatile ADC0CIDXSTR _ADC0CIDX @0x0000061C;







 
typedef union {
  byte Byte;
  struct {
    byte CMD_PTR     :8;                                        
  } Bits;
} ADC0CBP_0STR;
extern volatile ADC0CBP_0STR _ADC0CBP_0 @0x0000061D;


 






 
typedef union {
  byte Byte;
  struct {
    byte CMD_PTR     :8;                                        
  } Bits;
} ADC0CBP_1STR;
extern volatile ADC0CBP_1STR _ADC0CBP_1 @0x0000061E;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte CMD_PTR     :6;                                        
  } Bits;
} ADC0CBP_2STR;
extern volatile ADC0CBP_2STR _ADC0CBP_2 @0x0000061F;







 
typedef union {
  byte Byte;
  struct {
    byte RES_IDX     :6;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} ADC0RIDXSTR;
extern volatile ADC0RIDXSTR _ADC0RIDX @0x00000620;







 
typedef union {
  byte Byte;
  struct {
    byte RES_PTR     :4;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} ADC0RBP_0STR;
extern volatile ADC0RBP_0STR _ADC0RBP_0 @0x00000621;


 






 
typedef union {
  byte Byte;
  struct {
    byte RES_PTR     :8;                                        
  } Bits;
} ADC0RBP_1STR;
extern volatile ADC0RBP_1STR _ADC0RBP_1 @0x00000622;







 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte RES_PTR     :6;                                        
  } Bits;
} ADC0RBP_2STR;
extern volatile ADC0RBP_2STR _ADC0RBP_2 @0x00000623;







 
typedef union {
  byte Byte;
  struct {
    byte CMDRES_OFF0 :7;                                        
    byte             :1; 
  } Bits;
} ADC0CROFF0STR;
extern volatile ADC0CROFF0STR _ADC0CROFF0 @0x00000624;


 






 
typedef union {
  byte Byte;
  struct {
    byte CMDRES_OFF1 :7;                                        
    byte             :1; 
  } Bits;
} ADC0CROFF1STR;
extern volatile ADC0CROFF1STR _ADC0CROFF1 @0x00000625;







 
typedef union {
  byte Byte;
  struct {
    byte DACM        :3;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte DRIVE       :1;                                        
    byte FVR         :1;                                        
  } Bits;
} DACCTLSTR;
extern volatile DACCTLSTR _DACCTL @0x00000680;











 
typedef union {
  byte Byte;
  struct {
    byte VOLTAGE     :8;                                        
  } Bits;
} DACVOLSTR;
extern volatile DACVOLSTR _DACVOL @0x00000682;







 
typedef union {
  byte Byte;
  struct {
    byte ACMOD       :2;                                        
    byte ACHYS       :2;                                        
    byte ACDLY       :1;                                        
    byte ACOPS       :1;                                        
    byte ACOPE       :1;                                        
    byte ACE         :1;                                        
  } Bits;
} ACMPC0STR;
extern volatile ACMPC0STR _ACMPC0 @0x00000690;
# 9076 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 9087 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ACNSEL      :2;                                        
    byte             :1; 
    byte             :1; 
    byte ACPSEL      :2;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} ACMPC1STR;
extern volatile ACMPC1STR _ACMPC1 @0x00000691;










 
typedef union {
  byte Byte;
  struct {
    byte ACIE        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} ACMPC2STR;
extern volatile ACMPC2STR _ACMPC2 @0x00000692;






 
typedef union {
  byte Byte;
  struct {
    byte ACIF        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte ACO         :1;                                        
  } Bits;
} ACMPSSTR;
extern volatile ACMPSSTR _ACMPS @0x00000693;








 
typedef union {
  byte Byte;
  struct {
    byte PMRF        :1;                                        
    byte OMRF        :1;                                        
    byte             :1; 
    byte COPRF       :1;                                        
    byte             :1; 
    byte LVRF        :1;                                        
    byte PORF        :1;                                        
    byte             :1; 
  } Bits;
} CPMURFLGSTR;
extern volatile CPMURFLGSTR _CPMURFLG @0x000006C3;
# 9177 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte SYNDIV0     :1;                                        
    byte SYNDIV1     :1;                                        
    byte SYNDIV2     :1;                                        
    byte SYNDIV3     :1;                                        
    byte SYNDIV4     :1;                                        
    byte SYNDIV5     :1;                                        
    byte VCOFRQ0     :1;                                        
    byte VCOFRQ1     :1;                                        
  } Bits;
  struct {
    byte grpSYNDIV :6;
    byte grpVCOFRQ :2;
  } MergedBits;
} CPMUSYNRSTR;
extern volatile CPMUSYNRSTR _CPMUSYNR @0x000006C4;
# 9215 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9228 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte REFDIV0     :1;                                        
    byte REFDIV1     :1;                                        
    byte REFDIV2     :1;                                        
    byte REFDIV3     :1;                                        
    byte             :1; 
    byte             :1; 
    byte REFFRQ0     :1;                                        
    byte REFFRQ1     :1;                                        
  } Bits;
  struct {
    byte grpREFDIV :4;
    byte         :1;
    byte         :1;
    byte grpREFFRQ :2;
  } MergedBits;
} CPMUREFDIVSTR;
extern volatile CPMUREFDIVSTR _CPMUREFDIV @0x000006C5;
# 9260 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9271 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte POSTDIV0    :1;                                        
    byte POSTDIV1    :1;                                        
    byte POSTDIV2    :1;                                        
    byte POSTDIV3    :1;                                        
    byte POSTDIV4    :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpPOSTDIV :5;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CPMUPOSTDIVSTR;
extern volatile CPMUPOSTDIVSTR _CPMUPOSTDIV @0x000006C6;
# 9301 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9309 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte UPOSC       :1;                                        
    byte OSCIF       :1;                                        
    byte             :1; 
    byte LOCK        :1;                                        
    byte LOCKIF      :1;                                        
    byte             :1; 
    byte             :1; 
    byte RTIF        :1;                                        
  } Bits;
} CPMUIFLGSTR;
extern volatile CPMUIFLGSTR _CPMUIFLG @0x000006C7;
# 9332 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte OSCIE       :1;                                        
    byte             :1; 
    byte             :1; 
    byte LOCKIE      :1;                                        
    byte             :1; 
    byte             :1; 
    byte RTIE        :1;                                        
  } Bits;
} CPMUINTSTR;
extern volatile CPMUINTSTR _CPMUINT @0x000006C8;










 
typedef union {
  byte Byte;
  struct {
    byte COPOSCSEL0  :1;                                        
    byte RTIOSCSEL   :1;                                        
    byte PCE         :1;                                        
    byte PRE         :1;                                        
    byte COPOSCSEL1  :1;                                        
    byte CSAD        :1;                                        
    byte PSTP        :1;                                        
    byte PLLSEL      :1;                                        
  } Bits;
} CPMUCLKSSTR;
extern volatile CPMUCLKSSTR _CPMUCLKS @0x000006C9;
# 9389 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9398 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte FM0         :1;                                        
    byte FM1         :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte grpFM   :2;
    byte         :1;
    byte         :1;
  } MergedBits;
} CPMUPLLSTR;
extern volatile CPMUPLLSTR _CPMUPLL @0x000006CA;











 
typedef union {
  byte Byte;
  struct {
    byte RTR0        :1;                                        
    byte RTR1        :1;                                        
    byte RTR2        :1;                                        
    byte RTR3        :1;                                        
    byte RTR4        :1;                                        
    byte RTR5        :1;                                        
    byte RTR6        :1;                                        
    byte RTDEC       :1;                                        
  } Bits;
  struct {
    byte grpRTR  :7;
    byte         :1;
  } MergedBits;
} CPMURTISTR;
extern volatile CPMURTISTR _CPMURTI @0x000006CB;
# 9464 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9475 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte CR0         :1;                                        
    byte CR1         :1;                                        
    byte CR2         :1;                                        
    byte             :1; 
    byte             :1; 
    byte WRTMASK     :1;                                        
    byte RSBCK       :1;                                        
    byte WCOP        :1;                                        
  } Bits;
  struct {
    byte grpCR   :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CPMUCOPSTR;
extern volatile CPMUCOPSTR _CPMUCOP @0x000006CC;
# 9508 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9517 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BIT0        :1;                                        
    byte BIT1        :1;                                        
    byte BIT2        :1;                                        
    byte BIT3        :1;                                        
    byte BIT4        :1;                                        
    byte BIT5        :1;                                        
    byte BIT6        :1;                                        
    byte BIT7        :1;                                        
  } Bits;
} CPMUARMCOPSTR;
extern volatile CPMUARMCOPSTR _CPMUARMCOP @0x000006CF;
# 9543 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9552 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte HTIF        :1;                                        
    byte HTIE        :1;                                        
    byte HTDS        :1;                                        
    byte HTE         :1;                                        
    byte             :1; 
    byte VSEL        :1;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} CPMUHTCTLSTR;
extern volatile CPMUHTCTLSTR _CPMUHTCTL @0x000006D0;
# 9575 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte LVIF        :1;                                        
    byte LVIE        :1;                                        
    byte LVDS        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} CPMULVCTLSTR;
extern volatile CPMULVCTLSTR _CPMULVCTL @0x000006D1;










 
typedef union {
  byte Byte;
  struct {
    byte APIF        :1;                                        
    byte APIE        :1;                                        
    byte APIFE       :1;                                        
    byte APIEA       :1;                                        
    byte APIES       :1;                                        
    byte             :1; 
    byte             :1; 
    byte APICLK      :1;                                        
  } Bits;
} CPMUAPICTLSTR;
extern volatile CPMUAPICTLSTR _CPMUAPICTL @0x000006D2;
# 9630 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9637 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte ACLKTR0     :1;                                        
    byte ACLKTR1     :1;                                        
    byte ACLKTR2     :1;                                        
    byte ACLKTR3     :1;                                        
    byte ACLKTR4     :1;                                        
    byte ACLKTR5     :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte         :1;
    byte grpACLKTR :6;
  } MergedBits;
} CPMUACLKTRSTR;
extern volatile CPMUACLKTRSTR _CPMUACLKTR @0x000006D3;
# 9667 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9676 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte APIR8       :1;                                        
        byte APIR9       :1;                                        
        byte APIR10      :1;                                        
        byte APIR11      :1;                                        
        byte APIR12      :1;                                        
        byte APIR13      :1;                                        
        byte APIR14      :1;                                        
        byte APIR15      :1;                                        
      } Bits;
    } CPMUAPIRHSTR;
# 9706 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 9715 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte APIR0       :1;                                        
        byte APIR1       :1;                                        
        byte APIR2       :1;                                        
        byte APIR3       :1;                                        
        byte APIR4       :1;                                        
        byte APIR5       :1;                                        
        byte APIR6       :1;                                        
        byte APIR7       :1;                                        
      } Bits;
    } CPMUAPIRLSTR;
# 9740 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 9749 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word APIR0       :1;                                        
    word APIR1       :1;                                        
    word APIR2       :1;                                        
    word APIR3       :1;                                        
    word APIR4       :1;                                        
    word APIR5       :1;                                        
    word APIR6       :1;                                        
    word APIR7       :1;                                        
    word APIR8       :1;                                        
    word APIR9       :1;                                        
    word APIR10      :1;                                        
    word APIR11      :1;                                        
    word APIR12      :1;                                        
    word APIR13      :1;                                        
    word APIR14      :1;                                        
    word APIR15      :1;                                        
  } Bits;
} CPMUAPIRSTR;
extern volatile CPMUAPIRSTR _CPMUAPIR @0x000006D4;
# 9789 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9806 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte HTTR        :4;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte HTOE        :1;                                        
  } Bits;
} CPMUHTTRSTR;
extern volatile CPMUHTTRSTR _CPMUHTTR @0x000006D7;









 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte IRCTRIM8    :1;                                        
        byte IRCTRIM9    :1;                                        
        byte             :1; 
        byte TCTRIM0     :1;                                        
        byte TCTRIM1     :1;                                        
        byte TCTRIM2     :1;                                        
        byte TCTRIM3     :1;                                        
        byte TCTRIM4     :1;                                        
      } Bits;
      struct {
        byte grpIRCTRIM_8 :2;
        byte     :1;
        byte grpTCTRIM :5;
      } MergedBits;
    } CPMUIRCTRIMHSTR;
# 9864 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 9876 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte IRCTRIM0    :1;                                        
        byte IRCTRIM1    :1;                                        
        byte IRCTRIM2    :1;                                        
        byte IRCTRIM3    :1;                                        
        byte IRCTRIM4    :1;                                        
        byte IRCTRIM5    :1;                                        
        byte IRCTRIM6    :1;                                        
        byte IRCTRIM7    :1;                                        
      } Bits;
    } CPMUIRCTRIMLSTR;
# 9901 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 9910 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word IRCTRIM0    :1;                                        
    word IRCTRIM1    :1;                                        
    word IRCTRIM2    :1;                                        
    word IRCTRIM3    :1;                                        
    word IRCTRIM4    :1;                                        
    word IRCTRIM5    :1;                                        
    word IRCTRIM6    :1;                                        
    word IRCTRIM7    :1;                                        
    word IRCTRIM8    :1;                                        
    word IRCTRIM9    :1;                                        
    word             :1; 
    word TCTRIM0     :1;                                        
    word TCTRIM1     :1;                                        
    word TCTRIM2     :1;                                        
    word TCTRIM3     :1;                                        
    word TCTRIM4     :1;                                        
  } Bits;
  struct {
    word grpIRCTRIM :10;
    word         :1;
    word grpTCTRIM :5;
  } MergedBits;
} CPMUIRCTRIMSTR;
extern volatile CPMUIRCTRIMSTR _CPMUIRCTRIM @0x000006D8;
# 9956 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 9976 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte OSCE        :1;                                        
  } Bits;
} CPMUOSCSTR;
extern volatile CPMUOSCSTR _CPMUOSC @0x000006DA;






 
typedef union {
  byte Byte;
  struct {
    byte PROT        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} CPMUPROTSTR;
extern volatile CPMUPROTSTR _CPMUPROT @0x000006DB;






 
typedef union {
  byte Byte;
  struct {
    byte INTXON      :1;                                        
    byte EXTXON      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte VREG5VEN    :1;                                        
  } Bits;
} CPMUVREGCTLSTR;
extern volatile CPMUVREGCTLSTR _CPMUVREGCTL @0x000006DD;










 
typedef union {
  byte Byte;
  struct {
    byte OSCMOD      :1;                                        
    byte OMRE        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} CPMUOSC2STR;
extern volatile CPMUOSC2STR _CPMUOSC2 @0x000006DE;








 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte BSUSE       :1;                                        
    byte BSUAE       :1;                                        
    byte BVLS        :2;                                        
    byte BVHS        :1;                                        
    byte             :1; 
  } Bits;
} BATESTR;
extern volatile BATESTR _BATE @0x000006F0;













 
typedef union {
  byte Byte;
  struct {
    byte BVLC        :1;                                        
    byte BVHC        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} BATSRSTR;
extern volatile BATSRSTR _BATSR @0x000006F1;








 
typedef union {
  byte Byte;
  struct {
    byte BVLIE       :1;                                        
    byte BVHIE       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} BATIESTR;
extern volatile BATIESTR _BATIE @0x000006F2;








 
typedef union {
  byte Byte;
  struct {
    byte BVLIF       :1;                                        
    byte BVHIF       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} BATIFSTR;
extern volatile BATIFSTR _BATIF @0x000006F3;








 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      union {  
         
        union {
          struct {
            byte BKDIF       :1;                                        
            byte BERRIF      :1;                                        
            byte BERRV       :1;                                        
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte RXEDGIF     :1;                                        
          } Bits;
        } SCI0ASR1STR;





        




        
         
        union {
          struct {
            byte SBR8        :1;                                        
            byte SBR9        :1;                                        
            byte SBR10       :1;                                        
            byte SBR11       :1;                                        
            byte SBR12       :1;                                        
            byte SBR13       :1;                                        
            byte SBR14       :1;                                        
            byte SBR15       :1;                                        
          } Bits;
        } SCI0BDHSTR;
# 10219 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
# 10228 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
      } SameAddr_STR;  
    
    } SCI0ASR1STR;
    

     
    union {
      byte Byte;
      union {  
         
        union {
          struct {
            byte BKDIE       :1;                                        
            byte BERRIE      :1;                                        
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte RXEDGIE     :1;                                        
          } Bits;
        } SCI0ACR1STR;




        



        
         
        union {
          struct {
            byte SBR0        :1;                                        
            byte SBR1        :1;                                        
            byte SBR2        :1;                                        
            byte SBR3        :1;                                        
            byte SBR4        :1;                                        
            byte SBR5        :1;                                        
            byte SBR6        :1;                                        
            byte SBR7        :1;                                        
          } Bits;
        } SCI0BDLSTR;
# 10282 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
# 10291 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
      } SameAddr_STR;  
    
    } SCI0ACR1STR;
    
  } Overlap_STR;

  struct {
    word SBR0        :1;                                        
    word SBR1        :1;                                        
    word SBR2        :1;                                        
    word SBR3        :1;                                        
    word SBR4        :1;                                        
    word SBR5        :1;                                        
    word SBR6        :1;                                        
    word SBR7        :1;                                        
    word SBR8        :1;                                        
    word SBR9        :1;                                        
    word SBR10       :1;                                        
    word SBR11       :1;                                        
    word SBR12       :1;                                        
    word SBR13       :1;                                        
    word SBR14       :1;                                        
    word SBR15       :1;                                        
  } Bits;
} SCI0BDSTR;
extern volatile SCI0BDSTR _SCI0BD @0x00000700;
# 10335 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10352 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  union {  
     
    union {
      struct {
        byte BKDFE       :1;                                        
        byte BERRM0      :1;                                        
        byte BERRM1      :1;                                        
        byte             :1; 
        byte             :1; 
        byte TNP0        :1;                                        
        byte TNP1        :1;                                        
        byte IREN        :1;                                        
      } Bits;
      struct {
        byte     :1;
        byte grpBERRM :2;
        byte     :1;
        byte     :1;
        byte grpTNP :2;
        byte     :1;
      } MergedBits;
    } SCI0ACR2STR;
# 10388 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 10399 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
     
    union {
      struct {
        byte PT          :1;                                        
        byte PE          :1;                                        
        byte ILT         :1;                                        
        byte WAKE        :1;                                        
        byte M           :1;                                        
        byte RSRC        :1;                                        
        byte SCISWAI     :1;                                        
        byte LOOPS       :1;                                        
      } Bits;
    } SCI0CR1STR;
# 10422 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 10431 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } SameAddr_STR;  

} SCI0ACR2STR;
extern volatile SCI0ACR2STR _SCI0ACR2 @0x00000702;


 
typedef union {
  byte Byte;
  struct {
    byte SBK         :1;                                        
    byte RWU         :1;                                        
    byte RE          :1;                                        
    byte TE          :1;                                        
    byte ILIE        :1;                                        
    byte RIE         :1;                                        
    byte TCIE        :1;                                        
    byte TIE         :1;                                        
  } Bits;
} SCI0CR2STR;
extern volatile SCI0CR2STR _SCI0CR2 @0x00000703;
# 10462 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10471 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PF          :1;                                        
    byte FE          :1;                                        
    byte NF          :1;                                        
    byte OR          :1;                                        
    byte IDLE        :1;                                        
    byte RDRF        :1;                                        
    byte TC          :1;                                        
    byte TDRE        :1;                                        
  } Bits;
} SCI0SR1STR;
extern volatile SCI0SR1STR _SCI0SR1 @0x00000704;
# 10497 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10506 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RAF         :1;                                        
    byte TXDIR       :1;                                        
    byte BRK13       :1;                                        
    byte RXPOL       :1;                                        
    byte TXPOL       :1;                                        
    byte             :1; 
    byte             :1; 
    byte AMAP        :1;                                        
  } Bits;
} SCI0SR2STR;
extern volatile SCI0SR2STR _SCI0SR2 @0x00000705;
# 10530 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10537 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte T8          :1;                                        
    byte R8          :1;                                        
  } Bits;
} SCI0DRHSTR;
extern volatile SCI0DRHSTR _SCI0DRH @0x00000706;








 
typedef union {
  byte Byte;
  struct {
    byte R0_T0       :1;                                        
    byte R1_T1       :1;                                        
    byte R2_T2       :1;                                        
    byte R3_T3       :1;                                        
    byte R4_T4       :1;                                        
    byte R5_T5       :1;                                        
    byte R6_T6       :1;                                        
    byte R7_T7       :1;                                        
  } Bits;
} SCI0DRLSTR;
extern volatile SCI0DRLSTR _SCI0DRL @0x00000707;
# 10586 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10595 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      union {  
         
        union {
          struct {
            byte BKDIF       :1;                                        
            byte BERRIF      :1;                                        
            byte BERRV       :1;                                        
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte RXEDGIF     :1;                                        
          } Bits;
        } SCI1ASR1STR;





        




        
         
        union {
          struct {
            byte SBR8        :1;                                        
            byte SBR9        :1;                                        
            byte SBR10       :1;                                        
            byte SBR11       :1;                                        
            byte SBR12       :1;                                        
            byte SBR13       :1;                                        
            byte SBR14       :1;                                        
            byte SBR15       :1;                                        
          } Bits;
        } SCI1BDHSTR;
# 10652 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
# 10661 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
      } SameAddr_STR;  
    
    } SCI1ASR1STR;
    

     
    union {
      byte Byte;
      union {  
         
        union {
          struct {
            byte BKDIE       :1;                                        
            byte BERRIE      :1;                                        
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte             :1; 
            byte RXEDGIE     :1;                                        
          } Bits;
        } SCI1ACR1STR;




        



        
         
        union {
          struct {
            byte SBR0        :1;                                        
            byte SBR1        :1;                                        
            byte SBR2        :1;                                        
            byte SBR3        :1;                                        
            byte SBR4        :1;                                        
            byte SBR5        :1;                                        
            byte SBR6        :1;                                        
            byte SBR7        :1;                                        
          } Bits;
        } SCI1BDLSTR;
# 10715 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
# 10724 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
        
      } SameAddr_STR;  
    
    } SCI1ACR1STR;
    
  } Overlap_STR;

  struct {
    word SBR0        :1;                                        
    word SBR1        :1;                                        
    word SBR2        :1;                                        
    word SBR3        :1;                                        
    word SBR4        :1;                                        
    word SBR5        :1;                                        
    word SBR6        :1;                                        
    word SBR7        :1;                                        
    word SBR8        :1;                                        
    word SBR9        :1;                                        
    word SBR10       :1;                                        
    word SBR11       :1;                                        
    word SBR12       :1;                                        
    word SBR13       :1;                                        
    word SBR14       :1;                                        
    word SBR15       :1;                                        
  } Bits;
} SCI1BDSTR;
extern volatile SCI1BDSTR _SCI1BD @0x00000710;
# 10768 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10785 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  union {  
     
    union {
      struct {
        byte BKDFE       :1;                                        
        byte BERRM0      :1;                                        
        byte BERRM1      :1;                                        
        byte             :1; 
        byte             :1; 
        byte TNP0        :1;                                        
        byte TNP1        :1;                                        
        byte IREN        :1;                                        
      } Bits;
      struct {
        byte     :1;
        byte grpBERRM :2;
        byte     :1;
        byte     :1;
        byte grpTNP :2;
        byte     :1;
      } MergedBits;
    } SCI1ACR2STR;
# 10821 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 10832 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
     
    union {
      struct {
        byte PT          :1;                                        
        byte PE          :1;                                        
        byte ILT         :1;                                        
        byte WAKE        :1;                                        
        byte M           :1;                                        
        byte RSRC        :1;                                        
        byte SCISWAI     :1;                                        
        byte LOOPS       :1;                                        
      } Bits;
    } SCI1CR1STR;
# 10855 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 10864 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } SameAddr_STR;  

} SCI1ACR2STR;
extern volatile SCI1ACR2STR _SCI1ACR2 @0x00000712;


 
typedef union {
  byte Byte;
  struct {
    byte SBK         :1;                                        
    byte RWU         :1;                                        
    byte RE          :1;                                        
    byte TE          :1;                                        
    byte ILIE        :1;                                        
    byte RIE         :1;                                        
    byte TCIE        :1;                                        
    byte TIE         :1;                                        
  } Bits;
} SCI1CR2STR;
extern volatile SCI1CR2STR _SCI1CR2 @0x00000713;
# 10895 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10904 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PF          :1;                                        
    byte FE          :1;                                        
    byte NF          :1;                                        
    byte OR          :1;                                        
    byte IDLE        :1;                                        
    byte RDRF        :1;                                        
    byte TC          :1;                                        
    byte TDRE        :1;                                        
  } Bits;
} SCI1SR1STR;
extern volatile SCI1SR1STR _SCI1SR1 @0x00000714;
# 10930 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10939 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RAF         :1;                                        
    byte TXDIR       :1;                                        
    byte BRK13       :1;                                        
    byte RXPOL       :1;                                        
    byte TXPOL       :1;                                        
    byte             :1; 
    byte             :1; 
    byte AMAP        :1;                                        
  } Bits;
} SCI1SR2STR;
extern volatile SCI1SR2STR _SCI1SR2 @0x00000715;
# 10963 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 10970 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte T8          :1;                                        
    byte R8          :1;                                        
  } Bits;
} SCI1DRHSTR;
extern volatile SCI1DRHSTR _SCI1DRH @0x00000716;








 
typedef union {
  byte Byte;
  struct {
    byte R0_T0       :1;                                        
    byte R1_T1       :1;                                        
    byte R2_T2       :1;                                        
    byte R3_T3       :1;                                        
    byte R4_T4       :1;                                        
    byte R5_T5       :1;                                        
    byte R6_T6       :1;                                        
    byte R7_T7       :1;                                        
  } Bits;
} SCI1DRLSTR;
extern volatile SCI1DRLSTR _SCI1DRL @0x00000717;
# 11019 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11028 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte LSBFE       :1;                                        
    byte SSOE        :1;                                        
    byte CPHA        :1;                                        
    byte CPOL        :1;                                        
    byte MSTR        :1;                                        
    byte SPTIE       :1;                                        
    byte SPE         :1;                                        
    byte SPIE        :1;                                        
  } Bits;
} SPI0CR1STR;
extern volatile SPI0CR1STR _SPI0CR1 @0x00000780;
# 11054 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11063 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SPC0        :1;                                        
    byte SPISWAI     :1;                                        
    byte             :1; 
    byte BIDIROE     :1;                                        
    byte MODFEN      :1;                                        
    byte             :1; 
    byte XFRW        :1;                                        
    byte             :1; 
  } Bits;
} SPI0CR2STR;
extern volatile SPI0CR2STR _SPI0CR2 @0x00000781;
# 11086 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"








 
typedef union {
  byte Byte;
  struct {
    byte SPR0        :1;                                        
    byte SPR1        :1;                                        
    byte SPR2        :1;                                        
    byte             :1; 
    byte SPPR0       :1;                                        
    byte SPPR1       :1;                                        
    byte SPPR2       :1;                                        
    byte             :1; 
  } Bits;
  struct {
    byte grpSPR  :3;
    byte         :1;
    byte grpSPPR :3;
    byte         :1;
  } MergedBits;
} SPI0BRSTR;
extern volatile SPI0BRSTR _SPI0BR @0x00000782;
# 11124 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11135 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte MODF        :1;                                        
    byte SPTEF       :1;                                        
    byte             :1; 
    byte SPIF        :1;                                        
  } Bits;
} SPI0SRSTR;
extern volatile SPI0SRSTR _SPI0SR @0x00000783;










 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte R8_T8       :1;                                        
        byte R9_T9       :1;                                        
        byte R10_T10     :1;                                        
        byte R11_T11     :1;                                        
        byte R12_T12     :1;                                        
        byte R13_T13     :1;                                        
        byte R14_T14     :1;                                        
        byte R15_T15     :1;                                        
      } Bits;
    } SPI0DRHSTR;
# 11190 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 11199 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte R0_T0       :1;                                        
        byte R1_T1       :1;                                        
        byte R2_T2       :1;                                        
        byte R3_T3       :1;                                        
        byte R4_T4       :1;                                        
        byte R5_T5       :1;                                        
        byte R6_T6       :1;                                        
        byte R7_T7       :1;                                        
      } Bits;
    } SPI0DRLSTR;
# 11224 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 11233 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word R0_T0       :1;                                        
    word R1_T1       :1;                                        
    word R2_T2       :1;                                        
    word R3_T3       :1;                                        
    word R4_T4       :1;                                        
    word R5_T5       :1;                                        
    word R6_T6       :1;                                        
    word R7_T7       :1;                                        
    word R8_T8       :1;                                        
    word R9_T9       :1;                                        
    word R10_T10     :1;                                        
    word R11_T11     :1;                                        
    word R12_T12     :1;                                        
    word R13_T13     :1;                                        
    word R14_T14     :1;                                        
    word R15_T15     :1;                                        
  } Bits;
} SPI0DRSTR;
extern volatile SPI0DRSTR _SPI0DR @0x00000784;
# 11273 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11290 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte ADR1        :1;                                        
    byte ADR2        :1;                                        
    byte ADR3        :1;                                        
    byte ADR4        :1;                                        
    byte ADR5        :1;                                        
    byte ADR6        :1;                                        
    byte ADR7        :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte grpADR_1 :7;
  } MergedBits;
} IIC0IBADSTR;
extern volatile IIC0IBADSTR _IIC0IBAD @0x000007C0;
# 11321 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11331 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte IBC0        :1;                                        
    byte IBC1        :1;                                        
    byte IBC2        :1;                                        
    byte IBC3        :1;                                        
    byte IBC4        :1;                                        
    byte IBC5        :1;                                        
    byte IBC6        :1;                                        
    byte IBC7        :1;                                        
  } Bits;
} IIC0IBFDSTR;
extern volatile IIC0IBFDSTR _IIC0IBFD @0x000007C1;
# 11357 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11366 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte IBSWAI      :1;                                        
    byte             :1; 
    byte RSTA        :1;                                        
    byte TXAK        :1;                                        
    byte TX_RX       :1;                                        
    byte MS_SL       :1;                                        
    byte IBIE        :1;                                        
    byte IBEN        :1;                                        
  } Bits;
} IIC0IBCRSTR;
extern volatile IIC0IBCRSTR _IIC0IBCR @0x000007C2;
# 11391 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11399 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RXAK        :1;                                        
    byte IBIF        :1;                                        
    byte SRW         :1;                                        
    byte             :1; 
    byte IBAL        :1;                                        
    byte IBB         :1;                                        
    byte IAAS        :1;                                        
    byte TCF         :1;                                        
  } Bits;
} IIC0IBSRSTR;
extern volatile IIC0IBSRSTR _IIC0IBSR @0x000007C3;
# 11424 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11432 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte D0          :1;                                        
    byte D1          :1;                                        
    byte D2          :1;                                        
    byte D3          :1;                                        
    byte D4          :1;                                        
    byte D5          :1;                                        
    byte D6          :1;                                        
    byte D7          :1;                                        
  } Bits;
} IIC0IBDRSTR;
extern volatile IIC0IBDRSTR _IIC0IBDR @0x000007C4;
# 11458 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11467 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ADR8        :1;                                        
    byte ADR9        :1;                                        
    byte ADR10       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte ADTYPE      :1;                                        
    byte GCEN        :1;                                        
  } Bits;
  struct {
    byte grpADR_8 :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} IIC0IBCR2STR;
extern volatile IIC0IBCR2STR _IIC0IBCR2 @0x000007C5;
# 11500 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11508 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte INITRQ      :1;                                        
    byte SLPRQ       :1;                                        
    byte WUPE        :1;                                        
    byte TIME        :1;                                        
    byte SYNCH       :1;                                        
    byte CSWAI       :1;                                        
    byte RXACT       :1;                                        
    byte RXFRM       :1;                                        
  } Bits;
} CAN0CTL0STR;
extern volatile CAN0CTL0STR _CAN0CTL0 @0x00000800;
# 11534 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 11545 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte INITAK      :1;                                        
    byte SLPAK       :1;                                        
    byte WUPM        :1;                                        
    byte BORM        :1;                                        
    byte LISTEN      :1;                                        
    byte LOOPB       :1;                                        
    byte CLKSRC      :1;                                        
    byte CANE        :1;                                        
  } Bits;
} CAN0CTL1STR;
extern volatile CAN0CTL1STR _CAN0CTL1 @0x00000801;
# 11571 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11580 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BRP0        :1;                                        
    byte BRP1        :1;                                        
    byte BRP2        :1;                                        
    byte BRP3        :1;                                        
    byte BRP4        :1;                                        
    byte BRP5        :1;                                        
    byte SJW0        :1;                                        
    byte SJW1        :1;                                        
  } Bits;
  struct {
    byte grpBRP  :6;
    byte grpSJW  :2;
  } MergedBits;
} CAN0BTR0STR;
extern volatile CAN0BTR0STR _CAN0BTR0 @0x00000802;
# 11610 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 




# 11627 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte TSEG10      :1;                                        
    byte TSEG11      :1;                                        
    byte TSEG12      :1;                                        
    byte TSEG13      :1;                                        
    byte TSEG20      :1;                                        
    byte TSEG21      :1;                                        
    byte TSEG22      :1;                                        
    byte SAMP        :1;                                        
  } Bits;
  struct {
    byte grpTSEG_10 :4;
    byte grpTSEG_20 :3;
    byte         :1;
  } MergedBits;
} CAN0BTR1STR;
extern volatile CAN0BTR1STR _CAN0BTR1 @0x00000803;
# 11661 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11674 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RXF         :1;                                        
    byte OVRIF       :1;                                        
    byte TSTAT0      :1;                                        
    byte TSTAT1      :1;                                        
    byte RSTAT0      :1;                                        
    byte RSTAT1      :1;                                        
    byte CSCIF       :1;                                        
    byte WUPIF       :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte         :1;
    byte grpTSTAT :2;
    byte grpRSTAT :2;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0RFLGSTR;
extern volatile CAN0RFLGSTR _CAN0RFLG @0x00000804;
# 11710 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11723 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RXFIE       :1;                                        
    byte OVRIE       :1;                                        
    byte TSTATE0     :1;                                        
    byte TSTATE1     :1;                                        
    byte RSTATE0     :1;                                        
    byte RSTATE1     :1;                                        
    byte CSCIE       :1;                                        
    byte WUPIE       :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte         :1;
    byte grpTSTATE :2;
    byte grpRSTATE :2;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0RIERSTR;
extern volatile CAN0RIERSTR _CAN0RIER @0x00000805;
# 11759 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11772 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte TXE0        :1;                                        
    byte TXE1        :1;                                        
    byte TXE2        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpTXE  :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TFLGSTR;
extern volatile CAN0TFLGSTR _CAN0TFLG @0x00000806;













 
typedef union {
  byte Byte;
  struct {
    byte TXEIE0      :1;                                        
    byte TXEIE1      :1;                                        
    byte TXEIE2      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpTXEIE :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TIERSTR;
extern volatile CAN0TIERSTR _CAN0TIER @0x00000807;













 
typedef union {
  byte Byte;
  struct {
    byte ABTRQ0      :1;                                        
    byte ABTRQ1      :1;                                        
    byte ABTRQ2      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpABTRQ :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TARQSTR;
extern volatile CAN0TARQSTR _CAN0TARQ @0x00000808;













 
typedef union {
  byte Byte;
  struct {
    byte ABTAK0      :1;                                        
    byte ABTAK1      :1;                                        
    byte ABTAK2      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpABTAK :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TAAKSTR;
extern volatile CAN0TAAKSTR _CAN0TAAK @0x00000809;













 
typedef union {
  byte Byte;
  struct {
    byte TX0         :1;                                        
    byte TX1         :1;                                        
    byte TX2         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpTX   :3;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TBSELSTR;
extern volatile CAN0TBSELSTR _CAN0TBSEL @0x0000080A;













 
typedef union {
  byte Byte;
  struct {
    byte IDHIT0      :1;                                        
    byte IDHIT1      :1;                                        
    byte IDHIT2      :1;                                        
    byte             :1; 
    byte IDAM        :2;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpIDHIT :3;
    byte         :1;
    byte         :2;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0IDACSTR;
extern volatile CAN0IDACSTR _CAN0IDAC @0x0000080B;
# 11981 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 11989 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte BOHOLD      :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} CAN0MISCSTR;
extern volatile CAN0MISCSTR _CAN0MISC @0x0000080D;






 
typedef union {
  byte Byte;
  struct {
    byte RXERR0      :1;                                        
    byte RXERR1      :1;                                        
    byte RXERR2      :1;                                        
    byte RXERR3      :1;                                        
    byte RXERR4      :1;                                        
    byte RXERR5      :1;                                        
    byte RXERR6      :1;                                        
    byte RXERR7      :1;                                        
  } Bits;
} CAN0RXERRSTR;
extern volatile CAN0RXERRSTR _CAN0RXERR @0x0000080E;
# 12036 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12045 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte TXERR0      :1;                                        
    byte TXERR1      :1;                                        
    byte TXERR2      :1;                                        
    byte TXERR3      :1;                                        
    byte TXERR4      :1;                                        
    byte TXERR5      :1;                                        
    byte TXERR6      :1;                                        
    byte TXERR7      :1;                                        
  } Bits;
} CAN0TXERRSTR;
extern volatile CAN0TXERRSTR _CAN0TXERR @0x0000080F;
# 12071 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12080 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR0STR;
extern volatile CAN0IDAR0STR _CAN0IDAR0 @0x00000810;
# 12106 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 12117 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR1STR;
extern volatile CAN0IDAR1STR _CAN0IDAR1 @0x00000811;
# 12143 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12152 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR2STR;
extern volatile CAN0IDAR2STR _CAN0IDAR2 @0x00000812;
# 12178 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12187 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR3STR;
extern volatile CAN0IDAR3STR _CAN0IDAR3 @0x00000813;
# 12213 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12222 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR0STR;
extern volatile CAN0IDMR0STR _CAN0IDMR0 @0x00000814;
# 12248 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 12259 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR1STR;
extern volatile CAN0IDMR1STR _CAN0IDMR1 @0x00000815;
# 12285 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12294 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR2STR;
extern volatile CAN0IDMR2STR _CAN0IDMR2 @0x00000816;
# 12320 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12329 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR3STR;
extern volatile CAN0IDMR3STR _CAN0IDMR3 @0x00000817;
# 12355 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12364 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR4STR;
extern volatile CAN0IDAR4STR _CAN0IDAR4 @0x00000818;
# 12390 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12399 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR5STR;
extern volatile CAN0IDAR5STR _CAN0IDAR5 @0x00000819;
# 12425 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12434 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR6STR;
extern volatile CAN0IDAR6STR _CAN0IDAR6 @0x0000081A;
# 12460 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12469 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AC0         :1;                                        
    byte AC1         :1;                                        
    byte AC2         :1;                                        
    byte AC3         :1;                                        
    byte AC4         :1;                                        
    byte AC5         :1;                                        
    byte AC6         :1;                                        
    byte AC7         :1;                                        
  } Bits;
} CAN0IDAR7STR;
extern volatile CAN0IDAR7STR _CAN0IDAR7 @0x0000081B;
# 12495 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12504 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR4STR;
extern volatile CAN0IDMR4STR _CAN0IDMR4 @0x0000081C;
# 12530 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12539 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR5STR;
extern volatile CAN0IDMR5STR _CAN0IDMR5 @0x0000081D;
# 12565 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12574 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR6STR;
extern volatile CAN0IDMR6STR _CAN0IDMR6 @0x0000081E;
# 12600 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12609 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte AM0         :1;                                        
    byte AM1         :1;                                        
    byte AM2         :1;                                        
    byte AM3         :1;                                        
    byte AM4         :1;                                        
    byte AM5         :1;                                        
    byte AM6         :1;                                        
    byte AM7         :1;                                        
  } Bits;
} CAN0IDMR7STR;
extern volatile CAN0IDMR7STR _CAN0IDMR7 @0x0000081F;
# 12635 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12644 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID21        :1;                                        
    byte ID22        :1;                                        
    byte ID23        :1;                                        
    byte ID24        :1;                                        
    byte ID25        :1;                                        
    byte ID26        :1;                                        
    byte ID27        :1;                                        
    byte ID28        :1;                                        
  } Bits;
} CAN0RXIDR0STR;
extern volatile CAN0RXIDR0STR _CAN0RXIDR0 @0x00000820;
# 12670 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 12681 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID15        :1;                                        
    byte ID16        :1;                                        
    byte ID17        :1;                                        
    byte IDE         :1;                                        
    byte SRR         :1;                                        
    byte ID18        :1;                                        
    byte ID19        :1;                                        
    byte ID20        :1;                                        
  } Bits;
  struct {
    byte grpID_15 :3;
    byte         :1;
    byte         :1;
    byte grpID_18 :3;
  } MergedBits;
} CAN0RXIDR1STR;
extern volatile CAN0RXIDR1STR _CAN0RXIDR1 @0x00000821;
# 12716 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12729 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID7         :1;                                        
    byte ID8         :1;                                        
    byte ID9         :1;                                        
    byte ID10        :1;                                        
    byte ID11        :1;                                        
    byte ID12        :1;                                        
    byte ID13        :1;                                        
    byte ID14        :1;                                        
  } Bits;
} CAN0RXIDR2STR;
extern volatile CAN0RXIDR2STR _CAN0RXIDR2 @0x00000822;
# 12755 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12764 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RTR         :1;                                        
    byte ID0         :1;                                        
    byte ID1         :1;                                        
    byte ID2         :1;                                        
    byte ID3         :1;                                        
    byte ID4         :1;                                        
    byte ID5         :1;                                        
    byte ID6         :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte grpID   :7;
  } MergedBits;
} CAN0RXIDR3STR;
extern volatile CAN0RXIDR3STR _CAN0RXIDR3 @0x00000823;
# 12795 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12806 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR0STR;
extern volatile CAN0RXDSR0STR _CAN0RXDSR0 @0x00000824;
# 12832 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 12843 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR1STR;
extern volatile CAN0RXDSR1STR _CAN0RXDSR1 @0x00000825;
# 12869 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12878 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR2STR;
extern volatile CAN0RXDSR2STR _CAN0RXDSR2 @0x00000826;
# 12904 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12913 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR3STR;
extern volatile CAN0RXDSR3STR _CAN0RXDSR3 @0x00000827;
# 12939 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12948 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR4STR;
extern volatile CAN0RXDSR4STR _CAN0RXDSR4 @0x00000828;
# 12974 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 12983 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR5STR;
extern volatile CAN0RXDSR5STR _CAN0RXDSR5 @0x00000829;
# 13009 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13018 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR6STR;
extern volatile CAN0RXDSR6STR _CAN0RXDSR6 @0x0000082A;
# 13044 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13053 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0RXDSR7STR;
extern volatile CAN0RXDSR7STR _CAN0RXDSR7 @0x0000082B;
# 13079 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13088 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DLC0        :1;                                        
    byte DLC1        :1;                                        
    byte DLC2        :1;                                        
    byte DLC3        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpDLC  :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0RXDLRSTR;
extern volatile CAN0RXDLRSTR _CAN0RXDLR @0x0000082C;
# 13118 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13125 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte TSR8        :1;                                        
        byte TSR9        :1;                                        
        byte TSR10       :1;                                        
        byte TSR11       :1;                                        
        byte TSR12       :1;                                        
        byte TSR13       :1;                                        
        byte TSR14       :1;                                        
        byte TSR15       :1;                                        
      } Bits;
    } CAN0RXTSRHSTR;
# 13155 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 13164 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte TSR0        :1;                                        
        byte TSR1        :1;                                        
        byte TSR2        :1;                                        
        byte TSR3        :1;                                        
        byte TSR4        :1;                                        
        byte TSR5        :1;                                        
        byte TSR6        :1;                                        
        byte TSR7        :1;                                        
      } Bits;
    } CAN0RXTSRLSTR;
# 13189 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 13198 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word TSR0        :1;                                        
    word TSR1        :1;                                        
    word TSR2        :1;                                        
    word TSR3        :1;                                        
    word TSR4        :1;                                        
    word TSR5        :1;                                        
    word TSR6        :1;                                        
    word TSR7        :1;                                        
    word TSR8        :1;                                        
    word TSR9        :1;                                        
    word TSR10       :1;                                        
    word TSR11       :1;                                        
    word TSR12       :1;                                        
    word TSR13       :1;                                        
    word TSR14       :1;                                        
    word TSR15       :1;                                        
  } Bits;
} CAN0RXTSRSTR;
extern volatile CAN0RXTSRSTR _CAN0RXTSR @0x0000082E;
# 13238 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13255 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID21        :1;                                        
    byte ID22        :1;                                        
    byte ID23        :1;                                        
    byte ID24        :1;                                        
    byte ID25        :1;                                        
    byte ID26        :1;                                        
    byte ID27        :1;                                        
    byte ID28        :1;                                        
  } Bits;
} CAN0TXIDR0STR;
extern volatile CAN0TXIDR0STR _CAN0TXIDR0 @0x00000830;
# 13281 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 13292 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID15        :1;                                        
    byte ID16        :1;                                        
    byte ID17        :1;                                        
    byte IDE         :1;                                        
    byte SRR         :1;                                        
    byte ID18        :1;                                        
    byte ID19        :1;                                        
    byte ID20        :1;                                        
  } Bits;
  struct {
    byte grpID_15 :3;
    byte         :1;
    byte         :1;
    byte grpID_18 :3;
  } MergedBits;
} CAN0TXIDR1STR;
extern volatile CAN0TXIDR1STR _CAN0TXIDR1 @0x00000831;
# 13327 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13340 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte ID7         :1;                                        
    byte ID8         :1;                                        
    byte ID9         :1;                                        
    byte ID10        :1;                                        
    byte ID11        :1;                                        
    byte ID12        :1;                                        
    byte ID13        :1;                                        
    byte ID14        :1;                                        
  } Bits;
} CAN0TXIDR2STR;
extern volatile CAN0TXIDR2STR _CAN0TXIDR2 @0x00000832;
# 13366 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13375 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte RTR         :1;                                        
    byte ID0         :1;                                        
    byte ID1         :1;                                        
    byte ID2         :1;                                        
    byte ID3         :1;                                        
    byte ID4         :1;                                        
    byte ID5         :1;                                        
    byte ID6         :1;                                        
  } Bits;
  struct {
    byte         :1;
    byte grpID   :7;
  } MergedBits;
} CAN0TXIDR3STR;
extern volatile CAN0TXIDR3STR _CAN0TXIDR3 @0x00000833;
# 13406 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13417 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR0STR;
extern volatile CAN0TXDSR0STR _CAN0TXDSR0 @0x00000834;
# 13443 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
 


# 13454 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR1STR;
extern volatile CAN0TXDSR1STR _CAN0TXDSR1 @0x00000835;
# 13480 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13489 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR2STR;
extern volatile CAN0TXDSR2STR _CAN0TXDSR2 @0x00000836;
# 13515 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13524 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR3STR;
extern volatile CAN0TXDSR3STR _CAN0TXDSR3 @0x00000837;
# 13550 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13559 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR4STR;
extern volatile CAN0TXDSR4STR _CAN0TXDSR4 @0x00000838;
# 13585 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13594 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR5STR;
extern volatile CAN0TXDSR5STR _CAN0TXDSR5 @0x00000839;
# 13620 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13629 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR6STR;
extern volatile CAN0TXDSR6STR _CAN0TXDSR6 @0x0000083A;
# 13655 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13664 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DB0         :1;                                        
    byte DB1         :1;                                        
    byte DB2         :1;                                        
    byte DB3         :1;                                        
    byte DB4         :1;                                        
    byte DB5         :1;                                        
    byte DB6         :1;                                        
    byte DB7         :1;                                        
  } Bits;
} CAN0TXDSR7STR;
extern volatile CAN0TXDSR7STR _CAN0TXDSR7 @0x0000083B;
# 13690 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13699 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DLC0        :1;                                        
    byte DLC1        :1;                                        
    byte DLC2        :1;                                        
    byte DLC3        :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpDLC  :4;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} CAN0TXDLRSTR;
extern volatile CAN0TXDLRSTR _CAN0TXDLR @0x0000083C;
# 13729 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13736 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte PRIO0       :1;                                        
    byte PRIO1       :1;                                        
    byte PRIO2       :1;                                        
    byte PRIO3       :1;                                        
    byte PRIO4       :1;                                        
    byte PRIO5       :1;                                        
    byte PRIO6       :1;                                        
    byte PRIO7       :1;                                        
  } Bits;
} CAN0TXTBPRSTR;
extern volatile CAN0TXTBPRSTR _CAN0TXTBPR @0x0000083D;
# 13762 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13771 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  word Word;
    
  struct {
     
    union {
      byte Byte;
      struct {
        byte TSR8        :1;                                        
        byte TSR9        :1;                                        
        byte TSR10       :1;                                        
        byte TSR11       :1;                                        
        byte TSR12       :1;                                        
        byte TSR13       :1;                                        
        byte TSR14       :1;                                        
        byte TSR15       :1;                                        
      } Bits;
    } CAN0TXTSRHSTR;
# 13801 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 13810 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    

     
    union {
      byte Byte;
      struct {
        byte TSR0        :1;                                        
        byte TSR1        :1;                                        
        byte TSR2        :1;                                        
        byte TSR3        :1;                                        
        byte TSR4        :1;                                        
        byte TSR5        :1;                                        
        byte TSR6        :1;                                        
        byte TSR7        :1;                                        
      } Bits;
    } CAN0TXTSRLSTR;
# 13835 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
# 13844 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"
    
  } Overlap_STR;

  struct {
    word TSR0        :1;                                        
    word TSR1        :1;                                        
    word TSR2        :1;                                        
    word TSR3        :1;                                        
    word TSR4        :1;                                        
    word TSR5        :1;                                        
    word TSR6        :1;                                        
    word TSR7        :1;                                        
    word TSR8        :1;                                        
    word TSR9        :1;                                        
    word TSR10       :1;                                        
    word TSR11       :1;                                        
    word TSR12       :1;                                        
    word TSR13       :1;                                        
    word TSR14       :1;                                        
    word TSR15       :1;                                        
  } Bits;
} CAN0TXTSRSTR;
extern volatile CAN0TXTSRSTR _CAN0TXTSR @0x0000083E;
# 13884 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 13901 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte LPDR0       :1;                                        
    byte LPDR1       :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
  struct {
    byte grpLPDR :2;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
    byte         :1;
  } MergedBits;
} LP0DRSTR;
extern volatile LP0DRSTR _LP0DR @0x00000980;











 
typedef union {
  byte Byte;
  struct {
    byte LPPUE       :1;                                        
    byte LPWUE       :1;                                        
    byte RXONLY      :1;                                        
    byte LPE         :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} LP0CRSTR;
extern volatile LP0CRSTR _LP0CR @0x00000981;












 
typedef union {
  byte Byte;
  struct {
    byte LPSLR       :2;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte LPDTDIS     :1;                                        
  } Bits;
} LP0SLRMSTR;
extern volatile LP0SLRMSTR _LP0SLRM @0x00000983;









 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte LPDT        :1;                                        
  } Bits;
} LP0SRSTR;
extern volatile LP0SRSTR _LP0SR @0x00000985;






 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte LPOCIE      :1;                                        
    byte LPDTIE      :1;                                        
  } Bits;
} LP0IESTR;
extern volatile LP0IESTR _LP0IE @0x00000986;








 
typedef union {
  byte Byte;
  struct {
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte LPOCIF      :1;                                        
    byte LPDTIF      :1;                                        
  } Bits;
} LP0IFSTR;
extern volatile LP0IFSTR _LP0IF @0x00000987;








 
typedef union {
  byte Byte;
  struct {
    byte PGAEN_bit   :1;                                          
    byte PGAOFFSCEN  :1;                                        
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PGAENSTR;
extern volatile PGAENSTR _PGAEN @0x00000B40;








 
typedef union {
  byte Byte;
  struct {
    byte PGAINSEL    :2;                                        
    byte             :1; 
    byte             :1; 
    byte PGAREFSEL   :2;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} PGACNTLSTR;
extern volatile PGACNTLSTR _PGACNTL @0x00000B41;










 
typedef union {
  byte Byte;
  struct {
    byte PGAGAIN_grp :4;                                          
    byte             :1; 
    byte             :1; 
    byte             :1; 
    byte             :1; 
  } Bits;
} PGAGAINSTR;
extern volatile PGAGAINSTR _PGAGAIN @0x00000B42;







 
typedef union {
  byte Byte;
  struct {
    byte PGAOFFSET_grp :6;                                        
    byte             :1; 
    byte             :1; 
  } Bits;
} PGAOFFSETSTR;
extern volatile PGAOFFSETSTR _PGAOFFSET @0x00000B43;







 
typedef union {
  word Word;
  struct {
    word KEY         :16;                                       
  } Bits;
} BAKEY0STR;
 



 






 
typedef union {
  word Word;
  struct {
    word KEY         :16;                                       
  } Bits;
} BAKEY1STR;
 








 
typedef union {
  word Word;
  struct {
    word KEY         :16;                                       
  } Bits;
} BAKEY2STR;
 








 
typedef union {
  word Word;
  struct {
    word KEY         :16;                                       
  } Bits;
} BAKEY3STR;
 








 
typedef union {
  word Word;
  struct {
    word KEY         :16;                                       
  } Bits;
} PROTKEYSTR;
 








 
typedef union {
  byte Byte;
  struct {
    byte FPLS0       :1;                                        
    byte FPLS1       :1;                                        
    byte FPLDIS      :1;                                        
    byte FPHS0       :1;                                        
    byte FPHS1       :1;                                        
    byte FPHDIS      :1;                                        
    byte RNV6        :1;                                        
    byte FPOPEN      :1;                                        
  } Bits;
  struct {
    byte grpFPLS :2;
    byte         :1;
    byte grpFPHS :2;
    byte         :1;
    byte grpRNV_6 :1;
    byte         :1;
  } MergedBits;
} NVFPROTSTR;
 
# 14254 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 14267 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte DPS0        :1;                                        
    byte DPS1        :1;                                        
    byte DPS2        :1;                                        
    byte DPS3        :1;                                        
    byte DPS4        :1;                                        
    byte DPS5        :1;                                        
    byte DPS6        :1;                                        
    byte DPOPEN      :1;                                        
  } Bits;
  struct {
    byte grpDPS  :7;
    byte         :1;
  } MergedBits;
} NVDFPROTSTR;
 
# 14299 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 14310 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte NV0         :1;                                        
    byte NV1         :1;                                        
    byte NV2         :1;                                        
    byte NV3         :1;                                        
    byte NV4         :1;                                        
    byte NV5         :1;                                        
    byte NV6         :1;                                        
    byte NV7         :1;                                        
  } Bits;
} NVFOPTSTR;
 
# 14337 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 14346 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
typedef union {
  byte Byte;
  struct {
    byte SEC0        :1;                                        
    byte SEC1        :1;                                        
    byte RNV2        :1;                                        
    byte RNV3        :1;                                        
    byte RNV4        :1;                                        
    byte RNV5        :1;                                        
    byte KEYEN0      :1;                                        
    byte KEYEN1      :1;                                        
  } Bits;
  struct {
    byte grpSEC  :2;
    byte grpRNV_2 :4;
    byte grpKEYEN :2;
  } MergedBits;
} NVFSECSTR;
 
# 14382 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"

# 14397 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 
extern volatile void* volatile MMCPC @0x00000085;           
extern volatile void* volatile DBGAA @0x00000115;           
extern volatile void* volatile DBGBA @0x00000125;           
extern volatile void* volatile DBGDA @0x00000145;           
extern volatile void* volatile ECCDPTR @0x000003C7;         
extern volatile void* volatile ADC0CBP @0x0000061D;         
extern volatile void* volatile ADC0RBP @0x00000621;         


   
# 14417 "C:/workspace/NE1AW_PORTING/Generated_Code/IO_Map.h"


 




 







 

# 75 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"

 


/*vcast_scrub*/

 
# 90 "C:/workspace/NE1AW_PORTING/Generated_Code/Cpu.h"














 

extern volatile byte LastResetSource;   
extern volatile byte CCR_reg;           

 

/*vcast_scrub*/
void _EntryPoint(void);










 

 

__interrupt void Cpu_IllegalOpcode(void);









 

__interrupt void Cpu_MachineException(void);








 

__interrupt void Cpu_SpareOpcode(void);









 

__interrupt void Cpu_LvdStatusChanged(void);









 

__interrupt void Cpu_PllLockStatusChanged(void);









 

__interrupt void Cpu_OscStatusChanged(void);









 

__interrupt void Cpu_SRAM_ECC(void);








 

__interrupt void Cpu_SpuriousInterrupt(void);








 

 
__interrupt void Cpu_Interrupt(void);

/*vcast_scrub*/













 














 






























 

void PE_low_level_init(void);










 

 




 







 
# 78 "C:/workspace/NE1AW_PORTING/Generated_Code/EEPROM.h"




   
  typedef  word * EEPROM_TAddress;      
  typedef  word * EEPROM_TAddress_Const;  


/*vcast_scrub*/


 


 


 

 

 

 





 
 

 


byte EEPROM_SetByte(EEPROM_TAddress_Const Addr,byte Data);


























 

byte EEPROM_GetByte(EEPROM_TAddress_Const Addr,byte *Data);



















 

void EEPROM_Init(void);










 

/*vcast_scrub*/

 




 







 
# 83 "C:/workspace/NE1AW_PORTING/Generated_Code/EEPROM.c"

 
typedef   word * EEPROM_TAddress_;  

/*vcast_scrub*/
/*vcast_scrub*/

 

static word BackupArray[0x02];          










 
static void BackupSector(EEPROM_TAddress_ Addr, word From, word To)
{ /*vcast_internal_start*/
extern unsigned  *P_9_1_1;
extern unsigned  P_9_1_2;
extern unsigned  P_9_1_3;
extern unsigned char SBF_9_1;
if(SBF_9_1) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_656684112
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_656684112
  if ( vcast_is_in_driver ) {
    P_9_1_1 = Addr;
    P_9_1_2 = From;
    P_9_1_3 = To;
    vCAST_COMMON_STUB_PROC_9( 9, 1, 4, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_656684112
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_656684112
  vCAST_USER_CODE_TIMER_START();
  return;
}
{ /*vcast_internal_end*/

  word i;
  word ValidFrom;
  word ValidTo;

   
  ValidFrom = From;
  if (ValidFrom > (word)2U) {   
    ValidFrom = (word)2U;
  }
  
   
  ValidTo = To;
  if (ValidTo > (word)4U) {   
    ValidTo = (word)4U;
  }

   
  for (i = ValidFrom; i < ValidTo; i = (word)(i + 2U)) {
    word index = i/2U;
     
     
    BackupArray[index] = Addr[index];  
  }
} /*vcast_internal_start*/}/*vcast_internal_end*/











 
 
static byte SetupFCCOB(dword PhraseAddr, word From, word To,  word* Data, word* pIndex);

static byte WriteBlock(EEPROM_TAddress_ Addr, word From, word To,  word* Data)
{ /*vcast_internal_start*/
extern unsigned  *P_9_2_1;
extern unsigned  P_9_2_2;
extern unsigned  P_9_2_3;
extern unsigned  *P_9_2_4;
extern unsigned char  R_9_2;
extern unsigned char SBF_9_2;
if(SBF_9_2) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_1834319982
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_1834319982
  if ( vcast_is_in_driver ) {
    P_9_2_1 = Addr;
    P_9_2_2 = From;
    P_9_2_3 = To;
    P_9_2_4 = Data;
    vCAST_COMMON_STUB_PROC_9( 9, 2, 5, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_1834319982
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_1834319982
  vCAST_USER_CODE_TIMER_START();
  return R_9_2;
}
{ /*vcast_internal_end*/

  byte result = 0U;
  byte err = 0U;
  word i;
  byte j;
  dword PhraseAddr;

   
  if(From != To) {
    i = From;
    PhraseAddr = (dword)Addr;
    
    while((i < To) && (result == (byte)0U)) {
       
      byte setupResult = SetupFCCOB(PhraseAddr, From, To, Data, &i);
      
      _FSTAT . Byte = 0x80U;                      
      while (_FSTAT . Bits . CCIF == (byte)0U) {
        ;  
      }
      
       
      if ((_FSTAT . Byte & (byte)0x30U) != (byte)0U) {        
        result = 9U;            
      } else if (_FSTAT . MergedBits . grpMGSTAT != (byte)0U) {          
        err = 1U;                         
      } else {
         
      }
      
       
      if (PhraseAddr <= (0xFFFFFFFFUL - (dword)8U)) {
        PhraseAddr += (dword)8U;
      } else {
         
        result = 9U;
      }
    }
    
     
    if((result == (byte)0U) && (err != (byte)0U)) {
      result = 3U;                 
    }
  }
  
   
  return result;
} /*vcast_internal_start*/}/*vcast_internal_end*/











 
static byte SetupFCCOB(dword PhraseAddr, word From, word To,  word* Data, word* pIndex)
{ /*vcast_internal_start*/
extern unsigned long  P_9_3_1;
extern unsigned  P_9_3_2;
extern unsigned  P_9_3_3;
extern unsigned  *P_9_3_4;
extern unsigned  *P_9_3_5;
extern unsigned char  R_9_3;
extern unsigned char SBF_9_3;
if(SBF_9_3) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_4190692900
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_4190692900
  if ( vcast_is_in_driver ) {
    P_9_3_1 = PhraseAddr;
    P_9_3_2 = From;
    P_9_3_3 = To;
    P_9_3_4 = Data;
    P_9_3_5 = pIndex;
    vCAST_COMMON_STUB_PROC_9( 9, 3, 6, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_4190692900
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_4190692900
  vCAST_USER_CODE_TIMER_START();
  return R_9_3;
}
{ /*vcast_internal_end*/

  byte j;
  word i = *pIndex;
  
   
  _FSTAT . Byte = 0x30U;                      
  _FCCOBIX . Byte = 5U;                       
  _FCCOB0 . Overlap_STR . FCCOB0HISTR . Byte = 0x11U;                   
  _FCCOB0 . Overlap_STR . FCCOB0LOSTR . Byte = (byte)((PhraseAddr >> 16U) & (dword)0xFFU);  
  _FCCOB1 . Word = (word)(PhraseAddr & (dword)0xFFFFU);          
  
  for(j = (byte)0U; j < (byte)4U; j++) {
    *((volatile word*)&_FCCOB2 . Word + j) = *(( word *)(Data + (i/2U)));  
    
     
    if (i <= (0xFFFFU - 2U)) {
         
      i = (word)(i + 2U);
    } else {
       
      i = To;  
    }
    
    if(i >= To) {
      _FCCOBIX . Byte = j + (byte)2U;               
      break;
    }
  }
  
  *pIndex = i;
  return 0U;
} /*vcast_internal_start*/}/*vcast_internal_end*/










 
static byte EraseSectorInternal(EEPROM_TAddress_ Addr)
{ /*vcast_internal_start*/
extern unsigned  *P_9_4_1;
extern unsigned char  R_9_4;
extern unsigned char SBF_9_4;
if(SBF_9_4) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_654130152
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_654130152
  if ( vcast_is_in_driver ) {
    P_9_4_1 = Addr;
    vCAST_COMMON_STUB_PROC_9( 9, 4, 2, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_654130152
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_654130152
  vCAST_USER_CODE_TIMER_START();
  return R_9_4;
}
{ /*vcast_internal_end*/

  byte result = 0U;
  
  if (_FSTAT . Bits . CCIF == (byte)0U) {               
    result = 8U;                  
  } else {
     
    _FSTAT . Byte = 0x30U;                      
    _FCCOBIX . Byte = 1U;                       
    _FCCOB0 . Overlap_STR . FCCOB0HISTR . Byte = 0x12U;                   
    _FCCOB0 . Overlap_STR . FCCOB0LOSTR . Byte = (byte)((((dword)Addr) >> 16) & (dword)0xFFU);  
    _FCCOB1 . Word = (word)(((dword)Addr) & (dword)0xFFFEU);  
    _FSTAT . Byte = 0x80U;                      
    while (_FSTAT . Bits . CCIF == (byte)0U) {
      ;  
    }
    if ((_FSTAT . Byte & (byte)0x23U) != (byte)0U) {        
      result = 9U;            
    }
  }
  return result;                        
} /*vcast_internal_start*/}/*vcast_internal_end*/









 
static byte WriteWord(EEPROM_TAddress_ AddrRow, word Data16)
{ /*vcast_internal_start*/
extern unsigned  *P_9_5_1;
extern unsigned  P_9_5_2;
extern unsigned char  R_9_5;
extern unsigned char SBF_9_5;
if(SBF_9_5) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_2206668051
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_2206668051
  if ( vcast_is_in_driver ) {
    P_9_5_1 = AddrRow;
    P_9_5_2 = Data16;
    vCAST_COMMON_STUB_PROC_9( 9, 5, 3, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_2206668051
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_2206668051
  vCAST_USER_CODE_TIMER_START();
  return R_9_5;
}
{ /*vcast_internal_end*/

  byte result = 0U;
  
  if (_FSTAT . Bits . CCIF == (byte)0U) {               
    result = 8U;                  
  } else {
     
    _FSTAT . Byte = 0x30U;                      
    _FCCOBIX . Byte = 2U;                       
    _FCCOB0 . Overlap_STR . FCCOB0HISTR . Byte = 0x11U;                   
    _FCCOB0 . Overlap_STR . FCCOB0LOSTR . Byte = (byte)((((dword)AddrRow) >> 16) & (dword)0xFFU);  
    _FCCOB1 . Word = (word)(((dword)AddrRow) & (dword)0xFFFFU);    
    _FCCOB2 . Word = Data16;                    
    _FSTAT . Byte = 0x80U;                      
    if ((_FSTAT . Byte & (byte)0x30U) != (byte)0U) {        
      result = 9U;            
    } else {
      while (_FSTAT . Bits . CCIF == (byte)0U) {
        ;  
      }
      if (_FSTAT . MergedBits . grpMGSTAT != (byte)0U) {               
        result = 3U;             
      }
    }
  }
  return result;                        
} /*vcast_internal_start*/}/*vcast_internal_end*/




























 
byte EEPROM_SetByte(EEPROM_TAddress_Const Addr,byte Data)
{ /*vcast_internal_start*/
extern unsigned  *P_9_6_1;
extern unsigned char  P_9_6_2;
extern unsigned char  R_9_6;
extern unsigned char SBF_9_6;
if(SBF_9_6) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_1042310301
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_1042310301
  if ( vcast_is_in_driver ) {
    P_9_6_1 = Addr;
    P_9_6_2 = Data;
    vCAST_COMMON_STUB_PROC_9( 9, 6, 3, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_1042310301
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_1042310301
  vCAST_USER_CODE_TIMER_START();
  return R_9_6;
}
{ /*vcast_internal_end*/

  byte result;
  byte err;
  word Data16;
  EEPROM_TAddress_ SecAddr;             

  if(((dword)Addr < (dword)((EEPROM_TAddress)0x00100000UL)) || ((dword)Addr > (dword)((EEPROM_TAddress)0x001003FFUL))) {  
    result = 2U;                 
  } else if(_FSTAT . Bits . CCIF == (byte)0U) {              
    result = 8U;                  
  } else {
    SecAddr = (EEPROM_TAddress_)((dword)Addr & 0x00FFFFFEUL);  
    if (*SecAddr == 0xFFFFU) {  
      if ((((dword)Addr) & (dword)1U) != (dword)0U) {         
        result = WriteWord(SecAddr, ((*SecAddr) & 0xFF00U) | Data);
      } else {
         
        word tempWord = *Addr;
        byte nextByte = (byte)(tempWord & 0xFFU);
        result = WriteWord((EEPROM_TAddress_)Addr, ((word)Data << 8) | nextByte);  
      }
    } else {                            
      SecAddr = (EEPROM_TAddress_)((dword)Addr & 0x00FFFFFCUL);  
      BackupSector(SecAddr, 0U, 0x04U);  
      Data16 = BackupArray[(((dword)Addr) % (dword)0x04U) / (dword)2U];  
      if ((((dword)Addr) & (dword)1U) != (dword)0U) {         
        Data16 = (Data16 & 0xFF00U) | Data;
      } else {
        Data16 = ((word)Data << 8) | (Data16 & 0xFFU);
      }
      BackupArray[(((dword)Addr) % (dword)0x04U) / (dword)2U] = Data16;  
      err = EraseSectorInternal(Addr);  
      if(err != (byte)0U) {
        result = err;                   
      } else {
        err = WriteBlock(SecAddr, 0U, 0x04U,BackupArray);  
        result = err;
      }
    }
  }
  return result;                        
} /*vcast_internal_start*/}/*vcast_internal_end*/





















 
byte EEPROM_GetByte(EEPROM_TAddress_Const Addr, byte *Data)
{ /*vcast_internal_start*/
extern unsigned  *P_9_7_1;
extern unsigned char  *P_9_7_2;
extern unsigned char  R_9_7;
extern unsigned char SBF_9_7;
if(SBF_9_7) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_2914114624
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_2914114624
  if ( vcast_is_in_driver ) {
    P_9_7_1 = Addr;
    P_9_7_2 = Data;
    vCAST_COMMON_STUB_PROC_9( 9, 7, 3, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_2914114624
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_2914114624
  vCAST_USER_CODE_TIMER_START();
  return R_9_7;
}
{ /*vcast_internal_end*/

  byte result = 0U;
  
  if(((dword)Addr < (dword)((EEPROM_TAddress)0x00100000UL)) || ((dword)Addr > (dword)((EEPROM_TAddress)0x001003FFUL))) {  
    result = 2U;                 
  } else if(_FSTAT . Bits . CCIF == (byte)0U) {              
    result = 8U;                  
  } else {
     
    if ((((dword)Addr) & (dword)1U) != (dword)0U) {
       
      EEPROM_TAddress_ alignedAddr = (EEPROM_TAddress_)((dword)Addr & 0xFFFFFFFEUL);
      word tempWord = *alignedAddr;
      *Data = (byte)(tempWord & 0xFFU);   
    } else {
       
      word tempWord = *Addr;
      *Data = (byte)((tempWord >> 8) & 0xFFU);   
    }
  }
  return result;                        
} /*vcast_internal_start*/}/*vcast_internal_end*/












 
void EEPROM_Init(void)
{ /*vcast_internal_start*/
extern unsigned char SBF_9_8;
if(SBF_9_8) {
  vCAST_USER_CODE_TIMER_STOP();
#define BEGINNING_OF_STUB_USER_CODE_9_765373702
#include "vcast_configure_stub.c"
#undef BEGINNING_OF_STUB_USER_CODE_9_765373702
  if ( vcast_is_in_driver ) {
    vCAST_COMMON_STUB_PROC_9( 9, 8, 1, 0 );
  } /* vcast_is_in_driver */
#define END_OF_STUB_USER_CODE_9_765373702
#include "vcast_configure_stub.c"
#undef END_OF_STUB_USER_CODE_9_765373702
  vCAST_USER_CODE_TIMER_START();
  return;
}
{ /*vcast_internal_end*/

  _FCLKDIV . Byte = 0x1DU;                      
} /*vcast_internal_start*/}/*vcast_internal_end*/


 

 



 







 
# 6 "vcast_preprocess.15656.1008.c"

 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
 /*vcast_internal_start*//*vcast_internal_end*/
typedef int VECTORCAST_MARKER__UNIT_APPENDIX_START;

typedef int VECTORCAST_MARKER__UNIT_APPENDIX_END;
# 2 "vcast_preprocess.15656.1010.c"
