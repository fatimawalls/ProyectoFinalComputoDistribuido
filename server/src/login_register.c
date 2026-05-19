#include <stdlib.h>
#include <string.h>     
#include <stdio.h>

#include "cJSON.h"           
#include "constants.h"        
#include "json_utils.h"       
#include "database_repository.h"


int login(const char *name, const char *password) {
    int count = 0;
    User *users = getAllUsers(&count); 
    
    if (users == NULL) {
        return 0; 
    }

    for (int i = 0; i < count; i++) {
        if (strcmp(users[i].name, name) == 0 && strcmp(users[i].password, password) == 0) {
            free(users);
            return 1;
        }
    }

    free(users);
    return 0;
}

int registerUser(const char *name, const char *password) {
    int count = 0;
    User *users = getAllUsers(&count);

    if (users != NULL) {
        for (int i = 0; i < count; i++) {
            // Verificamos que el nombre no sea NULL antes de comparar
            if (users[i].name == NULL) {
                break; 
            }
            if (strcmp(users[i].name, name) == 0) {
                free(users);
                return 0; 
            }
        }
        free(users);
    }
    User nuevo = createUser(name, password);
    
    int resultado = saveUser(&nuevo);

    return resultado; 
}