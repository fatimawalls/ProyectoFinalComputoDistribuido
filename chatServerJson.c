/*
 * ChatRoomServer.c
 *
 * Compilar:

gcc ChatRoomServer.c \
database/src/database_repository.c \
database/src/json_utils.c \
database/src/index_manager.c \
database/src/memory_utils.c \
database/src/login_register.c \
database/src/protocol.c \
database/libs/cJSON.c \
-Idatabase/include \
-Idatabase/libs \
-lpthread \
-o chatserver

 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/mman.h>

#include "cJSON.h"
#include "models.h"
#include "database_repository.h"
#include "memory_utils.h"
#include "login_register.h"
#include "protocol.h"

 /* ============================================================
    CONSTANTES
    ============================================================ */
#define TCP_PORT    5000
#define UDP_PORT    5001
#define MAX_USERS   64
#define MAX_MEMBERS 32
#define BUFSIZE     8192

    /* ============================================================
       SHARED MEMORY
       ============================================================ */
typedef struct {
    int  db_user_id;
    char username[64];
    int  active;
    char udp_ip[64];
    int  udp_port;
} ShmUser;

typedef struct {
    ShmUser         users[MAX_USERS];
    int             user_count;
    pthread_mutex_t lock;
} SharedState;

static SharedState* g_state = NULL;
static int          g_tcp_sd = -1;
static int          g_udp_sd = -1;

/* ============================================================
   RED
   ============================================================ */
static int recv_line(int fd, char* buf, int maxlen) {
    int total = 0; char c;
    while (total < maxlen - 1) {
        int n = recv(fd, &c, 1, 0);
        if (n <= 0) return n;
        if (c == '\n') break;
        buf[total++] = c;
    }
    buf[total] = '\0';
    return total;
}

/* ============================================================
   UDP
   ============================================================ */
static void udp_notify(int db_user_id, const char* msg) {
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        ShmUser* u = &g_state->users[i];
        if (!u->active || u->db_user_id != db_user_id || u->udp_port == 0)
            continue;
        struct sockaddr_in dest;
        memset(&dest, 0, sizeof(dest));
        dest.sin_family = AF_INET;
        dest.sin_port = htons(u->udp_port);
        inet_aton(u->udp_ip, &dest.sin_addr);
        pthread_mutex_unlock(&g_state->lock);
        char buf[BUFSIZE];
        snprintf(buf, sizeof(buf), "%s\n", msg);
        sendto(g_udp_sd, buf, strlen(buf), 0,
            (struct sockaddr*)&dest, sizeof(dest));
        return;
    }
    pthread_mutex_unlock(&g_state->lock);
}

static void udp_push_to_list(const char* json_text,
    int* ids, int count, int skip_id)
{
    for (int i = 0; i < count; i++)
        if (ids[i] != skip_id)
            udp_notify(ids[i], json_text);
}

/* ============================================================
   AUTENTICACION + SYNC
   ============================================================ */
