/* ==========================================================================
 * protocol.c  —  Implementación de utilidades del protocolo JSON/TCP
 * ==========================================================================
 * Dependencia: cJSON  (https://github.com/DaveGamble/cJSON)
 *   Compilar con: gcc -o server server.c protocol.c cJSON.c -lpthread
 * ========================================================================== */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include "protocol.h"

/* cJSON es una biblioteca de un solo archivo; inclúyela en tu proyecto.
 * Si prefieres una biblioteca diferente (jansson, yyjson), reemplaza
 * únicamente estas funciones. */
#include "cJSON.h"

/* ── Buffer estático para proto_build_error ─────────────────────────── */
static char _err_buf[PROTO_MAX_FRAME];

/* ─────────────────────────────────────────────────────────────────────
 * proto_send
 * Construye  {"cmd":"...", "status":"...", "payload":{...}}\n
 * y lo escribe completo en el socket fd.
 * ───────────────────────────────────────────────────────────────────── */
int proto_send(int fd, const char *cmd, const char *status, const char *payload)
{
    char frame[PROTO_MAX_FRAME];
    int  n;

    /* Si no hay status (REQ_) lo omitimos del JSON */
    if (status == NULL || status[0] == '\0') {
        n = snprintf(frame, sizeof(frame),
                     "{\"cmd\":\"%s\",\"payload\":%s}\n",
                     cmd, payload ? payload : "{}");
    } else {
        n = snprintf(frame, sizeof(frame),
                     "{\"cmd\":\"%s\",\"status\":\"%s\",\"payload\":%s}\n",
                     cmd, status, payload ? payload : "{}");
    }

    if (n <= 0 || n >= (int)sizeof(frame)) {
        fprintf(stderr, "[proto_send] frame demasiado grande para cmd=%s\n", cmd);
        return -1;
    }

    /* write() completo (maneja EINTR) */
    ssize_t sent = 0, total = n;
    while (sent < total) {
        ssize_t w = write(fd, frame + sent, total - sent);
        if (w < 0) {
            if (errno == EINTR) continue;
            perror("[proto_send] write");
            return -1;
        }
        sent += w;
    }
    return 0;
}

/* ─────────────────────────────────────────────────────────────────────
 * proto_recv
 * Lee byte a byte hasta encontrar '\n'.
 * Parsea el JSON y llena ProtoFrame.
 * ───────────────────────────────────────────────────────────────────── */
int proto_recv(int fd, ProtoFrame *frame)
{
    char    buf[PROTO_MAX_FRAME];
    int     pos = 0;
    ssize_t r;

    memset(frame, 0, sizeof(*frame));

    /* Leer hasta '\n' o buffer lleno */
    while (pos < (int)sizeof(buf) - 1) {
        r = read(fd, buf + pos, 1);
        if (r == 0) return 0;          /* conexión cerrada */
        if (r < 0) {
            if (errno == EINTR) continue;
            perror("[proto_recv] read");
            return -1;
        }
        if (buf[pos] == '\n') { buf[pos] = '\0'; break; }
        pos++;
    }

    if (pos == 0) return 0;

    /* Parsear JSON */
    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        fprintf(stderr, "[proto_recv] JSON inválido: %s\n", buf);
        return -1;
    }

    /* Extraer "cmd" */
    cJSON *j_cmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");
    if (cJSON_IsString(j_cmd))
        strncpy(frame->cmd, j_cmd->valuestring, PROTO_MAX_CMD - 1);

    /* Extraer "status" (opcional) */
    cJSON *j_status = cJSON_GetObjectItemCaseSensitive(root, "status");
    if (cJSON_IsString(j_status))
        strncpy(frame->status, j_status->valuestring, sizeof(frame->status) - 1);

    /* Serializar "payload" de vuelta a JSON string para que el handler lo procese */
    cJSON *j_payload = cJSON_GetObjectItemCaseSensitive(root, "payload");
    if (j_payload) {
        char *payload_str = cJSON_PrintUnformatted(j_payload);
        if (payload_str) {
            strncpy(frame->payload_json, payload_str,
                    sizeof(frame->payload_json) - 1);
            free(payload_str);
        }
    }

    cJSON_Delete(root);
    return pos + 1;
}

/* ─────────────────────────────────────────────────────────────────────
 * proto_build_error
 * ───────────────────────────────────────────────────────────────────── */
const char *proto_build_error(const char *cmd, const char *message)
{
    snprintf(_err_buf, sizeof(_err_buf),
             "{\"cmd\":\"%s\",\"status\":\"error\","
             "\"payload\":{\"message\":\"%s\"}}\n",
             cmd, message);
    return _err_buf;
}

/* ═══════════════════════════════════════════════════════════════════════
 * HELPERS DE CONSTRUCCIÓN DE PAYLOADS
 * Funciones convenientes para construir los payloads JSON de cada
 * respuesta/evento sin escribir snprintf manualmente en cada handler.
 * ═══════════════════════════════════════════════════════════════════════ */

