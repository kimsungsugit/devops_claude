#pragma once
#ifndef __not_in_flash_func
#define __not_in_flash_func(x) x
#endif
#ifndef __packed
#define __packed __attribute__((packed))
#endif
#ifndef weak
#define weak __attribute__((weak))
#endif
#ifndef __unused
#define __unused __attribute__((unused))
#endif
