/***********************************************
 *      VectorCAST Test Harness Component      *
 *     Copyright 2025 Vector Informatik, GmbH.    *
 *              25.sp4 (08/19/25)              *
 ***********************************************/
/*
---------------------------------------------
-- Copyright 2020 Vector Informatik, GmbH. --
---------------------------------------------
*/
#ifndef __VCAST_BASICS_H__
#define __VCAST_BASICS_H__

#include "vcast_env_defines.h"

#ifdef __cplusplus
extern "C" {
#endif

#if defined(VCAST_KEIL) && !defined(VCAST_USE_CHAR_FOR_BOOL)
#define vCAST_boolean bit 	 
#else 	 
typedef char vCAST_boolean;
#endif

#define vCAST_array_boolean char
#define vCAST_false 0
#define vCAST_true 1

void vCAST_APPEND_HISTORY_FLAG (char flag);
void vCAST_READ_COMMAND_DATA_FOR_ONE_PARAM (int vcUnit, int vcSub, int vcParam);
void vCAST_READ_COMMAND_DATA_FOR_USER_GLOBALS(void);
void vCAST_READ_COMMAND_DATA ( int, int, int, vCAST_boolean, vCAST_boolean );

void vCAST_SET_HISTORY_FLAGS ( int VC_U, int VC_S);
void vCAST_SET_HISTORY (int VC_U, int VC_S);
void vCAST_CHECK_ROBJECT( void* vcastRobject, int vcastCombinedID );

#ifdef VCAST_ENABLE_TIMER_USER_CODE
void vCAST_USER_CODE_TIMER_START (void);
void vCAST_USER_CODE_TIMER_STOP (void);
#else
#define vCAST_USER_CODE_TIMER_START()
#define vCAST_USER_CODE_TIMER_STOP()
#endif

#if !defined(VCAST_NO_STDLIB) && !defined(VCAST_NO_MALLOC)
#ifdef VCAST_FREE_HARNESS_DATA
void VCAST_Free_Allocated_Data(void);
#endif
#endif

void vCAST_UC_WRITE_EXPECTED (const char *vcast_param, const char *vcast_name, int vcast_match, const char *vcast_actual);

int VCAST_test_name_cmp(const char *vcast_tn);
#define vcast_test_name_equals(tst) (!VCAST_test_name_cmp(tst))

extern vCAST_boolean vCAST_TOOL_ERROR;
#ifdef VCAST_CPP_ENVIRONMENT
#ifndef VCAST_KEIL
extern int vcast_exception_index;
extern int vcast_should_throw_exception;
#endif
#endif

extern vCAST_boolean vcast_is_in_driver;
extern vCAST_boolean vcastIsCodeBasedTest;
extern vCAST_boolean vcastInsertCBTevent;


extern int    vCAST_CURRENT_SLOT;
extern int    vCAST_CURRENT_ITERATION;

extern vCAST_boolean vCAST_FULL_STRINGS;  /* use full strings or not */

void *VCAST_memcpy ( void *vcast_dest, const void *vcast_source, int vcast_vc_n );
void  VCAST_strncpy ( char *VC_S, char *VC_T, int VC_N );

/* BEGIN FLOATING POINT SUPPORT */
#define VCAST_FLOAT_FORMAT_SIZE 8

/* ifdef VCAST_NO_FLOAT */
#ifdef VCAST_NO_FLOAT
#define VCAST_FLOAT_ZERO  0
#define VCAST_FLOAT_ONE   1
#define VCAST_FLOAT_TWO   2
#define VCAST_FLOAT_TEN  10
#else
#define VCAST_FLOAT_ZERO  0.0
#define VCAST_FLOAT_ONE   1.0
#define VCAST_FLOAT_TWO   2.0
#define VCAST_FLOAT_TEN  10.0
#endif
/* endif VCAST_NO_FLOAT */

/* types */
/* ifdef VCAST_NO_FLOAT */
#ifdef VCAST_NO_FLOAT
typedef long vCAST_double;
typedef long vCAST_long_double;
/* else */
#else
typedef double vCAST_double;
#if defined(VCAST_HAS_FLOAT128)
typedef __float128 vCAST_long_double;
#else
/* ifdef VCAST_ALLOW_LONG_DOUBLE */
#if defined(VCAST_ALLOW_LONG_DOUBLE) || !defined(VCAST_NO_LONG_DOUBLE)
typedef long double vCAST_long_double;
#else
typedef double vCAST_long_double;
#endif
/* endif VCAST_ALLOW_LONG_DOUBLE */
#endif
/* endif defined(VCAST_HAS_FLOAT128) */
#endif
/* endif VCAST_NO_FLOAT */

/* objects */
/* ifndef VCAST_NOFLOAT */
#ifndef VCAST_NO_FLOAT
/*******************/
/* harness options */
/*******************/
/* default values */
extern char VCAST_DEFAULT_FLOAT_FORMAT[];
extern int  VCAST_DEFAULT_FLOAT_PRECISION;
extern int  VCAST_DEFAULT_FLOAT_FIELD_WIDTH;
/* actual values */
extern int  VCAST_FLOAT_PRECISION;
extern int  VCAST_FLOAT_FIELD_WIDTH;
extern char VCAST_FLOAT_FORMAT[];
/* floating point special-case constants */
extern vCAST_long_double VCAST_globalZero;
vCAST_long_double VCAST_GET_QUIET_NAN(void);
vCAST_long_double VCAST_GET_NEGATIVE_INFINITY(void);
vCAST_long_double VCAST_GET_POSITIVE_INFINITY(void);
#endif
/* endif VCAST_NO_FLOAT */

/* functions */
void vectorcast_float_to_string( char *vcast_mixed_str, vCAST_long_double vcast_f );

/* END FLOATING POINT SUPPORT */

#ifdef __cplusplus
}
#endif