/* ── RES_LOGIN OK ────────────────────────────────────────────────────── */
int proto_send_login_ok(int fd, const char *username, const char *nickname)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"username\":\"%s\",\"nickname\":\"%s\"}",
             username, nickname);
    return proto_send(fd, CMD_RES_LOGIN, PROTO_STATUS_OK, payload);
}

/* ── RES_LOBBY_ROOMS ─────────────────────────────────────────────────── */
/*
 * rooms_json debe ser un array JSON ya serializado, ej:
 * "[{\"id\":\"general\",\"name\":\"general\",\"coordinator\":\"admin_root\","
 *   "\"member_count\":3,\"notifications\":0}]"
 */
int proto_send_lobby_rooms(int fd, const char *rooms_json)
{
    char payload[PROTO_MAX_FRAME - 64];
    snprintf(payload, sizeof(payload), "{\"rooms\":%s}", rooms_json);
    return proto_send(fd, CMD_RES_LOBBY_ROOMS, PROTO_STATUS_OK, payload);
}

/* ── RES_LOBBY_USERS ─────────────────────────────────────────────────── */
int proto_send_lobby_users(int fd, const char *users_json)
{
    char payload[PROTO_MAX_FRAME - 64];
    snprintf(payload, sizeof(payload), "{\"users\":%s}", users_json);
    return proto_send(fd, CMD_RES_LOBBY_USERS, PROTO_STATUS_OK, payload);
}

/* ── RES_CHAT_HISTORY ────────────────────────────────────────────────── */
int proto_send_chat_history(int fd, const char *room_id, const char *msgs_json)
{
    char payload[PROTO_MAX_FRAME - 64];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"messages\":%s}", room_id, msgs_json);
    return proto_send(fd, CMD_RES_CHAT_HISTORY, PROTO_STATUS_OK, payload);
}

/* ── EVT_NEW_MSG ─────────────────────────────────────────────────────── */
int proto_send_evt_new_msg(int fd, const char *room_id,
                           const char *sender, const char *text_b64,
                           long ts)
{
    char payload[PROTO_MAX_FRAME - 64];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"sender\":\"%s\","
             "\"text\":\"%s\",\"ts\":%ld}",
             room_id, sender, text_b64, ts);
    return proto_send(fd, CMD_EVT_NEW_MSG, "", payload);
}

/* ── EVT_JOIN_REQUEST  (al coordinador) ─────────────────────────────── */
int proto_send_evt_join_request(int fd, const char *room_id,
                                const char *username, const char *nickname)
{
    char payload[512];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"username\":\"%s\",\"nickname\":\"%s\"}",
             room_id, username, nickname);
    return proto_send(fd, CMD_EVT_JOIN_REQUEST, "", payload);
}

/* ── EVT_JOIN_APPROVED / EVT_JOIN_REJECTED  (al solicitante) ────────── */
int proto_send_evt_join_result(int fd, int approved,
                               const char *room_id, const char *room_name)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"room_name\":\"%s\"}",
             room_id, room_name);
    const char *cmd = approved ? CMD_EVT_JOIN_APPROVED : CMD_EVT_JOIN_REJECTED;
    return proto_send(fd, cmd, "", payload);
}

/* ── EVT_USER_JOINED / EVT_USER_LEFT  (broadcast a sala) ────────────── */
int proto_send_evt_user_joined(int fd, const char *room_id,
                               const char *username, const char *nickname)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"username\":\"%s\",\"nickname\":\"%s\"}",
             room_id, username, nickname);
    return proto_send(fd, CMD_EVT_USER_JOINED, "", payload);
}

int proto_send_evt_user_left(int fd, const char *room_id,
                             const char *username, const char *reason)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"username\":\"%s\",\"reason\":\"%s\"}",
             room_id, username, reason);
    return proto_send(fd, CMD_EVT_USER_LEFT, "", payload);
}

/* ── EVT_USER_ONLINE / EVT_USER_OFFLINE  (broadcast global) ─────────── */
int proto_send_evt_user_presence(int fd, int is_online,
                                 const char *username, const char *nickname)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"username\":\"%s\",\"nickname\":\"%s\"}",
             username, nickname);
    const char *cmd = is_online ? CMD_EVT_USER_ONLINE : CMD_EVT_USER_OFFLINE;
    return proto_send(fd, cmd, "", payload);
}

/* ── EVT_ROOM_DELETED ────────────────────────────────────────────────── */
int proto_send_evt_room_deleted(int fd, const char *room_id,
                                const char *room_name)
{
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"room_id\":\"%s\",\"room_name\":\"%s\"}",
             room_id, room_name);
    return proto_send(fd, CMD_EVT_ROOM_DELETED, "", payload);
}