static int autenticar(int sock, const char* client_ip,
    char* username_out)
{
    char buf[BUFSIZE];

    while (1) {
        if (recv_line(sock, buf, sizeof(buf)) <= 0) return -1;

        cJSON* req = cJSON_Parse(buf);
        if (!req) continue;

        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!jtype) { cJSON_Delete(req); continue; }
        const char* type = jtype->valuestring;

        /* CREATE_ACCOUNT */
        if (strcmp(type, "CREATE_ACCOUNT") == 0) {
            const char* uname = cJSON_GetObjectItem(req, "username")->valuestring;
            const char* pass = cJSON_GetObjectItem(req, "password")->valuestring;
            User u = createUser(uname, pass);
            saveUser(&u);
            sendCreateAccountResponse(sock, 1, u.id, u.name);
            freeUser(&u);
            cJSON_Delete(req);
            continue;
        }

        /* AUTH */
        if (strcmp(type, "AUTH") == 0) {
            const char* uname = cJSON_GetObjectItem(req, "username")->valuestring;
            const char* pass = cJSON_GetObjectItem(req, "password")->valuestring;

            User* user = authenticateUser(uname, pass);
            if (!user) {
                sendAuthResponse(sock, 0, 0, NULL);
                cJSON_Delete(req);
                continue;
            }

            int db_id = user->id;
            strncpy(username_out, user->name, 63);

            /* Registrar en shared memory */
            pthread_mutex_lock(&g_state->lock);
            int slot = -1;
            for (int i = 0; i < MAX_USERS; i++)
                if (!g_state->users[i].active) { slot = i; break; }

            if (slot == -1) {
                pthread_mutex_unlock(&g_state->lock);
                sendAuthResponse(sock, 0, 0, NULL);
                freeUser(user); free(user);
                cJSON_Delete(req);
                continue;
            }

            ShmUser* su = &g_state->users[slot];
            memset(su, 0, sizeof(ShmUser));
            su->db_user_id = db_id;
            su->active = 1;
            strncpy(su->username, uname, sizeof(su->username) - 1);
            strncpy(su->udp_ip, client_ip, sizeof(su->udp_ip) - 1);
            g_state->user_count++;
            pthread_mutex_unlock(&g_state->lock);

            sendAuthResponse(sock, 1, db_id, user->name);
            freeUser(user); free(user);

            /* SYNC */
            sendSyncStart(sock);

            int roomCount;
            ChatRoom* rooms = getChatRoomsFromUser(db_id, &roomCount);
            for (int i = 0; i < roomCount; i++) {
                sendChatRoomJson(sock, &rooms[i]);

                for (int j = 0; j < rooms[i].userCount; j++) {
                    User* ru = getUserById(rooms[i].userIds[j]);
                    if (ru) {
                        sendChatUserJson(sock, ru->id, ru->name);
                        freeUser(ru); free(ru);
                    }
                }

                int msgCount;
                Message* msgs = getMessagesFromChatRoom(rooms[i].id, &msgCount);
                for (int j = 0; j < msgCount; j++)
                    sendMessageJson(sock, msgs[j].id, msgs[j].userId,
                        msgs[j].chatRoomId, msgs[j].text);
                if (msgs) freeMessages(msgs, msgCount);
            }
            if (rooms) freeChatRooms(rooms, roomCount);

            sendSyncEnd(sock);

            cJSON_Delete(req);
            return db_id;
        }

        cJSON_Delete(req);
    }
}

/* ============================================================
   LOBBY
   ============================================================ */