#ifndef VCAST_NULL
#ifdef __cplusplus
#define VCAST_NULL (0)
#else
#define VCAST_NULL ((void*)0)
#endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

#ifdef VCAST_HAS_LONGLONG
#ifdef VCAST_MICROSOFT_LONG_LONG
#define VCAST_LONGEST_INT __int64
#define VCAST_LONGEST_UNSIGNED unsigned __int64
#else
#define VCAST_LONGEST_INT long long
#define VCAST_LONGEST_UNSIGNED unsigned long long
#endif
#else
#define VCAST_LONGEST_INT long
#define VCAST_LONGEST_UNSIGNED unsigned long
#endif

#ifndef VCAST_UNSIGNED_CONVERSION_TYPE
#define VCAST_UNSIGNED_CONVERSION_TYPE unsigned VCAST_LONGEST_INT
#endif
#ifndef VCAST_SIGNED_CONVERSION_TYPE
#define VCAST_SIGNED_CONVERSION_TYPE VCAST_LONGEST_INT
#endif

VCAST_LONGEST_INT vcast_abs ( VCAST_LONGEST_INT vcNum );
void vectorcast_signed_to_string ( char vcDest[], VCAST_LONGEST_INT vcSrc );
int VCAST_special_compare ( char *vcDouble1, char *vcDouble2, int vcLen );
void vectorcast_strcpy ( char *VC_S, const char *VC_T );
void vectorcast_float_to_string( char *mixed_str, vCAST_long_double vcast_f );

#define VCAST_PROBE_PRINT_AVAILABLE

void vcast_probe_print (const char *S);
void vcast_probe_print_int (VCAST_SIGNED_CONVERSION_TYPE i);
void vcast_probe_print_unsigned (VCAST_UNSIGNED_CONVERSION_TYPE i);
void vcast_probe_print_float (vCAST_long_double vcast_f);
void vcast_probe_assert (const char *msg, int condition);

#ifdef VCAST_DISABLE_UC_WRITE_EXPECTED
#define vcast_probe_event(x)
#else
void vcast_probe_event (const char *msg);
#endif

#define vcast_probe_verbose()

void vcast_vunit_test_case_event(const char *test_suite,
                                 const char *test_case);
void vcast_vunit_assert_event(int result, const char *expr, const char *lhs,
                              const char *rhs, const char *file, int line);

int VCAST_COUPLING_INSTRUMENTATION_POINT (int vc_probeIndex);
void vcastDumpCouplingData (void);
void vcastCouplingDataInit (void);
int vcastControlCoupleTargetCall (int vc_probeIndex);
int vcastControlCoupleFptrCall (int probeIndex, void *fnCall, void *fnTarget);
int vcastControlCoupleVrtlCall (int vc_probeIndex);

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus

#ifdef VCAST_HARNESS_NEEDS_ADDRESSOF
namespace vcast {
template <typename T>
T* addressof(T& obj){
  return reinterpret_cast<T*>(
    &const_cast<char&>(reinterpret_cast<const volatile char&>(obj))
  );
}
}
#endif

#if defined(VCAST_HARNESS_NEEDS_VCAST_MOVE) || defined(VCAST_HARNESS_NEEDS_VCAST_FORWARD)

namespace vcast {
#ifndef VCAST_REMOVE_REFERENCE
#define VCAST_REMOVE_REFERENCE
  template <class T> struct remove_reference      { typedef T type; };
  template <class T> struct remove_reference<T&>  { typedef T type; };
  template <class T> struct remove_reference<T&&> { typedef T type; };
#endif

#ifdef VCAST_HARNESS_NEEDS_VCAST_FORWARD

  template <class T>
  inline
#if __cplusplus >= 201402L
  constexpr
#endif /* C++14 */
  T && forward(typename ::vcast::remove_reference<T>::type & arg) noexcept
  { return (static_cast<T&&>(arg)); }

  template <class T>
  inline
#if __cplusplus >= 201402L
  constexpr
#endif /* C++14 */
  T && forward(typename ::vcast::remove_reference<T>::type && arg) noexcept
  { return (static_cast<T&&>(arg)); }

#endif /* VCAST_HARNESS_NEEDS_VCAST_FORWARD */

#ifdef VCAST_HARNESS_NEEDS_VCAST_MOVE

  template <class T>
  inline
#if __cplusplus >= 201402L
  constexpr
#endif /* C++14 */
  typename ::vcast::remove_reference<T>::type && move(T&& t) noexcept
  { return static_cast<typename ::vcast::remove_reference<T>::type &&>(t); }

#endif /* VCAST_HARNESS_NEEDS_VCAST_MOVE */
}
#endif /* __cplusplus */

#endif /* defined(VCAST_HARNESS_NEEDS_VCAST_MOVE) || defined(VCAST_HARNESS_NEEDS_VCAST_FORWARD) */

#endif /* __VCAST_BASICS_H__ */
