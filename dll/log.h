#ifndef PR2N_LOG_H
#define PR2N_LOG_H
/* Append a line to PR2Nation.log next to the game exe (flushed per line). */
void log_open(void);
void log_line(const char *fmt, ...);
#endif
