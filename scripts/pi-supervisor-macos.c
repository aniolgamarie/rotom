/* macOS 身份 helper。受管启动使用独立父 helper 持有未回收 child，防止停止时 PID 复用。
 * libproc 字段依据 Apple xnu 的 proc_info.h；真实 SDK/clang 身份在 native 验收记录。
 */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <sys/ioctl.h>
#include <dlfcn.h>
#include <libproc.h>
#include <uuid/uuid.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int info(pid_t pid, struct proc_bsdinfo *value) {
  memset(value, 0, sizeof(*value));
  return proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, value, sizeof(*value)) == (int)sizeof(*value);
}

static void identity(FILE *out, const struct proc_bsdinfo *value) {
  struct timeval boot = {0};
  size_t length = sizeof(boot);
  uuid_t host;
  uuid_string_t host_text;
  struct timespec timeout = {1, 0};
  if (sysctlbyname("kern.boottime", &boot, &length, NULL, 0) != 0 || gethostuuid(host, &timeout) != 0) exit(5);
  uuid_unparse_lower(host, host_text);
  fprintf(out, "{\"platform\":\"darwin\",\"boot_id\":\"%s:%lld:%d\",\"pid\":%u,\"ppid\":%u,\"pgid\":%u,\"uid\":%u,\"namespace\":null,\"start_time\":\"%" PRIu64 ".%06" PRIu64 "\"}",
    host_text, (long long)boot.tv_sec, (int)boot.tv_usec, value->pbi_pid, value->pbi_ppid, value->pbi_pgid,
    value->pbi_uid, value->pbi_start_tvsec, value->pbi_start_tvusec);
}

static int positive(const char *text) {
  char *end = NULL;
  long value = strtol(text, &end, 10);
  return end && *end == '\0' && value > 0 && value <= 2147483647 ? (int)value : -1;
}

static int secure_nonce(const char *received, const char *expected) {
  if (strlen(received) != 64) return 0;
  unsigned char different = 0;
  for (int index = 0; index < 64; index++) different |= (unsigned char)(received[index] ^ expected[index]);
  return different == 0;
}

static void json_string(FILE *out, const char *value) {
  fputc('"', out);
  for (const unsigned char *p = (const unsigned char *)value; *p; p++) {
    if (*p == '"' || *p == '\\') { fputc('\\', out); fputc(*p, out); }
    else if (*p < 32) fprintf(out, "\\u%04x", *p);
    else fputc(*p, out);
  }
  fputc('"', out);
}

static int receipt(const char *path, const char *nonce, const struct proc_bsdinfo *worker, const char *state, int code, unsigned long generation) {
  char temporary[2048];
  if (snprintf(temporary, sizeof(temporary), "%s.%d.tmp", path, getpid()) >= (int)sizeof(temporary)) return 0;
  int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) return 0;
  FILE *out = fdopen(fd, "w");
  if (!out) { close(fd); unlink(temporary); return 0; }
  fprintf(out, "{\"schema_version\":1,\"nonce\":\"%s\",\"state\":\"%s\",\"exit_code\":%d,\"grant_generation\":%lu,\"worker\":", nonce, state, code, generation);
  identity(out, worker);
  fputs("}\n", out);
  int ok = fflush(out) == 0 && fsync(fd) == 0;
  fclose(out);
  if (!ok || rename(temporary, path) != 0) { unlink(temporary); return 0; }
  char parent[2048];
  if (strlen(path) >= sizeof(parent)) return 0;
  strcpy(parent, path);
  char *slash = strrchr(parent, '/');
  if (!slash) return 0;
  *slash = '\0';
  fd = open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  if (fd < 0) return 0;
  ok = fsync(fd) == 0;
  close(fd);
  return ok;
}

/* 固定 libproc ABI：出生身份跨 exec 不变，原父出生身份跨 reparent 不变。
 * 私有能力缺失或返回尺寸不同即拒绝，绝不退回仅凭 PID 的停止。
 */
