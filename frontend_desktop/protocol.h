/* ==========================================================================
 * protocol.h  —  Protocolo JSON/TCP para el servidor de chat distribuido
 * ==========================================================================
 * Arquitectura:
 *   Navegador <--SocketIO--> web_server.py <--TCP/JSON--> servidor C
 *
 * Formato de trama:
 *   Cada mensaje es un objeto JSON terminado en '\n'.
 *   { "cmd": "NOMBRE_COMANDO", "payload": { ... } }
 *
 * Prefijos de comandos:
 *   REQ_   → Cliente  → Servidor  (petición)
 *   RES_   → Servidor → Cliente   (respuesta a una petición)
 *   EVT_   → Servidor → Cliente   (evento espontáneo / broadcast)
 * ========================================================================== */

#ifndef PROTOCOL_H
#define PROTOCOL_H

/* ── Longitudes máximas ─────────────────────────────────────────────── */
#define PROTO_MAX_CMD       32
#define PROTO_MAX_USERNAME  64
#define PROTO_MAX_NICKNAME  64
#define PROTO_MAX_PASSWORD  128
#define PROTO_MAX_ROOM_ID   64
#define PROTO_MAX_ROOM_NAME 64
#define PROTO_MAX_MSG       2048
#define PROTO_MAX_FRAME     8192   /* tamaño máximo de una trama JSON */

/* ── Códigos de estado (campo "status" en RES_) ──────────────────────── */
#define PROTO_STATUS_OK      "ok"
#define PROTO_STATUS_ERROR   "error"

/* ══════════════════════════════════════════════════════════════════════
 * COMANDOS  —  Cliente → Servidor  (REQ_)
 * ══════════════════════════════════════════════════════════════════════
 *
 * REQ_LOGIN
 *   { "cmd":"REQ_LOGIN",
 *     "payload":{ "username":"...", "password":"..." } }
 *
 * REQ_LOGOUT
 *   { "cmd":"REQ_LOGOUT", "payload":{} }
 *
 * REQ_LOBBY_LIST_USERS
 *   Lista usuarios online (excluye al solicitante).
 *   { "cmd":"REQ_LOBBY_LIST_USERS", "payload":{} }
 *
 * REQ_LOBBY_LIST_ROOMS
 *   Lista todas las salas existentes.
 *   { "cmd":"REQ_LOBBY_LIST_ROOMS", "payload":{} }
 *
 * REQ_CREATE_ROOM
 *   { "cmd":"REQ_CREATE_ROOM",
 *     "payload":{ "name":"..." } }
 *
 * REQ_JOIN_ROOM
 *   Solicita unirse a una sala (el coordinador debe aprobar).
 *   { "cmd":"REQ_JOIN_ROOM",
 *     "payload":{ "room_id":"..." } }
 *
 * REQ_LEAVE_ROOM
 *   { "cmd":"REQ_LEAVE_ROOM",
 *     "payload":{ "room_id":"..." } }
 *
 * REQ_CHAT_SEND_MSG
 *   { "cmd":"REQ_CHAT_SEND_MSG",
 *     "payload":{ "room_id":"...", "text":"..." } }
 *
 * REQ_CHAT_GET_HISTORY
 *   { "cmd":"REQ_CHAT_GET_HISTORY",
 *     "payload":{ "room_id":"..." } }
 *
 * REQ_COORD_LIST_REQUESTS
 *   Solo si el usuario es coordinador de esa sala.
 *   { "cmd":"REQ_COORD_LIST_REQUESTS",
 *     "payload":{ "room_id":"..." } }
 *
 * REQ_COORD_ACCEPT_USER
 *   { "cmd":"REQ_COORD_ACCEPT_USER",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * REQ_COORD_REJECT_USER
 *   { "cmd":"REQ_COORD_REJECT_USER",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * REQ_COORD_KICK_USER
 *   { "cmd":"REQ_COORD_KICK_USER",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * REQ_COORD_LIST_MEMBERS
 *   { "cmd":"REQ_COORD_LIST_MEMBERS",
 *     "payload":{ "room_id":"..." } }
 *
 * REQ_COORD_DELETE_ROOM
 *   Solo si el coordinador es el único miembro.
 *   { "cmd":"REQ_COORD_DELETE_ROOM",
 *     "payload":{ "room_id":"..." } }
 * ══════════════════════════════════════════════════════════════════════ */

