#ifndef AUTH_H
#define AUTH_H

#include "models.h"

User *authenticateUser(
    const char *name,
    const char *password
);

int registerUser(
    const char *name,
    const char *password
);

#endif