struct unique_info {
  unsigned char image[16];
  uint64_t birth, parent_birth;
  int32_t exec_version, parent_exec_version;
  uint64_t reserved[2];
};
_Static_assert(sizeof(struct unique_info) == 56, "libproc unique identity ABI");
struct scope_process { pid_t pid; struct unique_info unique; };
#define SCOPE_LIMIT 65536
static uint64_t owned_history[SCOPE_LIMIT];
static size_t owned_history_count;
static int (*signal_by_token)(audit_token_t *, int);

static int unique_identity(pid_t pid, struct unique_info *value) {
  memset(value, 0, sizeof(*value));
  return proc_pidinfo(pid, 17, 1, value, sizeof(*value)) == (int)sizeof(*value) && value->birth > 0;
}
static int known_owned(uint64_t birth) {
  for (size_t index = 0; index < owned_history_count; index++) if (owned_history[index] == birth) return 1;
  return 0;
}
static int remember_owned(uint64_t birth) {
  if (known_owned(birth)) return 1;
  if (owned_history_count >= SCOPE_LIMIT) return 0;
  owned_history[owned_history_count++] = birth;
  return 1;
}
static int compare_pid(const void *left, const void *right) {
  pid_t a = *(const pid_t *)left, b = *(const pid_t *)right;
  return (a > b) - (a < b);
}
static int take_scope(uint64_t root_birth, pid_t root_pid, struct scope_process **owned, int *owned_count, int *uncertain) {
  int capacity = proc_listallpids(NULL, 0);
  *owned = NULL; *owned_count = 0; *uncertain = 1;
  if (capacity < 1 || capacity > SCOPE_LIMIT - 256) return 0;
  capacity += 256;
  pid_t *first = calloc((size_t)capacity, sizeof(pid_t)), *second = calloc((size_t)capacity, sizeof(pid_t));
  struct scope_process *all = calloc((size_t)capacity, sizeof(*all)), *result = calloc((size_t)capacity, sizeof(*result));
  if (!first || !second || !all || !result) { free(first); free(second); free(all); free(result); return 0; }
  int count = proc_listallpids(first, capacity * (int)sizeof(pid_t));
  int good = count > 0 && count < capacity, root_seen = 0;
  if (good) qsort(first, (size_t)count, sizeof(pid_t), compare_pid);
  for (int index = 0; good && index < count; index++) {
    all[index].pid = first[index];
    if (first[index] <= 0) continue;
    if (!unique_identity(first[index], &all[index].unique)) good = 0;
    if (first[index] == root_pid && all[index].unique.birth == root_birth) root_seen = 1;
  }
  int count_again = proc_listallpids(second, capacity * (int)sizeof(pid_t));
  if (count_again != count || !root_seen) good = 0;
  if (good) {
    qsort(second, (size_t)count_again, sizeof(pid_t), compare_pid);
    if (memcmp(first, second, (size_t)count * sizeof(pid_t))) good = 0;
  }
  for (int index = 0; good && index < count; index++) {
    if (first[index] <= 0) continue;
    struct unique_info current;
    if (!unique_identity(first[index], &current) || current.birth != all[index].unique.birth
        || current.parent_birth != all[index].unique.parent_birth || current.exec_version != all[index].unique.exec_version) good = 0;
  }
  if (good) {
    *uncertain = 0;
    for (int index = 0; index < count; index++) {
      if (all[index].pid <= 0 || all[index].unique.birth < root_birth) continue;
      uint64_t cursor = all[index].unique.birth;
      int belongs = 0;
      for (int depth = 0; depth <= count; depth++) {
        if (cursor == root_birth || known_owned(cursor)) { belongs = 1; break; }
        if (cursor < root_birth) break;
        int found = -1;
        for (int candidate = 0; candidate < count; candidate++) if (all[candidate].unique.birth == cursor) { found = candidate; break; }
        if (found < 0 || all[found].unique.parent_birth >= cursor) { *uncertain = 1; break; }
        cursor = all[found].unique.parent_birth;
        if (depth == count) *uncertain = 1;
      }
      if (belongs) {
        if (!remember_owned(all[index].unique.birth)) { *uncertain = 1; continue; }
        result[(*owned_count)++] = all[index];
      }
    }
    *owned = result;
  } else free(result);
  free(first); free(second); free(all);
  return good;
}
static int signal_scope(uint64_t root_birth, pid_t root_pid, int number) {
  struct scope_process *owned = NULL;
  int count = 0, uncertain;
  if (!signal_by_token || !take_scope(root_birth, root_pid, &owned, &count, &uncertain)) return 0;
  int good = 1;
  for (int index = count - 1; index >= 0; index--) {
    struct unique_info current;
    if (!unique_identity(owned[index].pid, &current)) continue;
    if (current.birth != owned[index].unique.birth || current.exec_version != owned[index].unique.exec_version) { good = 0; continue; }
    audit_token_t token = {{0}};
    token.val[5] = (unsigned int)owned[index].pid;
    token.val[7] = (unsigned int)current.exec_version;
    if (signal_by_token(&token, number) != 0 && errno != ESRCH) good = 0;
  }
  free(owned);
  return good;
}