/* ── Nombres de comandos REQ_ ──────────────────────────────────────── */
#define CMD_REQ_LOGIN                "REQ_LOGIN"
#define CMD_REQ_LOGOUT               "REQ_LOGOUT"
#define CMD_REQ_LOBBY_LIST_USERS     "REQ_LOBBY_LIST_USERS"
#define CMD_REQ_LOBBY_LIST_ROOMS     "REQ_LOBBY_LIST_ROOMS"
#define CMD_REQ_CREATE_ROOM          "REQ_CREATE_ROOM"
#define CMD_REQ_JOIN_ROOM            "REQ_JOIN_ROOM"
#define CMD_REQ_LEAVE_ROOM           "REQ_LEAVE_ROOM"
#define CMD_REQ_CHAT_SEND_MSG        "REQ_CHAT_SEND_MSG"
#define CMD_REQ_CHAT_GET_HISTORY     "REQ_CHAT_GET_HISTORY"
#define CMD_REQ_COORD_LIST_REQUESTS  "REQ_COORD_LIST_REQUESTS"
#define CMD_REQ_COORD_ACCEPT_USER    "REQ_COORD_ACCEPT_USER"
#define CMD_REQ_COORD_REJECT_USER    "REQ_COORD_REJECT_USER"
#define CMD_REQ_COORD_KICK_USER      "REQ_COORD_KICK_USER"
#define CMD_REQ_COORD_LIST_MEMBERS   "REQ_COORD_LIST_MEMBERS"
#define CMD_REQ_COORD_DELETE_ROOM    "REQ_COORD_DELETE_ROOM"

/* ══════════════════════════════════════════════════════════════════════
 * RESPUESTAS  —  Servidor → Cliente  (RES_)
 * ══════════════════════════════════════════════════════════════════════
 *
 * RES_LOGIN
 *   OK  : { "cmd":"RES_LOGIN", "status":"ok",
 *            "payload":{ "username":"...", "nickname":"..." } }
 *   ERR : { "cmd":"RES_LOGIN", "status":"error",
 *            "payload":{ "message":"Credenciales inválidas" } }
 *
 * RES_LOGOUT
 *   { "cmd":"RES_LOGOUT", "status":"ok", "payload":{} }
 *
 * RES_LOBBY_USERS
 *   { "cmd":"RES_LOBBY_USERS", "status":"ok",
 *     "payload":{ "users":[
 *       { "username":"...", "nickname":"...", "online": true }, ...
 *     ]}}
 *
 * RES_LOBBY_ROOMS
 *   { "cmd":"RES_LOBBY_ROOMS", "status":"ok",
 *     "payload":{ "rooms":[
 *       { "id":"...", "name":"...", "coordinator":"...",
 *         "member_count": 3, "notifications": 1 }, ...
 *     ]}}
 *
 * RES_CREATE_ROOM
 *   OK  : { "cmd":"RES_CREATE_ROOM", "status":"ok",
 *            "payload":{ "id":"...", "name":"...", "coordinator":"..." } }
 *   ERR : { "cmd":"RES_CREATE_ROOM", "status":"error",
 *            "payload":{ "message":"Nombre ya en uso" } }
 *
 * RES_JOIN_ROOM
 *   (Acuse de recibo — aprobación llega como EVT_JOIN_APPROVED)
 *   { "cmd":"RES_JOIN_ROOM", "status":"ok",
 *     "payload":{ "room_id":"...", "message":"Solicitud enviada al coordinador" } }
 *
 * RES_LEAVE_ROOM
 *   { "cmd":"RES_LEAVE_ROOM", "status":"ok",
 *     "payload":{ "room_id":"..." } }
 *
 * RES_CHAT_HISTORY
 *   Los mensajes vienen cifrados; el cliente los descifra.
 *   { "cmd":"RES_CHAT_HISTORY", "status":"ok",
 *     "payload":{ "room_id":"...", "messages":[
 *       { "sender":"...", "text":"<cifrado_b64>", "ts": 1715000000 }, ...
 *     ]}}
 *
 * RES_COORD_REQUESTS
 *   { "cmd":"RES_COORD_REQUESTS", "status":"ok",
 *     "payload":{ "room_id":"...", "requests":[
 *       { "username":"...", "nickname":"..." }, ...
 *     ]}}
 *
 * RES_COORD_ACCEPT
 *   { "cmd":"RES_COORD_ACCEPT", "status":"ok",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * RES_COORD_REJECT
 *   { "cmd":"RES_COORD_REJECT", "status":"ok",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * RES_COORD_KICK
 *   { "cmd":"RES_COORD_KICK", "status":"ok",
 *     "payload":{ "room_id":"...", "username":"..." } }
 *
 * RES_COORD_MEMBERS
 *   { "cmd":"RES_COORD_MEMBERS", "status":"ok",
 *     "payload":{ "room_id":"...", "members":[
 *       { "username":"...", "nickname":"...", "online": true }, ...
 *     ]}}
 *
 * RES_COORD_DELETE_ROOM
 *   OK  : { "cmd":"RES_COORD_DELETE_ROOM", "status":"ok",
 *            "payload":{ "room_id":"..." } }
 *   ERR : { "cmd":"RES_COORD_DELETE_ROOM", "status":"error",
 *            "payload":{ "message":"Sala tiene más miembros" } }
 * ══════════════════════════════════════════════════════════════════════ */

