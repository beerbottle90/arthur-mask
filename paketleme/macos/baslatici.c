/* Arthur Mask.app başlatıcısı (Contents/MacOS/Arthur Mask).
 *
 * İndirilen paketin karantina işaretini kaldırır; aksi hâlde Claude Desktop'un sonradan başlattığı gömülü
 * Python ayrıca Gatekeeper'a takılır. Kullanıcı uygulamayı "Yine de Aç" ile onayladıktan sonra çalıştığı için
 * onayı genişletmez. Ardından gömülü Python'la `arthur_mask.baslat` açılır (Windows'taki kısayolun karşılığı).
 */
#include <limits.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/xattr.h>
#include <unistd.h>

extern char **environ;

static void ust_klasor(char *yol) {
    char *ayrac = strrchr(yol, '/');
    if (ayrac) *ayrac = '\0';
}

int main(void) {
    char ham[PATH_MAX], paket[PATH_MAX], kaynaklar[PATH_MAX], python[PATH_MAX];
    uint32_t boy = sizeof ham;
    if (_NSGetExecutablePath(ham, &boy) != 0 || !realpath(ham, paket)) return 1;
    ust_klasor(paket); /* .../Contents/MacOS */
    ust_klasor(paket); /* .../Contents */
    snprintf(kaynaklar, sizeof kaynaklar, "%s/Resources", paket);
    snprintf(python, sizeof python, "%s/runtime/bin/python3", kaynaklar);
    ust_klasor(paket); /* .../Arthur Mask.app */

    if (getxattr(paket, "com.apple.quarantine", NULL, 0, 0, 0) >= 0) {
        char *xattr[] = {"/usr/bin/xattr", "-dr", "com.apple.quarantine", paket, NULL};
        pid_t pid;
        if (posix_spawn(&pid, xattr[0], NULL, NULL, xattr, environ) == 0) waitpid(pid, NULL, 0);
    }

    if (chdir(kaynaklar) != 0) return 1;
    char *arg[] = {python, "-I", "-B", "-c",
                   "import sys; from arthur_mask.baslat import main; sys.exit(main())", NULL};
    execv(python, arg);
    perror("Arthur Mask");
    return 1;
}
