/* Stand-in for a Zephyr image's shell command tables, laid out as in
 * include/zephyr/shell/shell.h. Rebuild the fixtures next to this file with:
 *
 *   clang --target=armv7m-none-eabi -mthumb -ffreestanding -nostdlib -fuse-ld=lld \
 *         -Wl,-e,main -O0 -o shell_arm.elf shell.c          (Cortex-M, as on an nRF91)
 *   ... -mbig-endian -Wl,-EB -o shell_armbe.elf              (big endian)
 *   clang --target=aarch64-none-elf ... -o shell_a64.elf      (64-bit, no padding)
 *   gcc -m32 -ffreestanding -nostdlib -static -Wl,-e,main -O0 -o shell32.elf shell.c
 *                                                            (native_sim, 32-bit)
 *   gcc -DPAD -O0 -o shell64pad.elf shell.c                  (native_sim_64: 24-byte padding)
 *
 * A plain link names section bounds __start_<sec>/__stop_<sec> where Zephyr's linker
 * script gives _<sec>_list_start/_end; the reader accepts both.
 */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
struct shell_static_entry;
typedef int (*shell_cmd_handler)(void *sh, size_t argc, char **argv);
typedef void (*shell_dynamic_get)(size_t idx, struct shell_static_entry *entry);
union shell_cmd_entry { shell_dynamic_get dynamic_get; const struct shell_static_entry *entry; };
struct shell_static_args { uint8_t mandatory; uint8_t optional; uint16_t remote_cmd:2; uint16_t remote_id:4; };
#ifdef PAD
#define P 24
#else
#define P 0
#endif
struct shell_static_entry { const char *syntax; const char *help; const union shell_cmd_entry *subcmd;
  shell_cmd_handler handler; struct shell_static_args args; uint8_t padding[P]; };
static int h(void *sh, size_t argc, char **argv) { return 0; }
static void dyn_get(size_t idx, struct shell_static_entry *e) { e->syntax = 0; }
#define SEC(x) __attribute__((section(#x), used, aligned(sizeof(void*))))
/* dynamic */
static const union shell_cmd_entry dyn_devs SEC(shell_dynamic_subcmds) = { .dynamic_get = dyn_get };
/* static set for "kernel" */
static const struct shell_static_entry shell_kernel_sub[] = {
  { "version", "Kernel version.", NULL, h, {1, 0} },
  { "uptime", "Kernel uptime.", NULL, h, {1, 1} },
  { "thread", "Thread commands", NULL, h, {1, 0} },
  { 0 } };
static const union shell_cmd_entry kernel_sub = { .entry = shell_kernel_sub };
/* section set for "app": marker, then entries, then end marker */
static const struct shell_static_entry app_set[] SEC(shell_subcmds) = {
  { 0 },
  { "start", "Start the app", NULL, h, {1, 0} },
  { "stop", NULL, NULL, h, {1, 0} },
  { 0 } };
static const struct shell_static_entry _shell_kernel = { "kernel", "Kernel commands", &kernel_sub, h, {1, 0} };
static const struct shell_static_entry _shell_device = { "device", "Device commands", &dyn_devs, h, {2, 0} };
static const struct shell_static_entry _shell_app = { "app", "App commands", (const union shell_cmd_entry *)&app_set[0], h, {1, 0} };
static const struct shell_static_entry _shell_help = { "help", NULL, NULL, h, {1, 0} };
static const union shell_cmd_entry roots[] SEC(shell_root_cmds) = {
  { .entry = &_shell_app }, { .entry = &_shell_device }, { .entry = &_shell_help }, { .entry = &_shell_kernel } };
extern const char __start_shell_root_cmds[], __stop_shell_root_cmds[], __start_shell_subcmds[], __stop_shell_subcmds[], __start_shell_dynamic_subcmds[], __stop_shell_dynamic_subcmds[];
const void *volatile keep[] = { __start_shell_root_cmds, __stop_shell_root_cmds, __start_shell_subcmds, __stop_shell_subcmds, __start_shell_dynamic_subcmds, __stop_shell_dynamic_subcmds };
int main(void) { return roots[0].entry != 0; }