#define CMD_RES_LOGIN               "RES_LOGIN"
#define CMD_RES_LOGOUT              "RES_LOGOUT"
#define CMD_RES_LOBBY_USERS         "RES_LOBBY_USERS"
#define CMD_RES_LOBBY_ROOMS         "RES_LOBBY_ROOMS"
#define CMD_RES_CREATE_ROOM         "RES_CREATE_ROOM"
#define CMD_RES_JOIN_ROOM           "RES_JOIN_ROOM"
#define CMD_RES_LEAVE_ROOM          "RES_LEAVE_ROOM"
#define CMD_RES_CHAT_HISTORY        "RES_CHAT_HISTORY"
#define CMD_RES_COORD_REQUESTS      "RES_COORD_REQUESTS"
#define CMD_RES_COORD_ACCEPT        "RES_COORD_ACCEPT"
#define CMD_RES_COORD_REJECT        "RES_COORD_REJECT"
#define CMD_RES_COORD_KICK          "RES_COORD_KICK"
#define CMD_RES_COORD_MEMBERS       "RES_COORD_MEMBERS"
#define CMD_RES_COORD_DELETE_ROOM   "RES_COORD_DELETE_ROOM"

/* ══════════════════════════════════════════════════════════════════════
 * EVENTOS ESPONTÁNEOS  —  Servidor → Cliente  (EVT_)
 * ══════════════════════════════════════════════════════════════════════
 *
 * EVT_NEW_MSG
 *   Broadcast a todos los miembros de una sala cuando llega un mensaje.
 *   { "cmd":"EVT_NEW_MSG",
 *     "payload":{ "room_id":"...", "sender":"...", "text":"<cifrado_b64>",
 *                 "ts": 1715000000 } }
 *
 * EVT_USER_JOINED
 *   Un usuario fue aceptado y entró a la sala.
 *   { "cmd":"EVT_USER_JOINED",
 *     "payload":{ "room_id":"...", "username":"...", "nickname":"..." } }
 *
 * EVT_USER_LEFT
 *   Un usuario abandonó o fue expulsado de la sala.
 *   { "cmd":"EVT_USER_LEFT",
 *     "payload":{ "room_id":"...", "username":"...", "reason":"left"|"kicked" } }
 *
 * EVT_JOIN_APPROVED
 *   Notifica al solicitante que el coordinador lo aceptó.
 *   { "cmd":"EVT_JOIN_APPROVED",
 *     "payload":{ "room_id":"...", "room_name":"..." } }
 *
 * EVT_JOIN_REJECTED
 *   Notifica al solicitante que fue rechazado.
 *   { "cmd":"EVT_JOIN_REJECTED",
 *     "payload":{ "room_id":"...", "room_name":"..." } }
 *
 * EVT_JOIN_REQUEST
 *   Notifica al coordinador que hay una nueva solicitud de ingreso.
 *   { "cmd":"EVT_JOIN_REQUEST",
 *     "payload":{ "room_id":"...", "username":"...", "nickname":"..." } }
 *
 * EVT_ROOM_DELETED
 *   Broadcast a miembros cuando el coordinador borra la sala.
 *   { "cmd":"EVT_ROOM_DELETED",
 *     "payload":{ "room_id":"...", "room_name":"..." } }
 *
 * EVT_USER_ONLINE
 *   Un usuario conectó al sistema.
 *   { "cmd":"EVT_USER_ONLINE",
 *     "payload":{ "username":"...", "nickname":"..." } }
 *
 * EVT_USER_OFFLINE
 *   Un usuario se desconectó.
 *   { "cmd":"EVT_USER_OFFLINE",
 *     "payload":{ "username":"...", "nickname":"..." } }
 * ══════════════════════════════════════════════════════════════════════ */

