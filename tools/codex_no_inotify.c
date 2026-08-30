#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdarg.h>
#include <sys/syscall.h>

typedef long (*real_syscall_function)(long number, ...);

static real_syscall_function load_real_syscall(void) {
    return (real_syscall_function)dlsym(RTLD_NEXT, "syscall");
}

int inotify_init(void) {
    errno = ENOSYS;
    return -1;
}

int inotify_init1(int flags) {
    (void)flags;
    errno = ENOSYS;
    return -1;
}

long syscall(long number, ...) {
    if (
        number == SYS_inotify_init
        || number == SYS_inotify_init1
        || number == SYS_inotify_add_watch
        || number == SYS_inotify_rm_watch
    ) {
        errno = ENOSYS;
        return -1;
    }

    real_syscall_function real_syscall = load_real_syscall();
    if (real_syscall == 0) {
        errno = ENOSYS;
        return -1;
    }

    va_list arguments;
    va_start(arguments, number);
    long argument_1 = va_arg(arguments, long);
    long argument_2 = va_arg(arguments, long);
    long argument_3 = va_arg(arguments, long);
    long argument_4 = va_arg(arguments, long);
    long argument_5 = va_arg(arguments, long);
    long argument_6 = va_arg(arguments, long);
    va_end(arguments);

    return real_syscall(
        number,
        argument_1,
        argument_2,
        argument_3,
        argument_4,
        argument_5,
        argument_6
    );
}

int inotify_add_watch(int fd, const char *pathname, unsigned int mask) {
    (void)fd;
    (void)pathname;
    (void)mask;
    errno = ENOSYS;
    return -1;
}
