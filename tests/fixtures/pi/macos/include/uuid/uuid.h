#ifndef AGENTCFG_TEST_UUID_H
#define AGENTCFG_TEST_UUID_H
#include <time.h>
typedef unsigned char uuid_t[16];
typedef char uuid_string_t[37];
void uuid_unparse_lower(const uuid_t, uuid_string_t);
int gethostuuid(uuid_t, const struct timespec *);
#endif
