#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <arpa/inet.h>
#include <unistd.h>
#include <sys/socket.h>
#include <ifaddrs.h>
#include <signal.h> // 1. NUEVO: Librería para manejar señales (evitar zombies)

#include "request_handler.h"
#include "login_register.h"

#define PORT 8080

int main()
{
    int serverSocket = socket(AF_INET, SOCK_STREAM, 0);

    if (serverSocket < 0)
    {
        perror("socket");
        return 1;
    }

    int opt = 1;

    if (setsockopt(
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

    if (bind(
        serverSocket,
        (struct sockaddr*)&serverAddr,
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

    // --- SECCIÓN PARA AUTO-DETECTAR LA IP REAL ---
    char realIP[64] = "0.0.0.0";
    struct ifaddrs* interfaces = NULL;
    struct ifaddrs* temp_addr = NULL;

    if (getifaddrs(&interfaces) == 0) {
        temp_addr = interfaces;
        while (temp_addr != NULL) {
            if (temp_addr->ifa_addr != NULL && temp_addr->ifa_addr->sa_family == AF_INET) {
                char* ip = inet_ntoa(((struct sockaddr_in*)temp_addr->ifa_addr)->sin_addr);

                if (strcmp(ip, "127.0.0.1") != 0) {
                    strcpy(realIP, ip);
                    break;
                }
            }
            temp_addr = temp_addr->ifa_next;
        }
        freeifaddrs(interfaces);
    }

    printf("==================================================\n");
    printf(" DATABASE SERVER INICIADO\n");
    printf(" Dirección IP : %s\n", realIP);
    printf(" Puerto        : %d\n", ntohs(serverAddr.sin_port));
    printf("==================================================\n");
    fflush(stdout);

    // 2. NUEVO: Prevenir que los procesos hijos se conviertan en "zombies" al terminar
    signal(SIGCHLD, SIG_IGN);

    while (1)
    {
        int clientSocket = accept(serverSocket, NULL, NULL);

        if (clientSocket < 0)
        {
            perror("accept");
            continue;
        }

        // 3. NUEVO: Hacemos el fork para crear un proceso paralelo
        pid_t pid = fork();

        if (pid < 0) {
            perror("Error en fork");
            close(clientSocket);
            continue;
        }

        if (pid == 0) {
            // =========================================================
            // PROCESO HIJO: Atiende al cliente
            // =========================================================
            close(serverSocket); // El hijo no necesita escuchar conexiones nuevas

            printf("[PID %d] Client connected\n", getpid());
            fflush(stdout);

            char buffer[8192];

            int bytes = recv(
                clientSocket,
                buffer,
                sizeof(buffer) - 1,
                0
            );

            if (bytes <= 0)
            {
                perror("recv");
                close(clientSocket);
                exit(1); // IMPORTANTE: El hijo debe morir con exit(), no con continue o return
            }

            buffer[bytes] = '\0';

            printf("[PID %d] REQUEST:\n%s\n", getpid(), buffer);
            fflush(stdout);

            handleRequest(clientSocket, buffer);

            close(clientSocket);
            exit(0); // IMPORTANTE: El hijo termina exitosamente aquí
        }
        else {
            // =========================================================
            // PROCESO PADRE: Cierra el socket del cliente y sigue iterando
            // =========================================================
            close(clientSocket); // El padre le deja el socket al hijo
        }
    }

    close(serverSocket);

    return 0;
}