#define CMD_EVT_NEW_MSG         "EVT_NEW_MSG"
#define CMD_EVT_USER_JOINED     "EVT_USER_JOINED"
#define CMD_EVT_USER_LEFT       "EVT_USER_LEFT"
#define CMD_EVT_JOIN_APPROVED   "EVT_JOIN_APPROVED"
#define CMD_EVT_JOIN_REJECTED   "EVT_JOIN_REJECTED"
#define CMD_EVT_JOIN_REQUEST    "EVT_JOIN_REQUEST"
#define CMD_EVT_ROOM_DELETED    "EVT_ROOM_DELETED"
#define CMD_EVT_USER_ONLINE     "EVT_USER_ONLINE"
#define CMD_EVT_USER_OFFLINE    "EVT_USER_OFFLINE"

/* ── Struct auxiliar para leer/escribir tramas ───────────────────────── */
typedef struct {
    char cmd[PROTO_MAX_CMD];
    char status[8];        /* "ok" | "error" | "" (vacío en REQ_) */
    char payload_json[PROTO_MAX_FRAME - 64];  /* payload crudo como JSON string */
} ProtoFrame;

/* ── Declaraciones de funciones de utilidad (implementadas en protocol.c) */

/**
 * proto_send  —  Serializa y envía una trama JSON por el socket fd.
 * @cmd     : nombre del comando (ej. CMD_REQ_LOGIN)
 * @status  : PROTO_STATUS_OK / PROTO_STATUS_ERROR / "" para REQ_
 * @payload : objeto JSON del payload como string (sin llaves externas NO,
 *            aquí sí se incluyen, ej: "{\"username\":\"bob\"}")
 * Retorna 0 en éxito, -1 en error.
 */
int proto_send(int fd, const char *cmd, const char *status, const char *payload);

/**
 * proto_recv  —  Lee una trama completa (terminada en '\n') del socket fd.
 * Llena la estructura ProtoFrame.
 * Retorna bytes leídos, 0 en cierre de conexión, -1 en error.
 */
int proto_recv(int fd, ProtoFrame *frame);

/**
 * proto_build_error  —  Construye una trama de error estándar.
 * @cmd     : comando de respuesta (ej. CMD_RES_LOGIN)
 * @message : mensaje de error legible
 * Retorna puntero a buffer estático (no thread-safe); copiar si es necesario.
 */
const char *proto_build_error(const char *cmd, const char *message);

#endif /* PROTOCOL_H */