static int supervise(int argc, char **argv) {
  if (argc < 8 || strcmp(argv[6], "--") || argv[7][0] != '/') return 2;
  const char *socket_path = argv[2];
  int nonce_fd = positive(argv[3]), status_fd = positive(argv[4]), admission_fd = positive(argv[5]);
  char nonce[66] = {0}, terminal_path[2048], parent[2048];
  if (nonce_fd < 3 || status_fd < 3 || admission_fd < 3 || nonce_fd == status_fd || nonce_fd == admission_fd || status_fd == admission_fd) return 2;
  struct stat nonce_pipe, status_pipe, admission_pipe;
  if (fstat(nonce_fd, &nonce_pipe) || fstat(status_fd, &status_pipe) || fstat(admission_fd, &admission_pipe)
      || !S_ISFIFO(nonce_pipe.st_mode) || !S_ISFIFO(status_pipe.st_mode) || !S_ISFIFO(admission_pipe.st_mode)
      || nonce_pipe.st_uid != geteuid() || status_pipe.st_uid != geteuid() || admission_pipe.st_uid != geteuid()) return 4;
  if (strlen(socket_path) >= sizeof(parent)) return 2;
  strcpy(parent, socket_path);
  char *slash = strrchr(parent, '/');
  if (!slash || slash == parent) return 2;
  const char *socket_name = strrchr(socket_path, '/') + 1;
  if (!*socket_name || strlen(socket_name) >= sizeof(((struct sockaddr_un *)0)->sun_path)) return 2;
  *slash = '\0';
  struct stat directory, existing;
  if (lstat(parent, &directory) || !S_ISDIR(directory.st_mode) || directory.st_uid != geteuid() || (directory.st_mode & 0777) != 0700) return 4;
  if (lstat(socket_path, &existing) == 0 || errno != ENOENT) return 4;
  ssize_t count = read(nonce_fd, nonce, 65);
  close(nonce_fd);
  if (count != 65 || nonce[64] != '\n') return 2;
  nonce[64] = '\0';
  for (int i = 0; i < 64; i++) if (!((nonce[i] >= '0' && nonce[i] <= '9') || (nonce[i] >= 'a' && nonce[i] <= 'f'))) return 2;
  if (snprintf(terminal_path, sizeof(terminal_path), "%s.receipt.json", socket_path) >= (int)sizeof(terminal_path)) return 2;
  if (lstat(terminal_path, &existing) == 0 || errno != ENOENT) return 4;
  umask(0077);
  const char *tty_setting = getenv("AGENTCFG_EXECUTION_TTY");
  int tty_mode = tty_setting && !strcmp(tty_setting, "1");
  unsetenv("AGENTCFG_EXECUTION_TTY");
  if (tty_mode && (!isatty(STDIN_FILENO) || ioctl(STDIN_FILENO, TIOCSCTTY, 0))) return 5;
  signal(SIGPIPE, SIG_IGN);
  int launch_cwd = open(".", O_RDONLY | O_DIRECTORY);
  int directory_fd = open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  struct stat pinned;
  if (launch_cwd < 0 || directory_fd < 0 || fstat(directory_fd, &pinned) || pinned.st_dev != directory.st_dev
      || pinned.st_ino != directory.st_ino || fchdir(directory_fd)) return 4;
  close(directory_fd);
  int server = socket(AF_UNIX, SOCK_STREAM, 0);
  struct sockaddr_un address = {0};
  address.sun_len = sizeof(address);
  address.sun_family = AF_UNIX;
  strcpy(address.sun_path, socket_name);
  if (server < 0 || bind(server, (struct sockaddr *)&address, sizeof(address)) || listen(server, 4)) return 6;
  struct stat socket_identity;
  if (lstat(socket_path, &socket_identity)) return 6;
  int gate[2];
  if (pipe(gate)) return 6;
  pid_t child = fork();
  if (child < 0) return 6;
  if (child == 0) {
    close(server);
    close(status_fd);
    close(admission_fd);
    close(gate[1]);
    if (setpgid(0, 0)) _exit(125);
    char admitted;
    if (read(gate[0], &admitted, 1) != 1 || admitted != 'G') _exit(125);
    if (fchdir(launch_cwd)) _exit(125);
    for (int fd = 3; fd < getdtablesize(); fd++) close(fd);
    execv(argv[7], &argv[7]);
    _exit(127);
  }
  close(launch_cwd);
  close(gate[0]);
  if (setpgid(child, child) && errno != EACCES) return 6;
  if (tty_mode && tcsetpgrp(STDIN_FILENO, child)) return 5;
  struct proc_bsdinfo worker, helper;
  if (!info(child, &worker) || !info(getpid(), &helper) || worker.pbi_pgid != (uint32_t)child) return 5;
  struct unique_info root_unique;
  signal_by_token = (int (*)(audit_token_t *, int))dlsym(RTLD_DEFAULT, "proc_signal_with_audittoken");
  if (!signal_by_token || !unique_identity(child, &root_unique) || !remember_owned(root_unique.birth)) return 5;
  FILE *status = fdopen(status_fd, "w");
  if (!status) return 6;
  if (!receipt(terminal_path, nonce, &worker, "running", -1, 1)) return 6;
  fputs("{\"schema_version\":1,\"state\":\"ready\",\"helper\":", status);
  identity(status, &helper);
  fputs(",\"worker\":", status);
  identity(status, &worker);
  fputs(",\"control_path\":", status);
  json_string(status, socket_path);
  fputs("}\n", status);
  char accepted;
  if (fflush(status) == 0 && read(admission_fd, &accepted, 1) == 1 && accepted == 'G') write(gate[1], "G", 1);
  close(admission_fd);
  close(gate[1]);
  unsigned long generation = 1;
  int unknown = 0, unknown_written = 0, stopping = 0, ticks = 0;
  for (;;) {
    siginfo_t ended;
    memset(&ended, 0, sizeof(ended));
    if (waitid(P_PID, child, &ended, WEXITED | WNOHANG | WNOWAIT) != 0) return 6;
    struct scope_process *owned = NULL;
    int count = 0, uncertain = 1;
    int stable = take_scope(root_unique.birth, child, &owned, &count, &uncertain);
    int live = 0;
    for (int index = 0; index < count; index++) if (owned[index].pid != child) live++;
    free(owned);
    unknown = !stable || uncertain;
    if (unknown && !unknown_written) {
      if (!receipt(terminal_path, nonce, &worker, "unknown", -1, generation)) return 6;
      unknown_written = 1;
    }
    /* 只有两次一致的出生身份清点且所有后代清零，才生成完整终止证明。 */
    if (ended.si_pid == child && live == 0 && !unknown) {
      int result;
      if (waitpid(child, &result, 0) != child) return 6;
      int code = WIFEXITED(result) ? WEXITSTATUS(result) : 128 + WTERMSIG(result);
      if (!receipt(terminal_path, nonce, &worker, "terminated", code, generation)) return 6;
      fputs("{\"schema_version\":1,\"state\":\"terminated\"}\n", status);
      fflush(status);
      fclose(status);
      if (lstat(socket_path, &existing) == 0 && existing.st_dev == socket_identity.st_dev && existing.st_ino == socket_identity.st_ino) unlink(socket_path);
      close(server);
      return code;
    }
    struct pollfd request = {server, POLLIN, 0};
    if (poll(&request, 1, 50) > 0 && (request.revents & POLLIN)) {
      int client = accept(server, NULL, NULL);
      uid_t uid; gid_t gid;
      char input[256] = {0}, received[65] = {0}, action[8] = {0};
      unsigned long requested = 0;
      int used = 0;
      if (client >= 0 && getpeereid(client, &uid, &gid) == 0 && uid == geteuid()) {
        struct timeval timeout = {1, 0};
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        ssize_t bytes = read(client, input, sizeof(input) - 1);
        if (bytes > 0 && sscanf(input, "%7[A-Z] %64[0-9a-f] %lu%n", action, received, &requested, &used) == 3
            && (!strcmp(action, "STOP") || !strcmp(action, "KILL") || !strcmp(action, "OWNER"))
            && !strcmp(input + used, "\n") && secure_nonce(received, nonce) && requested >= generation && requested >= 2) {
          generation = requested;
          /* 每个目标由 audit token 的 PID/version 核对，不能信号误投复用 PID。 */
          if (!strcmp(action, "OWNER")) {
            /* 只停止owner（child）：核对出生身份后按audit token发SIGKILL，
             * 不触碰作用域内worker；owner死后本helper继续服务控制通道，
             * 直到worker也被停止并取得终止收据才退出。不置stopping，
             * 不触发整体作用域升级。 */
            struct unique_info child_now;
            audit_token_t token = {{0}};
            if (unique_identity(child, &child_now) && child_now.birth == root_unique.birth) {
              token.val[5] = (unsigned int)child;
              token.val[7] = (unsigned int)child_now.exec_version;
              if (signal_by_token(&token, SIGKILL) == 0) write(client, "ACCEPTED\n", 9);
              else write(client, "REJECTED\n", 9);
            } else write(client, "REJECTED\n", 9);
          }
          else if (!strcmp(action, "KILL")) {
            if (signal_scope(root_unique.birth, child, SIGKILL)) {
              stopping = 1; ticks = 40; write(client, "ACCEPTED\n", 9);
            } else write(client, "REJECTED\n", 9);
          }
          else if (stopping) write(client, "ACCEPTED\n", 9);
          else {
            if (signal_scope(root_unique.birth, child, SIGTERM)) {
              stopping = 1;
              ticks = 0;
              write(client, "ACCEPTED\n", 9);
            } else write(client, "REJECTED\n", 9);
          }
        } else write(client, "REJECTED\n", 9);
      }
      if (client >= 0) close(client);
    }
    if (stopping && ++ticks >= 40) {
      ticks = signal_scope(root_unique.birth, child, SIGKILL) ? 0 : 39;
    }
  }
}

