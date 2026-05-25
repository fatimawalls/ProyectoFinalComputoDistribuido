# Protocolo de Comunicación — Chat Distribuido
**Proyecto Final · Cómputo Distribuido**

---

## Tabla de contenidos

1. [Visión general](#1-visión-general)
2. [Formato de trama](#2-formato-de-trama)
3. [Convenciones](#3-convenciones)
4. [Comandos REQ_ — Cliente → Servidor](#4-comandos-req_--cliente--servidor)
5. [Respuestas RES_ — Servidor → Cliente](#5-respuestas-res_--servidor--cliente)
6. [Eventos EVT_ — Servidor → Cliente (broadcast)](#6-eventos-evt_--servidor--cliente-broadcast)
7. [Flujos completos](#7-flujos-completos)
8. [Cifrado de mensajes](#8-cifrado-de-mensajes)
9. [Códigos de error frecuentes](#9-códigos-de-error-frecuentes)
10. [Integración rápida en C](#10-integración-rápida-en-c)

---

## 1. Visión general

```
Navegador
   │  WebSocket (Socket.IO)
   ▼
web_server.py  ←──── este repo
   │  TCP · JSON · puerto 5000
   ▼
Servidor C  ←──── tú implementas esto
```

El servidor Python actúa como **gateway**: recibe eventos del navegador, los traduce a tramas JSON y las envía por TCP al servidor C. El servidor C procesa la lógica de negocio (usuarios, salas, mensajes cifrados) y responde con JSON.

**Cada cliente web abre su propia conexión TCP independiente al servidor C.**

---

## 2. Formato de trama

Cada mensaje es un objeto JSON en una sola línea, terminado con `\n`.

```
{"cmd":"NOMBRE","status":"ok|error","payload":{...}}\n
```

| Campo | Tipo | Descripción |
|---|---|---|
| `cmd` | string | Nombre del comando (ver secciones 4–6) |
| `status` | string | `"ok"` o `"error"`. **Solo en RES_**; ausente en REQ_ y EVT_ |
| `payload` | object | Parámetros específicos del comando |

> **Importante:** el servidor C debe leer hasta `\n` para delimitar cada trama. Un solo `recv()` puede contener múltiples tramas concatenadas.

---

## 3. Convenciones

| Prefijo | Dirección | Descripción |
|---|---|---|
| `REQ_` | Cliente → Servidor | Petición iniciada por el cliente |
| `RES_` | Servidor → Cliente | Respuesta directa a un REQ_ |
| `EVT_` | Servidor → Cliente | Evento espontáneo / broadcast |

- Los campos de texto (username, nickname, etc.) usan **UTF-8**.
- Los mensajes de chat se transmiten como **texto en claro** en el REQ_; el servidor los cifra antes de almacenarlos y los envía cifrados en base64 en RES_ y EVT_.
- Los timestamps (`ts`) son **Unix epoch en segundos** (entero).

---

## 4. Comandos REQ_ — Cliente → Servidor

### REQ_LOGIN
Autentica al usuario. Debe ser el primer comando tras conectar.

```json
{
  "cmd": "REQ_LOGIN",
  "payload": {
    "username": "jperez_root",
    "password": "s3cr3t"
  }
}
```

---

### REQ_LOGOUT
Cierra la sesión del usuario.

```json
{ "cmd": "REQ_LOGOUT", "payload": {} }
```

---

### REQ_LOBBY_LIST_USERS
Solicita la lista de usuarios online (excluye al solicitante).

```json
{ "cmd": "REQ_LOBBY_LIST_USERS", "payload": {} }
```

---

### REQ_LOBBY_LIST_ROOMS
Solicita la lista de todas las salas existentes.

```json
{ "cmd": "REQ_LOBBY_LIST_ROOMS", "payload": {} }
```

---

### REQ_CREATE_ROOM
Crea una nueva sala. El creador queda automáticamente como coordinador y primer miembro.

```json
{
  "cmd": "REQ_CREATE_ROOM",
  "payload": { "name": "dev-ops" }
}
```

---

### REQ_JOIN_ROOM
Envía una solicitud de ingreso a una sala. El coordinador debe aprobarla.

```json
{
  "cmd": "REQ_JOIN_ROOM",
  "payload": { "room_id": "dev-ops" }
}
```

---

### REQ_LEAVE_ROOM
El usuario abandona voluntariamente una sala.

```json
{
  "cmd": "REQ_LEAVE_ROOM",
  "payload": { "room_id": "dev-ops" }
}
```

---

### REQ_CHAT_SEND_MSG
Envía un mensaje a una sala. El texto va en claro; el servidor lo cifra.

```json
{
  "cmd": "REQ_CHAT_SEND_MSG",
  "payload": {
    "room_id": "general",
    "text": "Hola a todos"
  }
}
```

---

### REQ_CHAT_GET_HISTORY
Solicita el historial de mensajes de una sala.

```json
{
  "cmd": "REQ_CHAT_GET_HISTORY",
  "payload": { "room_id": "general" }
}
```

---

### REQ_COORD_LIST_REQUESTS
Lista las solicitudes de ingreso pendientes. Solo válido si el usuario es coordinador.

```json
{
  "cmd": "REQ_COORD_LIST_REQUESTS",
  "payload": { "room_id": "root-access" }
}
```

---

### REQ_COORD_ACCEPT_USER
Aprueba la solicitud de ingreso de un usuario.

```json
{
  "cmd": "REQ_COORD_ACCEPT_USER",
  "payload": { "room_id": "root-access", "username": "juan_dev" }
}
```

---

### REQ_COORD_REJECT_USER
Rechaza la solicitud de ingreso de un usuario.

```json
{
  "cmd": "REQ_COORD_REJECT_USER",
  "payload": { "room_id": "root-access", "username": "juan_dev" }
}
```

---

### REQ_COORD_KICK_USER
Expulsa a un miembro de la sala.

```json
{
  "cmd": "REQ_COORD_KICK_USER",
  "payload": { "room_id": "root-access", "username": "juan_dev" }
}
```

---

### REQ_COORD_LIST_MEMBERS
Lista los miembros actuales de una sala.

```json
{
  "cmd": "REQ_COORD_LIST_MEMBERS",
  "payload": { "room_id": "root-access" }
}
```

---

### REQ_COORD_DELETE_ROOM
Elimina una sala. Solo permitido si el coordinador es el único miembro.

```json
{
  "cmd": "REQ_COORD_DELETE_ROOM",
  "payload": { "room_id": "dev-ops" }
}
```

---

## 5. Respuestas RES_ — Servidor → Cliente

### RES_LOGIN

```json
// Éxito
{
  "cmd": "RES_LOGIN", "status": "ok",
  "payload": { "username": "jperez_root", "nickname": "jperez.sys" }
}

// Error
{
  "cmd": "RES_LOGIN", "status": "error",
  "payload": { "message": "Credenciales inválidas" }
}
```

---

### RES_LOBBY_USERS

```json
{
  "cmd": "RES_LOBBY_USERS", "status": "ok",
  "payload": {
    "users": [
      { "username": "maria_p", "nickname": "Maria_P", "online": true },
      { "username": "juan_dev", "nickname": "Juan_Dev", "online": false }
    ]
  }
}
```

---

### RES_LOBBY_ROOMS

```json
{
  "cmd": "RES_LOBBY_ROOMS", "status": "ok",
  "payload": {
    "rooms": [
      {
        "id": "general", "name": "general",
        "coordinator": "admin_root",
        "member_count": 3, "notifications": 0
      }
    ]
  }
}
```

---

### RES_CREATE_ROOM

```json
// Éxito
{
  "cmd": "RES_CREATE_ROOM", "status": "ok",
  "payload": { "id": "dev-ops", "name": "dev-ops", "coordinator": "maria_p" }
}

// Error
{
  "cmd": "RES_CREATE_ROOM", "status": "error",
  "payload": { "message": "Nombre ya en uso" }
}
```

---

### RES_JOIN_ROOM
Solo acuse de recibo. La aprobación real llega como `EVT_JOIN_APPROVED`.

```json
{
  "cmd": "RES_JOIN_ROOM", "status": "ok",
  "payload": {
    "room_id": "root-access",
    "message": "Solicitud enviada al coordinador"
  }
}
```

---

### RES_CHAT_HISTORY
Los mensajes se entregan cifrados en base64.

```json
{
  "cmd": "RES_CHAT_HISTORY", "status": "ok",
  "payload": {
    "room_id": "general",
    "messages": [
      { "sender": "Admin_Root", "text": "<cifrado_b64>", "ts": 1715000000 },
      { "sender": "Maria_P",   "text": "<cifrado_b64>", "ts": 1715000060 }
    ]
  }
}
```

---

### RES_COORD_REQUESTS

```json
{
  "cmd": "RES_COORD_REQUESTS", "status": "ok",
  "payload": {
    "room_id": "root-access",
    "requests": [
      { "username": "juan_dev", "nickname": "Juan_Dev" }
    ]
  }
}
```

---

### RES_COORD_MEMBERS

```json
{
  "cmd": "RES_COORD_MEMBERS", "status": "ok",
  "payload": {
    "room_id": "root-access",
    "members": [
      { "username": "jperez_root", "nickname": "jperez.sys", "online": true },
      { "username": "ana_ops",     "nickname": "Ana_Ops",    "online": true }
    ]
  }
}
```

---

### RES_COORD_DELETE_ROOM

```json
// Éxito
{ "cmd": "RES_COORD_DELETE_ROOM", "status": "ok",
  "payload": { "room_id": "dev-ops" } }

// Error
{ "cmd": "RES_COORD_DELETE_ROOM", "status": "error",
  "payload": { "message": "Sala tiene más miembros" } }
```

> Los demás RES_ (`RES_LOGOUT`, `RES_LEAVE_ROOM`, `RES_COORD_ACCEPT`, `RES_COORD_REJECT`, `RES_COORD_KICK`) siguen la misma estructura: `status: "ok"` y el `room_id` / `username` afectado en el payload.

---

## 6. Eventos EVT_ — Servidor → Cliente (broadcast)

Los eventos no tienen `status`. El servidor los emite espontáneamente a uno o varios clientes.

### EVT_NEW_MSG
Broadcast a todos los miembros de la sala cuando llega un mensaje nuevo.

```json
{
  "cmd": "EVT_NEW_MSG",
  "payload": {
    "room_id": "general",
    "sender":  "jperez.sys",
    "text":    "<cifrado_b64>",
    "ts":      1715000120
  }
}
```

---

### EVT_JOIN_REQUEST
Enviado **solo al coordinador** cuando alguien solicita unirse.

```json
{
  "cmd": "EVT_JOIN_REQUEST",
  "payload": {
    "room_id":  "root-access",
    "username": "juan_dev",
    "nickname": "Juan_Dev"
  }
}
```

---

### EVT_JOIN_APPROVED / EVT_JOIN_REJECTED
Enviado **al solicitante** con el resultado de su petición.

```json
{
  "cmd": "EVT_JOIN_APPROVED",
  "payload": { "room_id": "root-access", "room_name": "root-access" }
}
```

---

### EVT_USER_JOINED
Broadcast a la sala cuando un nuevo miembro es aceptado.

```json
{
  "cmd": "EVT_USER_JOINED",
  "payload": {
    "room_id":  "root-access",
    "username": "juan_dev",
    "nickname": "Juan_Dev"
  }
}
```

---

### EVT_USER_LEFT
Broadcast a la sala cuando alguien sale o es expulsado.

```json
{
  "cmd": "EVT_USER_LEFT",
  "payload": {
    "room_id":  "root-access",
    "username": "juan_dev",
    "reason":   "left"
  }
}
```

`reason` puede ser `"left"` (voluntario) o `"kicked"` (expulsado por coordinador).

---

### EVT_USER_ONLINE / EVT_USER_OFFLINE
Broadcast global cuando un usuario conecta o desconecta del sistema.

```json
{
  "cmd": "EVT_USER_ONLINE",
  "payload": { "username": "juan_dev", "nickname": "Juan_Dev" }
}
```

---

### EVT_ROOM_DELETED
Broadcast a los miembros cuando el coordinador elimina la sala.

```json
{
  "cmd": "EVT_ROOM_DELETED",
  "payload": { "room_id": "dev-ops", "room_name": "dev-ops" }
}
```

---

## 7. Flujos completos

### Login y carga del lobby

```
Cliente                          Servidor C
  │                                   │
  │── REQ_LOGIN ──────────────────────▶│
  │◀── RES_LOGIN (ok) ────────────────│
  │                                   │
  │── REQ_LOBBY_LIST_ROOMS ───────────▶│
  │◀── RES_LOBBY_ROOMS ───────────────│
  │                                   │
  │── REQ_LOBBY_LIST_USERS ───────────▶│
  │◀── RES_LOBBY_USERS ───────────────│
```

---

### Solicitud de ingreso a sala

```
Solicitante                  Servidor C               Coordinador
  │                               │                        │
  │── REQ_JOIN_ROOM ──────────────▶│                        │
  │◀── RES_JOIN_ROOM (ok) ────────│                        │
  │                               │── EVT_JOIN_REQUEST ────▶│
  │                               │                        │
  │                               │◀── REQ_COORD_ACCEPT ───│
  │◀── EVT_JOIN_APPROVED ─────────│                        │
  │◀── EVT_USER_JOINED ───────────│ (broadcast sala)       │
```

---

### Envío de mensaje

```
Remitente                    Servidor C              Otros miembros
  │                               │                        │
  │── REQ_CHAT_SEND_MSG ──────────▶│                        │
  │                               │  cifra y almacena      │
  │◀── EVT_NEW_MSG ───────────────│── EVT_NEW_MSG ─────────▶│
```

> El servidor envía `EVT_NEW_MSG` a **todos** los miembros, incluido el remitente. El cliente web usa esto para confirmar la entrega.

---

## 8. Cifrado de mensajes

- Los mensajes se almacenan **cifrados** en el servidor.
- El campo `text` en `EVT_NEW_MSG` y `RES_CHAT_HISTORY` llega como **base64**.
- El descifrado ocurre en el cliente (navegador o desktop); el servidor C nunca almacena texto en claro.
- El algoritmo de cifrado queda a decisión del equipo (sugerido: AES-256-GCM con clave derivada de la sala).

> Para las pruebas con `mock_c_server.py` el texto viaja en claro. Integrar el cifrado real es tarea del servidor C.

---

## 9. Códigos de error frecuentes

| Comando | `message` posible | Causa |
|---|---|---|
| `RES_LOGIN` | `"Credenciales inválidas"` | Username o password incorrectos |
| `RES_CREATE_ROOM` | `"Nombre ya en uso"` | Ya existe una sala con ese id |
| `RES_JOIN_ROOM` | `"Sala no encontrada"` | `room_id` inexistente |
| `RES_JOIN_ROOM` | `"Ya eres miembro"` | El usuario ya pertenece a la sala |
| `RES_COORD_DELETE_ROOM` | `"Sala tiene más miembros"` | No se puede borrar con miembros activos |

---

## 10. Integración rápida en C

Tu servidor C debe:

1. **Aceptar conexiones TCP** en `127.0.0.1:5000`.
2. **Leer hasta `\n`** para delimitar cada trama (un `recv` puede traer varias).
3. **Parsear el JSON** (recomendado: [cJSON](https://github.com/DaveGamble/cJSON), un solo `.c`).
4. **Usar `protocol.h` / `protocol.c`** del repositorio — ya incluyen `proto_recv()`, `proto_send()` y helpers para cada comando.

Ejemplo mínimo de loop de lectura en C:

```c
#include "protocol.h"

void handle_client(int fd) {
    ProtoFrame frame;
    while (proto_recv(fd, &frame) > 0) {
        if (strcmp(frame.cmd, CMD_REQ_LOGIN) == 0) {
            // parsear frame.payload_json con cJSON
            // validar credenciales
            proto_send_login_ok(fd, username, nickname);
        }
        else if (strcmp(frame.cmd, CMD_REQ_LOBBY_LIST_ROOMS) == 0) {
            // construir JSON de salas
            proto_send_lobby_rooms(fd, rooms_json);
        }
        // ... resto de comandos
    }
}
```

El archivo `mock_c_server.py` es la referencia de comportamiento exacto: cada flujo, error y broadcast está implementado ahí y puede usarse para comparar la salida del servidor C real.