static void procesar_lobby(int sock, int db_user_id) {
    char buf[BUFSIZE];
    printf("[uid=%d] Lobby\n", db_user_id);

    while (1) {
        int n = recv_line(sock, buf, sizeof(buf));
        if (n <= 0) { printf("[uid=%d] Desconectado\n", db_user_id); break; }
        printf("[uid=%d] %s\n", db_user_id, buf);

        cJSON* req = cJSON_Parse(buf);
        if (!req) continue;

        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!jtype) { cJSON_Delete(req); continue; }
        const char* type = jtype->valuestring;

        /* ── NEW_MESSAGE ── */
        if (strcmp(type, "NEW_MESSAGE") == 0) {
            const char* text = cJSON_GetObjectItem(req, "text")->valuestring;
            int userId = cJSON_GetObjectItem(req, "userId")->valueint;
            int chatRoomId = cJSON_GetObjectItem(req, "chatRoomId")->valueint;

            Message msg = createMessage(text, userId, chatRoomId);
            saveMessage(&msg);

            ChatRoom* room = getChatRoomById(chatRoomId);
            if (!room) { freeMessage(&msg); cJSON_Delete(req); continue; }

            sendNewMessageResponse(sock, 1, &msg,
                room->userIds, room->userCount);

            cJSON* push = cJSON_CreateObject();
            cJSON_AddStringToObject(push, "type", "MESSAGE");
            cJSON_AddNumberToObject(push, "id", msg.id);
            cJSON_AddNumberToObject(push, "userId", msg.userId);
            cJSON_AddNumberToObject(push, "chatRoomId", msg.chatRoomId);
            cJSON_AddStringToObject(push, "text", msg.text);
            char* pt = cJSON_PrintUnformatted(push);
            cJSON_Delete(push);
            udp_push_to_list(pt, room->userIds, room->userCount, db_user_id);
            free(pt);

            freeChatRoom(room); free(room);
            freeMessage(&msg);
        }

        /* ── NEW_CHATROOM ── */
        else if (strcmp(type, "NEW_CHATROOM") == 0) {
            const char* name = cJSON_GetObjectItem(req, "name")->valuestring;
            int coordId = cJSON_GetObjectItem(req, "coordinatorId")->valueint;

            ChatRoom room = createChatRoom(name, coordId);
            saveChatRoom(&room);

            int notify[1] = { coordId };
            sendNewChatRoomResponse(sock, 1, &room, notify, 1);

            freeChatRoom(&room);
        }

        /* ── ADD_USER ── */
        else if (strcmp(type, "ADD_USER") == 0) {
            int userId = cJSON_GetObjectItem(req, "userId")->valueint;
            int chatRoomId = cJSON_GetObjectItem(req, "chatRoomId")->valueint;

            ChatRoom* before = getChatRoomById(chatRoomId);
            int notify_ids[MAX_MEMBERS]; int nc = 0;
            if (before) {
                nc = before->userCount;
                for (int i = 0; i < nc; i++)
                    notify_ids[i] = before->userIds[i];
                freeChatRoom(before); free(before);
            }

            int success = addUserToChatRoom(userId, chatRoomId);
            ChatRoom* room = getChatRoomById(chatRoomId);
            User* added = getUserById(userId);

            sendUserChatRelationResponse(sock, "ADD_USER_RESPONSE", success,
                userId, chatRoomId, added,
                room ? room->userIds : NULL,
                room ? room->userCount : 0);

            if (success && added) {
                cJSON* push = cJSON_CreateObject();
                cJSON_AddStringToObject(push, "type", "ADD_USER_RESPONSE");
                cJSON_AddNumberToObject(push, "success", 1);
                cJSON_AddNumberToObject(push, "chatRoomId", chatRoomId);
                cJSON_AddNumberToObject(push, "userId", userId);
                cJSON* cu = cJSON_CreateObject();
                cJSON_AddNumberToObject(cu, "id", added->id);
                cJSON_AddStringToObject(cu, "username", added->name);
                cJSON_AddItemToObject(push, "chatUser", cu);
                char* pt = cJSON_PrintUnformatted(push);
                cJSON_Delete(push);
                udp_push_to_list(pt, notify_ids, nc, db_user_id);
                free(pt);
            }

            if (added) { freeUser(added); free(added); }
            if (room) { freeChatRoom(room); free(room); }
        }

        /* ── REMOVE_USER ── */
        else if (strcmp(type, "REMOVE_USER") == 0) {
            int userId = cJSON_GetObjectItem(req, "userId")->valueint;
            int chatRoomId = cJSON_GetObjectItem(req, "chatRoomId")->valueint;

            ChatRoom* before = getChatRoomById(chatRoomId);
            int notify_ids[MAX_MEMBERS]; int nc = 0;
            if (before) {
                nc = before->userCount;
                for (int i = 0; i < nc; i++)
                    notify_ids[i] = before->userIds[i];
                freeChatRoom(before); free(before);
            }

            int success = removeUserFromChatRoom(userId, chatRoomId);

            sendUserChatRelationResponse(sock, "REMOVE_USER_RESPONSE", success,
                userId, chatRoomId, NULL,
                notify_ids, nc);

            if (success) {
                cJSON* push = cJSON_CreateObject();
                cJSON_AddStringToObject(push, "type", "REMOVE_USER_RESPONSE");
                cJSON_AddNumberToObject(push, "success", 1);
                cJSON_AddNumberToObject(push, "chatRoomId", chatRoomId);
                cJSON_AddNumberToObject(push, "userId", userId);
                char* pt = cJSON_PrintUnformatted(push);
                cJSON_Delete(push);
                udp_push_to_list(pt, notify_ids, nc, db_user_id);
                free(pt);
            }
        }

        /* ── DELETE_MESSAGE ── */
        else if (strcmp(type, "DELETE_MESSAGE") == 0) {
            int messageId = cJSON_GetObjectItem(req, "messageId")->valueint;

            Message* message = getMessageById(messageId);
            int notify_ids[MAX_MEMBERS]; int nc = 0;

            if (message) {
                ChatRoom* room = getChatRoomById(message->chatRoomId);
                if (room) {
                    nc = room->userCount;
                    for (int i = 0; i < nc; i++)
                        notify_ids[i] = room->userIds[i];
                    freeChatRoom(room); free(room);
                }
            }

            int success = message ? deleteMessageById(messageId) : 0;

            sendDeleteResponse(sock, "DELETE_MESSAGE_RESPONSE", success,
                "messageId", messageId, notify_ids, nc);

            if (success) {
                cJSON* push = cJSON_CreateObject();
                cJSON_AddStringToObject(push, "type", "DELETE_MESSAGE_RESPONSE");
                cJSON_AddNumberToObject(push, "success", 1);
                cJSON_AddNumberToObject(push, "messageId", messageId);
                char* pt = cJSON_PrintUnformatted(push);
                cJSON_Delete(push);
                udp_push_to_list(pt, notify_ids, nc, db_user_id);
                free(pt);
            }

            if (message) { freeMessage(message); free(message); }
        }

        /* ── DELETE_CHATROOM ── */
        else if (strcmp(type, "DELETE_CHATROOM") == 0) {
            int chatRoomId = cJSON_GetObjectItem(req, "chatRoomId")->valueint;

            ChatRoom* room = getChatRoomById(chatRoomId);
            int notify_ids[1]; int nc = 0;

            int can = room &&
                room->userCount == 1 &&
                room->userIds[0] == room->coordinatorId;
            if (can) { notify_ids[0] = room->coordinatorId; nc = 1; }
            if (room) { freeChatRoom(room); free(room); }

            int success = can ? deleteChatRoomById(chatRoomId) : 0;

            sendDeleteResponse(sock, "DELETE_CHATROOM_RESPONSE", success,
                "chatRoomId", chatRoomId, notify_ids, nc);

            if (success) {
                cJSON* push = cJSON_CreateObject();
                cJSON_AddStringToObject(push, "type", "DELETE_CHATROOM_RESPONSE");
                cJSON_AddNumberToObject(push, "success", 1);
                cJSON_AddNumberToObject(push, "chatRoomId", chatRoomId);
                char* pt = cJSON_PrintUnformatted(push);
                cJSON_Delete(push);
                udp_push_to_list(pt, notify_ids, nc, db_user_id);
                free(pt);
            }
        }

        cJSON_Delete(req);
    }
}