static int stop_control(int argc, char **argv) {
  if (argc != 5) return 2;
  int nonce_fd = positive(argv[3]), generation = positive(argv[4]);
  char parent[2048], nonce[66] = {0}, request[128], response[16] = {0};
  if (nonce_fd < 3 || generation < 2 || strlen(argv[2]) >= sizeof(parent)) return 2;
  strcpy(parent, argv[2]);
  char *slash = strrchr(parent, '/');
  if (!slash || slash == parent) return 2;
  const char *name = strrchr(argv[2], '/') + 1;
  if (!*name || strlen(name) >= sizeof(((struct sockaddr_un *)0)->sun_path)) return 2;
  *slash = '\0';
  struct stat pipe_info, directory;
  if (fstat(nonce_fd, &pipe_info) || !S_ISFIFO(pipe_info.st_mode) || pipe_info.st_uid != geteuid()) return 4;
  if (read(nonce_fd, nonce, 65) != 65 || nonce[64] != '\n') return 2;
  close(nonce_fd); nonce[64] = '\0';
  for (int i = 0; i < 64; i++) if (!((nonce[i] >= '0' && nonce[i] <= '9') || (nonce[i] >= 'a' && nonce[i] <= 'f'))) return 2;
  int directory_fd = open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
  if (directory_fd < 0 || fstat(directory_fd, &directory) || directory.st_uid != geteuid()
      || (directory.st_mode & 0777) != 0700 || fchdir(directory_fd)) return 4;
  close(directory_fd);
  int client = socket(AF_UNIX, SOCK_STREAM, 0);
  struct sockaddr_un address = {0};
  address.sun_len = sizeof(address); address.sun_family = AF_UNIX;
  strcpy(address.sun_path, name);
  if (client < 0 || connect(client, (struct sockaddr *)&address, sizeof(address))) return 4;
  uid_t uid; gid_t gid;
  if (getpeereid(client, &uid, &gid) || uid != geteuid()) return 4;
  struct timeval timeout = {3, 0};
  setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  signal(SIGPIPE, SIG_IGN);
  int length = snprintf(request, sizeof(request), "%s %s %d\n", !strcmp(argv[1], "kill-control") ? "KILL" : !strcmp(argv[1], "owner-control") ? "OWNER" : "STOP", nonce, generation);
  if (write(client, request, (size_t)length) != length) return 4;
  ssize_t count = read(client, response, sizeof(response) - 1);
  close(client);
  if (count != 9 || strcmp(response, "ACCEPTED\n")) return 4;
  puts("accepted"); return 0;
}

