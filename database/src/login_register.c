#include <stdlib.h>
#include <string.h>     
#include <stdio.h>

#include "cJSON.h"           
#include "constants.h"        
#include "json_utils.h"       
#include "database_repository.h"
#include "memory_utils.h"


User *authenticateUser(
    const char *name,
    const char *password
)
{
    int count = 0;

    User *users =
        getAllUsers(&count);

    if(users == NULL)
    {
        return NULL;
    }

    for(int i = 0; i < count; i++)
    {
        if(
            strcmp(users[i].name, name) == 0 &&
            strcmp(users[i].password, password) == 0
        )
        {
            User *result =
                malloc(sizeof(User));

            *result = users[i];

            return result;
        }
    }

    free(users);

    return NULL;
}

int registerUser(
    const char *name,
    const char *password,
    const char *nickname
)
{
    int count = 0;

    User *users = getAllUsers(&count);

    if(users != NULL)
    {
        for(int i = 0; i < count; i++)
        {
            if(users[i].name && strcmp(users[i].name, name) == 0)
            {
                freeUsers(users, count);
                return 0;
            }
        }

        freeUsers(users, count);
    }

    User nuevo =
        createUserWithNickname(
            name,
            password,
            nickname
        );

    int resultado =
        saveUser(&nuevo);

    int id =
        resultado ? nuevo.id : 0;

    freeUser(&nuevo);

    return id;
}