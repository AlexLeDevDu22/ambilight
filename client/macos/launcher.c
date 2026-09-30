/*
 * Exécutable d'Ambilight.app : embarque Python et exécute server.py DANS ce
 * processus. Ainsi le processus EST l'app « Ambilight » : l'icône de la barre
 * de menus s'affiche (un processus enfant n'y a pas droit quand il est lancé
 * par une app), et les permissions macOS (micro, écran, entrées) sont
 * attribuées à Ambilight. Les chemins sont fixés à la compilation
 * (voir build_app.sh).
 */
#include <Python.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#if !defined(CLIENT_DIR) || !defined(SITE_PACKAGES)
#error "CLIENT_DIR et SITE_PACKAGES doivent être définis"
#endif

int main(int argc, char **argv) {
    if (chdir(CLIENT_DIR) != 0) return 1;

    const char *home = getenv("HOME");
    if (home) {
        char logdir[4096], logf[4096];
        snprintf(logdir, sizeof logdir, "%s/Library/Logs/Ambilight", home);
        mkdir(logdir, 0755);
        snprintf(logf, sizeof logf, "%s/server.log", logdir);
        struct stat st;
        int flags = O_WRONLY | O_CREAT | O_APPEND;
        if (stat(logf, &st) == 0 && st.st_size > 5 * 1024 * 1024) flags |= O_TRUNC;
        int fd = open(logf, flags, 0644);
        if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); close(fd); }
    }

    /* Paquets du venv du projet + dossier client */
    setenv("PYTHONPATH", SITE_PACKAGES ":" CLIENT_DIR, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    setenv("AMBILIGHT_APP", "1", 1);

    char *args[64];
    int n = 0;
    args[n++] = argv[0];
    args[n++] = CLIENT_DIR "/server.py";
    for (int i = 1; i < argc && n < 63; i++) {
        if (strncmp(argv[i], "-psn", 4) == 0) continue;  /* argument ajouté par le Finder */
        args[n++] = argv[i];
    }
    args[n] = NULL;
    return Py_BytesMain(n, args);
}
