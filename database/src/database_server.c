#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <arpa/inet.h>
#include <unistd.h>
#include <sys/socket.h>
#include <ifaddrs.h>

#include "request_handler.h"
#include "login_register.h"

#define PORT 8080

int main()
{
    int serverSocket = socket(AF_INET, SOCK_STREAM, 0);

    if(serverSocket < 0)
    {
        perror("socket");
        return 1;
    }

    int opt = 1;

    if(setsockopt(
        serverSocket,
        SOL_SOCKET,
        SO_REUSEADDR,
        &opt,
        sizeof(opt)
    ) < 0)
    {
        perror("setsockopt");
        close(serverSocket);
        return 1;
    }

    struct sockaddr_in serverAddr;
    memset(&serverAddr, 0, sizeof(serverAddr));

    serverAddr.sin_family = AF_INET;
    serverAddr.sin_port = htons(PORT);

    /*
        IMPORTANT FOR DOCKER:
        Listen on all interfaces, not only localhost.
    */
    serverAddr.sin_addr.s_addr = htonl(INADDR_ANY);

    if(bind(
        serverSocket,
        (struct sockaddr *)&serverAddr,
        sizeof(serverAddr)
    ) < 0)
    {
        perror("bind");
        close(serverSocket);
        return 1;
    }

    if (listen(serverSocket, 10) < 0)
    {
        perror("listen");
        close(serverSocket);
        return 1;
    }

    // --- NUEVA SECCIÓN PARA AUTO-DETECTAR LA IP REAL ---
    char realIP[64] = "0.0.0.0"; // IP por defecto si falla la búsqueda
    struct ifaddrs* interfaces = NULL;
    struct ifaddrs* temp_addr = NULL;

    // Obtener la lista de interfaces de red
    if (getifaddrs(&interfaces) == 0) {
        temp_addr = interfaces;
        while (temp_addr != NULL) {
            // Buscamos interfaces IPv4 (AF_INET)
            if (temp_addr->ifa_addr != NULL && temp_addr->ifa_addr->sa_family == AF_INET) {
                char* ip = inet_ntoa(((struct sockaddr_in*)temp_addr->ifa_addr)->sin_addr);

                // Ignoramos la interfaz local (127.0.0.1) para agarrar la de Docker (172.x.x.x)
                if (strcmp(ip, "127.0.0.1") != 0) {
                    strcpy(realIP, ip);
                    break; // Encontramos la IP, salimos del ciclo
                }
            }
            temp_addr = temp_addr->ifa_next;
        }
        freeifaddrs(interfaces); // Liberar memoria
    }

    printf("==================================================\n");
    printf(" DATABASE SERVER INICIADO\n");
    printf(" Dirección IP : %s\n", realIP);
    printf(" Puerto        : %d\n", ntohs(serverAddr.sin_port));
    printf("==================================================\n");
    fflush(stdout);


    while(1)
    {
        int clientSocket = accept(serverSocket, NULL, NULL);

        if(clientSocket < 0)
        {
            perror("accept");
            continue;
        }

        printf("Client connected\n");
        fflush(stdout);

        char buffer[8192];

        int bytes = recv(
            clientSocket,
            buffer,
            sizeof(buffer) - 1,
            0
        );

        if(bytes <= 0)
        {
            perror("recv");
            close(clientSocket);
            continue;
        }

        buffer[bytes] = '\0';

        printf("REQUEST:\n%s\n", buffer);
        fflush(stdout);

        handleRequest(clientSocket, buffer);

        close(clientSocket);
    }

    close(serverSocket);

    return 0;
}