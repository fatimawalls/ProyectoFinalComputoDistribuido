#ifndef PROTOCOL_H
#define PROTOCOL_H

#include "cJSON.h"
#include "models.h"
void sendJson(
    int clientSocket,
    cJSON *json
);

void sendAuthResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username
);

void sendCreateAccountResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username
);

void sendSyncStart(
    int clientSocket
);

void sendSyncEnd(
    int clientSocket
);

void sendChatRoomJson(
    int clientSocket,
    ChatRoom *room
);

void sendChatUserJson(
    int clientSocket,
    int id,
    const char *name
);

void sendMessageJson(
    int clientSocket,
    int id,
    int userId,
    int chatRoomId,
    const char *text
);

void sendNewMessageResponse(
    int clientSocket,
    int success,
    Message *message,
    int *notifyUsers,
    int notifyCount
);

void sendNewChatRoomResponse(
    int clientSocket,
    int success,
    ChatRoom *room,
    int *notifyUsers,
    int notifyCount
);
void sendUserChatRelationResponse(
    int clientSocket,
    const char *responseType,
    int success,
    int userId,
    int chatRoomId,
    User *chatUser,
    ChatRoom *room,
    int *notifyUsers,
    int notifyCount
);

void sendDeleteResponse(
    int clientSocket,
    const char *responseType,
    int success,
    const char *idFieldName,
    int objectId,
    int *notifyUsers,
    int notifyCount
);
#endif