int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "--version")) { puts("agentcfg-macos-supervisor 1"); return 0; }
  if (argc >= 2 && !strcmp(argv[1], "supervise")) return supervise(argc, argv);
  if (argc >= 2 && !strcmp(argv[1], "stop-control")) return stop_control(argc, argv);
  if (argc >= 2 && !strcmp(argv[1], "kill-control")) return stop_control(argc, argv);
  if (argc >= 2 && !strcmp(argv[1], "owner-control")) return stop_control(argc, argv);
  if (argc == 3 && !strcmp(argv[1], "inspect")) {
    int pid = positive(argv[2]);
    struct proc_bsdinfo value;
    if (pid < 0) return 2;
    if (!info(pid, &value)) {
      int absent = kill(pid, 0) < 0 && errno == ESRCH;
      puts(absent ? "{\"status\":\"absent\"}" : "{\"status\":\"unknown\"}"); return 0;
    }
    identity(stdout, &value); puts(""); return 0;
  }
  if (argc == 2 && !strcmp(argv[1], "list")) {
    int capacity = proc_listallpids(NULL, 0);
    if (capacity < 1 || capacity > 1000000) return 5;
    capacity += 256;
    pid_t *pids = calloc((size_t)capacity, sizeof(pid_t));
    if (!pids) return 6;
    int count = proc_listallpids(pids, capacity * (int)sizeof(pid_t));
    if (count <= 0 || count >= capacity) { free(pids); return 5; }
    int first = 1;
    fputc('[', stdout);
    for (int index = 0; index < count; index++) {
      struct proc_bsdinfo value;
      if (info(pids[index], &value) && value.pbi_uid == geteuid()) {
        if (!first) fputc(',', stdout);
        identity(stdout, &value); first = 0;
      }
    }
    puts("]"); free(pids); return 0;
  }
  return 2;
}
#else
#include <stdio.h>
int main(void) { fputs("macOS libproc helper is unavailable on this platform\n", stderr); return 5; }
#endif
