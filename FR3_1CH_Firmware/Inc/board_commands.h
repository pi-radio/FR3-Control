#ifndef BOARD_COMMANDS_H
#define BOARD_COMMANDS_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Parses one newline-terminated ASCII command in `line` (no terminator included)
 * and writes a CRLF-terminated response into `response`. */
void Commands_ProcessLine(const char *line, char *response, size_t response_capacity);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_COMMANDS_H */
