#ifndef AGENTCFG_TEST_LIBPROC_H
#define AGENTCFG_TEST_LIBPROC_H
#include <sys/types.h>
#include <stdint.h>
#include <mach/message.h>
#define PROC_PIDTBSDINFO 3
struct proc_bsdinfo {
  uint32_t pbi_pid, pbi_ppid, pbi_pgid;
  uid_t pbi_uid;
  uint64_t pbi_start_tvsec, pbi_start_tvusec;
};
int proc_pidinfo(int, int, uint64_t, void *, int);
int proc_listallpids(void *, int);
int proc_listpgrppids(pid_t, void *, int);
#endif
