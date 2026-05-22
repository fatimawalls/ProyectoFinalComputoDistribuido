#include <stdio.h>
#include <stdlib.h>
#include <string.h>

char *readFile(const char *filename)
{
    FILE *file = fopen(filename, "r");

    if (!file)
        return NULL;

    fseek(file, 0, SEEK_END);

    long size = ftell(file);

    rewind(file);

    char *buffer = malloc(size + 1);

    fread(buffer, 1, size, file);

    buffer[size] = '\0';

    fclose(file);

    return buffer;
}

int writeFile(const char *filename,const char *content){
    FILE *file = fopen(filename, "w");

    if (!file)
        return 0;

    fprintf(file, "%s", content);

    fclose(file);

    return 1;
}