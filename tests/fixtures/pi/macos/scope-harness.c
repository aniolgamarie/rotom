/* 只执行纯清点/身份信号逻辑；任何真实 fork/kill/socket 都使测试立即失败。 */
#include <assert.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <unistd.h>
int getdtablesize(void);
int getpeereid(int, uid_t *, gid_t *);
static pid_t forbidden_fork(void) { abort(); }
static int forbidden_kill(pid_t pid, int number) { (void)pid; (void)number; abort(); }
static int forbidden_socket(int domain, int type, int protocol) { (void)domain; (void)type; (void)protocol; abort(); }
#define fork forbidden_fork
#define kill forbidden_kill
#define socket forbidden_socket
#define main supervisor_entry_not_called
#include "../../../../scripts/pi-supervisor-macos.c"
#undef main

static struct scope_process fixture[8];
static int fixture_count, reads, mutate_at, signals;
static unsigned int signaled[8];
int proc_listallpids(void *buffer, int bytes) {
  if (!buffer) return fixture_count;
  assert(bytes >= fixture_count * (int)sizeof(pid_t));
  for (int i = 0; i < fixture_count; i++) ((pid_t *)buffer)[i] = fixture[i].pid;
  return fixture_count;
}
int proc_pidinfo(int pid, int flavor, uint64_t argument, void *buffer, int bytes) {
  (void)argument;
  assert(flavor == 17 && bytes == 56);
  for (int i = 0; i < fixture_count; i++) if (fixture[i].pid == pid) {
    struct unique_info value = fixture[i].unique;
    if (++reads == mutate_at) value.exec_version++;
    memcpy(buffer, &value, sizeof(value));
    return sizeof(value);
  }
  errno = ESRCH; return 0;
}
int proc_listpgrppids(pid_t pid, void *buffer, int size) { (void)pid; (void)buffer; (void)size; abort(); }
int sysctlbyname(const char *name, void *out, size_t *size, void *in, size_t length) {
  (void)name; (void)out; (void)size; (void)in; (void)length; abort();
}
int gethostuuid(uuid_t value, const struct timespec *timeout) { (void)value; (void)timeout; abort(); }
void uuid_unparse_lower(const uuid_t value, uuid_string_t out) { (void)value; (void)out; abort(); }
int getpeereid(int fd, uid_t *uid, gid_t *gid) { (void)fd; (void)uid; (void)gid; abort(); }
static int fake_signal(audit_token_t *token, int number) {
  assert(number == SIGTERM);
  assert(token->val[5] == 100 || token->val[5] == 200);
  assert(token->val[7] == (token->val[5] == 100 ? 9u : 10u));
  signaled[signals++] = token->val[5];
  return 0;
}
static void reset(void) {
  memset(fixture, 0, sizeof(fixture));
  fixture[0] = (struct scope_process){.pid = 100, .unique = {.birth = 1000, .parent_birth = 10, .exec_version = 9}};
  fixture[1] = (struct scope_process){.pid = 200, .unique = {.birth = 1001, .parent_birth = 1000, .exec_version = 10}};
  fixture_count = 2; reads = 0; mutate_at = -1; signals = 0;
  owned_history_count = 0;
  assert(remember_owned(1000));
  signal_by_token = fake_signal;
}
int main(void) {
  struct scope_process *owned;
  int count, uncertain;
  reset();
  assert(take_scope(1000, 100, &owned, &count, &uncertain) && count == 2 && !uncertain); free(owned);
  fixture[2] = (struct scope_process){.pid = 300, .unique = {.birth = 1002, .parent_birth = 1001}};
  fixture_count = 3;
  assert(take_scope(1000, 100, &owned, &count, &uncertain) && count == 3 && !uncertain); free(owned);
  fixture[1] = fixture[2]; fixture_count = 2;
  assert(take_scope(1000, 100, &owned, &count, &uncertain) && count == 2 && !uncertain); free(owned);
  fixture[2] = (struct scope_process){.pid = 400, .unique = {.birth = 2001, .parent_birth = 1999}};
  fixture_count = 3;
  assert(take_scope(1000, 100, &owned, &count, &uncertain) && uncertain); free(owned);
  fixture[2].unique.parent_birth = 99;
  assert(take_scope(1000, 100, &owned, &count, &uncertain) && !uncertain && count == 2); free(owned);
  reset(); mutate_at = 4;
  assert(!take_scope(1000, 100, &owned, &count, &uncertain));
  reset();
  assert(signal_scope(1000, 100, SIGTERM) && signals == 2);
  reset(); mutate_at = 5;
  assert(!signal_scope(1000, 100, SIGTERM) && signals == 1 && signaled[0] == 100);
  puts("macOS helper mock scope tests passed; no native libproc, agent host or signal invoked");
  return 0;
}
