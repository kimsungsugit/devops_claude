
/********************/
void vCAST_VALUE_USER_CODE_9 (
         int vcast_slot_index ) {
      /* BEGIN VALUE_USER_CODE_9 */
      /* BEGIN C-000154.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.002" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x00100300UL );

      }
         } /* SwUFn_2101.002 */
      /* END C-000154.DAT */
      /* BEGIN C-000155.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.003" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003FFUL );

      }
         } /* SwUFn_2101.003 */
      /* END C-000155.DAT */
      /* BEGIN C-000156.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.004" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003F0UL );

      }
         } /* SwUFn_2101.004 */
      /* END C-000156.DAT */
      /* BEGIN C-000160.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.008" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x00100300UL );

      }
         } /* SwUFn_2101.008 */
      /* END C-000160.DAT */
      /* BEGIN C-000161.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.009" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003FFUL );

      }
         } /* SwUFn_2101.009 */
      /* END C-000161.DAT */
      /* BEGIN C-000162.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.010" ) == 0 ) ) {
      {
          P_9_6_1 = ( (word *)0x001003F0UL );

      }
         } /* SwUFn_2101.010 */
      /* END C-000162.DAT */
      /* BEGIN C-000149.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.008" ) == 0 ) ) {
      {
          _FSTAT.Bits.CCIF = ( 1 );

      }
      {
          P_9_7_1 = ( (word *)0x001003F0UL );

      }
         } /* SwUFn_2102.008 */
      /* END C-000149.DAT */
      /* BEGIN C-000150.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.009" ) == 0 ) ) {
      {
          P_9_7_1 = ( (word *)0x001003F0UL );

      }
         } /* SwUFn_2102.009 */
      /* END C-000150.DAT */
      /* BEGIN C-000151.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.010" ) == 0 ) ) {
      {
          _FSTAT.Bits.CCIF = ( 1 );

      }
      {
          P_9_7_1 = ( (word *)0x001003F1UL );

      }
         } /* SwUFn_2102.010 */
      /* END C-000151.DAT */
      /* DONE VALUE_USER_CODE_9 */
}

/********************/
void vCAST_EXPECTED_USER_CODE_9 (
         int vcast_slot_index ) {
      /* BEGIN EXPECTED_USER_CODE_9 */
/* DONE EXPECTED_USER_CODE_9 */
}

/********************/
void vCAST_EGLOBALS_USER_CODE_9 (
         int vcast_slot_index ) {
      /* BEGIN EXPECTED_GLOBALS_USER_CODE_9 */
/* DONE EXPECTED_GLOBALS_USER_CODE_9 */
}

/********************/
void vCAST_STUB_PROCESSING_9 (
         int UnitIndex,
         int SubprogramIndex ) {
    vCAST_GLOBAL_STUB_PROCESSING();
      /* BEGIN STUB_VAL_USER_CODE_9 */
      /* BEGIN C-000186.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 2 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2105.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  3)) {
          /* UnitName == "EEPROM" && SubprogramName == "SetupFCCOB"*/
          word *temp = P_9_3_5;
*temp = 3;
        }
         } /* SwUFn_2105.008 */
      /* END C-000186.DAT */
      /* BEGIN C-000154.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.002" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x00100300UL );
        }
         } /* SwUFn_2101.002 */
      /* END C-000154.DAT */
      /* BEGIN C-000155.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.003" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x001003FFUL );
        }
         } /* SwUFn_2101.003 */
      /* END C-000155.DAT */
      /* BEGIN C-000156.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.004" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x001003F0UL );
        }
         } /* SwUFn_2101.004 */
      /* END C-000156.DAT */
      /* BEGIN C-000160.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x00100300UL );
        }
         } /* SwUFn_2101.008 */
      /* END C-000160.DAT */
      /* BEGIN C-000161.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.009" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x001003FFUL );
        }
         } /* SwUFn_2101.009 */
      /* END C-000161.DAT */
      /* BEGIN C-000162.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 6 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2101.010" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  6)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_SetByte"*/
          P_9_6_1 = ( (word *)0x001003F0UL );
        }
         } /* SwUFn_2101.010 */
      /* END C-000162.DAT */
      /* BEGIN C-000149.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.008" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex == -1)) {
          /* UnitName == "EEPROM" && SubprogramName == ""*/
          _FSTAT.Bits.CCIF = ( 1 );
        }
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_GetByte"*/
          P_9_7_1 = ( (word *)0x001003F0UL );
        }
         } /* SwUFn_2102.008 */
      /* END C-000149.DAT */
      /* BEGIN C-000150.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.009" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_GetByte"*/
          P_9_7_1 = ( (word *)0x001003F0UL );
        }
         } /* SwUFn_2102.009 */
      /* END C-000150.DAT */
      /* BEGIN C-000151.DAT */
if ( ( vCAST_UNIT ==  9 ) &&
     ( vCAST_SUBPROGRAM == 7 ) &&
     ( VCAST_test_name_cmp ( "SwUFn_2102.010" ) == 0 ) ) {
      if ((UnitIndex ==  9) && (SubprogramIndex == -1)) {
          /* UnitName == "EEPROM" && SubprogramName == ""*/
          _FSTAT.Bits.CCIF = ( 1 );
        }
      if ((UnitIndex ==  9) && (SubprogramIndex ==  7)) {
          /* UnitName == "EEPROM" && SubprogramName == "EEPROM_GetByte"*/
          P_9_7_1 = ( (word *)0x001003F1UL );
        }
         } /* SwUFn_2102.010 */
      /* END C-000151.DAT */
      /* DONE STUB_VAL_USER_CODE_9 */
}

/********************/
void vCAST_BEGIN_STUB_PROC_9 (
         int UnitIndex,
         int SubprogramIndex ) {
    vCAST_GLOBAL_BEGINNING_OF_STUB_PROCESSING();
      /* BEGIN STUB_EXP_USER_CODE_9 */
/* DONE STUB_EXP_USER_CODE_9 */
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
   } /* switch( uct ) */
}