/* ============================================================
   HIJO
   ============================================================ */
static void atender_cliente(int sock, const char* client_ip) {
    char username[64] = "";
    int uid = autenticar(sock, client_ip, username);
    if (uid < 0) { close(sock); exit(0); }
    printf("[uid=%d] Autenticado: %s\n", uid, username);

    procesar_lobby(sock, uid);

    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++)
        if (g_state->users[i].db_user_id == uid) {
            g_state->users[i].active = 0; break;
        }
    g_state->user_count--;
    pthread_mutex_unlock(&g_state->lock);

    close(sock);
    printf("[uid=%d] Fin\n", uid);
    exit(0);
}

/* ============================================================
   HILO UDP
   ============================================================ */
static void* hilo_udp(void* arg) {
    (void)arg;
    char buf[BUFSIZE];
    struct sockaddr_in src; socklen_t slen = sizeof(src);
    printf("[UDP] Puerto %d\n", UDP_PORT);
    while (1) {
        int n = recvfrom(g_udp_sd, buf, sizeof(buf) - 1, 0,
            (struct sockaddr*)&src, &slen);
        if (n > 0) { buf[n] = '\0'; printf("[UDP] %s", buf); }
    }
    return NULL;
}

/* ============================================================
   SIGNALS
   ============================================================ */
static void sig_chld(int s) { (void)s; while (waitpid(-1, NULL, WNOHANG) > 0); }
static void sig_int(int s) {
    (void)s;
    if (g_tcp_sd != -1) close(g_tcp_sd);
    if (g_udp_sd != -1) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */
int main(void) {
    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);

    /* UDP */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd < 0) { perror("udp socket"); exit(1); }
    struct sockaddr_in ua;
    memset(&ua, 0, sizeof(ua));
    ua.sin_family = AF_INET; ua.sin_addr.s_addr = INADDR_ANY;
    ua.sin_port = htons(UDP_PORT);
    if (bind(g_udp_sd, (struct sockaddr*)&ua, sizeof(ua)) < 0) {
        perror("udp bind"); exit(1);
    }
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp, NULL);
    pthread_detach(tid);

    /* TCP */
    g_tcp_sd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_sd < 0) { perror("tcp socket"); exit(1); }
    int opt = 1;
    setsockopt(g_tcp_sd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in ta;
    memset(&ta, 0, sizeof(ta));
    ta.sin_family = AF_INET; ta.sin_addr.s_addr = INADDR_ANY;
    ta.sin_port = htons(TCP_PORT);
    if (bind(g_tcp_sd, (struct sockaddr*)&ta, sizeof(ta)) < 0) {
        perror("tcp bind"); exit(1);
    }
    if (listen(g_tcp_sd, 10) < 0) { perror("listen"); exit(1); }

    signal(SIGCHLD, sig_chld);
    signal(SIGINT, sig_int);

    printf("[Servidor] TCP:%d  UDP:%d\n", TCP_PORT, UDP_PORT);

    while (1) {
        struct sockaddr_in ca; socklen_t clen = sizeof(ca);
        int cfd = accept(g_tcp_sd, (struct sockaddr*)&ca, &clen);
        if (cfd < 0) { perror("accept"); continue; }

        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &ca.sin_addr, ip, sizeof(ip));
        printf("[Padre] Conexion de %s\n", ip);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); close(cfd); continue; }
        if (pid == 0) { close(g_tcp_sd); atender_cliente(cfd, ip); }
        close(cfd);
    }

    return 0;
}