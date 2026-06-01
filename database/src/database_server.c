#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include <arpa/inet.h>
#include <unistd.h>
#include <sys/socket.h>
#include <ifaddrs.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>
#include <fcntl.h>

#include "request_handler.h"
#include "login_register.h"

#define PORT 5000

/*
    Global DB lock.

    Why:
    The database server is forkable now. That means several child
    processes can handle requests at the same time.

    The DB is stored in JSON/text files, so write operations must be
    serialized to avoid corrupted files or lost updates.

    This lock protects the whole request:
        recv -> handleRequest -> response

    It is intentionally simple and safe.
*/
#define DB_LOCK_FILE "data/database.lock"

static int acquireDatabaseLock(void)
{
    int lockFd = open(
        DB_LOCK_FILE,
        O_CREAT | O_RDWR,
        0666
    );

    if(lockFd < 0)
    {
        perror("[DB-LOCK] open");
        return -1;
    }

    struct flock lock;
    memset(&lock, 0, sizeof(lock));

    lock.l_type = F_WRLCK;
    lock.l_whence = SEEK_SET;
    lock.l_start = 0;
    lock.l_len = 0;

    while(fcntl(lockFd, F_SETLKW, &lock) < 0)
    {
        if(errno == EINTR)
        {
            continue;
        }

        perror("[DB-LOCK] fcntl lock");
        close(lockFd);
        return -1;
    }

    return lockFd;
}

static void releaseDatabaseLock(int lockFd)
{
    if(lockFd < 0)
    {
        return;
    }

    struct flock lock;
    memset(&lock, 0, sizeof(lock));

    lock.l_type = F_UNLCK;
    lock.l_whence = SEEK_SET;
    lock.l_start = 0;
    lock.l_len = 0;

    if(fcntl(lockFd, F_SETLK, &lock) < 0)
    {
        perror("[DB-LOCK] fcntl unlock");
    }

    close(lockFd);
}

static void handleClientRequest(
    int clientSocket,
    struct sockaddr_in clientAddr
)
{
    printf(
        "[DB-CHILD %d] Client connected from %s:%d\n",
        getpid(),
        inet_ntoa(clientAddr.sin_addr),
        ntohs(clientAddr.sin_port)
    );
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
        perror("[DB-CHILD] recv");
        close(clientSocket);
        exit(0);
    }

    buffer[bytes] = '\0';

    printf(
        "[DB-CHILD %d] REQUEST:\n%s\n",
        getpid(),
        buffer
    );
    fflush(stdout);

    int lockFd = acquireDatabaseLock();

    if(lockFd < 0)
    {
        /*
            If the DB lock cannot be acquired, do not execute the request.
            This prevents unsafe concurrent writes.
        */
        perror("[DB-CHILD] database lock failed");
        close(clientSocket);
        exit(1);
    }

    printf(
        "[DB-CHILD %d] DB lock acquired\n",
        getpid()
    );
    fflush(stdout);

    handleRequest(
        clientSocket,
        buffer
    );

    releaseDatabaseLock(lockFd);

    printf(
        "[DB-CHILD %d] DB lock released\n",
        getpid()
    );
    fflush(stdout);

    close(clientSocket);

    printf(
        "[DB-CHILD %d] Client handled. Exiting.\n",
        getpid()
    );
    fflush(stdout);

    exit(0);
}

int main()
{
    /*
        Avoid zombie child processes.
    */
    signal(SIGCHLD, SIG_IGN);

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

    if(listen(serverSocket, 10) < 0)
    {
        perror("listen");
        close(serverSocket);
        return 1;
    }

    /*
        Auto-detect real IP.
    */
    char realIP[64] = "0.0.0.0";
    struct ifaddrs *interfaces = NULL;
    struct ifaddrs *temp_addr = NULL;

    if(getifaddrs(&interfaces) == 0)
    {
        temp_addr = interfaces;

        while(temp_addr != NULL)
        {
            if(
                temp_addr->ifa_addr != NULL &&
                temp_addr->ifa_addr->sa_family == AF_INET
            )
            {
                char *ip =
                    inet_ntoa(
                        ((struct sockaddr_in *)temp_addr->ifa_addr)->sin_addr
                    );

                if(strcmp(ip, "127.0.0.1") != 0)
                {
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
    printf(" Direccion IP : %s\n", realIP);
    printf(" Puerto       : %d\n", ntohs(serverAddr.sin_port));
    printf(" Modo         : fork + file locking\n");
    printf(" Lock file    : %s\n", DB_LOCK_FILE);
    printf("==================================================\n");
    fflush(stdout);

    while(1)
    {
        struct sockaddr_in clientAddr;
        socklen_t clientLen = sizeof(clientAddr);

        int clientSocket = accept(
            serverSocket,
            (struct sockaddr *)&clientAddr,
            &clientLen
        );

        if(clientSocket < 0)
        {
            perror("accept");
            continue;
        }

        pid_t pid = fork();

        if(pid < 0)
        {
            perror("fork");
            close(clientSocket);
            continue;
        }

        if(pid == 0)
        {
            /*
                Child process.
            */
            close(serverSocket);

            handleClientRequest(
                clientSocket,
                clientAddr
            );
        }

        /*
            Parent process.
            The parent keeps accepting more clients.
        */
        close(clientSocket);
    }

    close(serverSocket);

    return 0;
}
