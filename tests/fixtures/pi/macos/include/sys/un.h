#ifndef AGENTCFG_TEST_UN_H
#define AGENTCFG_TEST_UN_H
struct sockaddr_un { unsigned char sun_len; unsigned char sun_family; char sun_path[104]; };
#endif
