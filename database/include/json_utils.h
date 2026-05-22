#ifndef JSON_UTILS_H
#define JSON_UTILS_H

char *readFile(const char *filename);

int writeFile(
    const char *filename,
    const char *content
);

#endif