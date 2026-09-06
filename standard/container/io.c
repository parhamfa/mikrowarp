#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sched.h>
#include <signal.h>
#include <sys/wait.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static volatile sig_atomic_t stopping = 0;
static void stop_handler(int signo) { (void)signo; stopping = 1; }
static long boot_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_BOOTTIME, &ts)) return -1;
    return ts.tv_sec;
}

/* PID 1 owns only lifecycle. Network readiness still expires in the kernel. */
static int supervise(char **command) {
    struct sigaction sa = {0}; sa.sa_handler = stop_handler;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL); sigaction(SIGINT, &sa, NULL);
    long started = boot_seconds(), ending = 0;
    if (started < 0) return 8;
    unlink("/run/mikrowarp/status");
    pid_t child = fork();
    if (child < 0) return 8;
    if (!child) {
        setpgid(0, 0);
        signal(SIGTERM, SIG_DFL); signal(SIGINT, SIG_DFL);
        execvp(command[0], command); _exit(127);
    }
    setpgid(child, child);
    FILE *pidfile = fopen("/run/mikrowarp/controller.pid", "w");
    if (pidfile) { fprintf(pidfile, "%ld\n", (long)child); fclose(pidfile); }
    for (;;) {
        int status;
        pid_t done;
        while ((done = waitpid(-1, &status, WNOHANG)) > 0) {
            if (done == child) {
                kill(-child, SIGTERM);
                return stopping == 1 ? 0 : 75;
            }
        }
        long now = boot_seconds(), heartbeat = started;
        FILE *file = fopen("/run/mikrowarp/status", "r");
        if (file) {
            char line[256];
            while (fgets(line, sizeof line, file)) {
                long value;
                if (sscanf(line, "uptime=%ld", &value) == 1 && value >= started && value <= now) heartbeat = value;
            }
            fclose(file);
        }
        if (!stopping && now - heartbeat > 120) {
            fputs("[mikrowarp] controller heartbeat expired; restarting container\n", stderr);
            stopping = 2;
        }
        if (stopping && !ending) { kill(-child, SIGTERM); ending = now + 8; }
        if (ending && now >= ending) { kill(-child, SIGKILL); return stopping == 1 ? 0 : 75; }
        struct timespec pause = {.tv_sec=2,.tv_nsec=0}; nanosleep(&pause,NULL);
    }
}

/* Drain the daemon even when disk writes fail. Keep exactly two bounded files. */
static int log_stream(const char *dir, const char *limit_arg) {
    char *end = NULL;
    unsigned long limit = strtoul(limit_arg, &end, 10);
    if (!end || *end || limit < 8192 || limit > 16777216) return 2;
    int dfd = open(dir, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dfd < 0) return 3;
    int fd = -1, warned = 0;
    unsigned long used = 0;
    unsigned char buffer[8192];
    ssize_t count;
    while ((count = read(STDIN_FILENO, buffer, sizeof buffer)) != 0) {
        if (count < 0) { if (errno == EINTR) continue; break; }
        size_t offset = 0;
        while (offset < (size_t)count) {
            if (fd < 0) {
                fd = openat(dfd, "service.log", O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0600);
                struct stat st;
                if (fd < 0 || fstat(fd, &st) || !S_ISREG(st.st_mode)) {
                    if (fd >= 0) close(fd);
                    fd = -1;
                    if (!warned) { fputs("[mikrowarp] service log unavailable; draining output\n", stderr); warned = 1; }
                    break;
                }
                used = (unsigned long)st.st_size;
            }
            if (used >= limit) {
                close(fd); fd = -1;
                if (renameat(dfd, "service.log", dfd, "service.log.1")) break;
                continue;
            }
            size_t amount = (size_t)count - offset;
            if (amount > limit - used) amount = limit - used;
            ssize_t written = write(fd, buffer + offset, amount);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) { close(fd); fd = -1; break; }
            offset += (size_t)written; used += (unsigned long)written;
        }
    }
    if (fd >= 0) close(fd);
    close(dfd);
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 3 && !strcmp(argv[1], "supervise")) return supervise(&argv[2]);
    if (argc == 4 && !strcmp(argv[1], "log")) return log_stream(argv[2], argv[3]);
    if (argc >= 3 && !strcmp(argv[1], "netns")) {
        /* RouterOS forbids the /sys remount performed by ip netns exec. */
        int fd = open("/run/netns/mikrowarp-probe", O_RDONLY | O_CLOEXEC);
        if (fd < 0 || setns(fd, CLONE_NEWNET)) { perror("probe network namespace"); return 6; }
        close(fd);
        execvp(argv[2], &argv[2]); perror("probe command"); return 7;
    }
    if (argc >= 3 && !strcmp(argv[1], "sync")) {
        for (int i=2; i<argc; i++) {
            int fd = open(argv[i], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
            if (fd < 0) return 4;
            int result = fsync(fd); close(fd);
            if (result) return 5;
        }
        return 0;
    }
    fputs("Usage: mikrowarp-io log DIRECTORY BYTES | sync PATH...\n", stderr);
    return 2;
}
