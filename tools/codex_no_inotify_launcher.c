#define _GNU_SOURCE
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>

static void install_no_inotify_seccomp_filter(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),

        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),

        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_inotify_init, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),

        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_inotify_init1, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),

        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_inotify_add_watch, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),

        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_inotify_rm_watch, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),

        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        perror("PR_SET_NO_NEW_PRIVS failed");
        exit(125);
    }
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0) {
        perror("PR_SET_SECCOMP failed");
        exit(125);
    }
}

static void close_inherited_file_descriptors(void) {
    struct rlimit nofile_limit;
    if (getrlimit(RLIMIT_NOFILE, &nofile_limit) != 0) {
        perror("getrlimit RLIMIT_NOFILE failed");
        exit(125);
    }

    rlim_t max_fd = nofile_limit.rlim_cur;
    if (max_fd == RLIM_INFINITY || max_fd > 65536) {
        max_fd = 65536;
    }

    for (int fd = 3; fd < (int)max_fd; fd += 1) {
        close(fd);
    }
}

int main(int argc, char **argv) {
    const char *real_codex_executable = getenv("CODEX_REAL_EXECUTABLE");
    if (real_codex_executable == NULL || real_codex_executable[0] == '\0') {
        fputs("CODEX_REAL_EXECUTABLE is required\n", stderr);
        return 125;
    }
    if (access(real_codex_executable, X_OK) != 0) {
        perror("CODEX_REAL_EXECUTABLE is not executable");
        return 125;
    }

    char **exec_argv = calloc((size_t)argc + 1, sizeof(char *));
    if (exec_argv == NULL) {
        perror("calloc failed");
        return 125;
    }

    exec_argv[0] = (char *)real_codex_executable;
    for (int index = 1; index < argc; index += 1) {
        exec_argv[index] = argv[index];
    }
    exec_argv[argc] = NULL;

    close_inherited_file_descriptors();
    install_no_inotify_seccomp_filter();
    execv(real_codex_executable, exec_argv);
    perror("execv Codex failed");
    return 127;
}
