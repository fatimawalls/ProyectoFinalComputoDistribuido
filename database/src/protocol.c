#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <sys/socket.h>
#include "models.h"
#include "protocol.h"

void sendJson(
    int clientSocket,
    cJSON *json
)
{
    char *text =
        cJSON_PrintUnformatted(json);

    send(
        clientSocket,
        text,
        strlen(text),
        0
    );

    send(
        clientSocket,
        "\n",
        1,
        0
    );

    free(text);
}


static cJSON *chatRoomPayload(ChatRoom *room)
{
    cJSON *chat = cJSON_CreateObject();

    cJSON_AddNumberToObject(chat, "id", room->id);
    cJSON_AddStringToObject(chat, "name", room->name);
    cJSON_AddNumberToObject(chat, "coordinatorId", room->coordinatorId);

    cJSON *users = cJSON_CreateArray();
    for(int i = 0; i < room->userCount; i++)
    {
        cJSON_AddItemToArray(users, cJSON_CreateNumber(room->userIds[i]));
    }
    cJSON_AddItemToObject(chat, "userIds", users);

    cJSON *messages = cJSON_CreateArray();
    for(int i = 0; i < room->messageCount; i++)
    {
        cJSON_AddItemToArray(messages, cJSON_CreateNumber(room->messageIds[i]));
    }
    cJSON_AddItemToObject(chat, "messageIds", messages);

    cJSON *requests = cJSON_CreateArray();
    for(int i = 0; i < room->requestCount; i++)
    {
        cJSON_AddItemToArray(requests, cJSON_CreateNumber(room->requestIds[i]));
    }
    cJSON_AddItemToObject(chat, "requestIds", requests);

    return chat;
}

static cJSON *userPayload(User *user)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddNumberToObject(json, "id", user->id);
    cJSON_AddStringToObject(json, "username", user->name);
    cJSON_AddStringToObject(json, "name", user->name);
    cJSON_AddStringToObject(
        json,
        "nickname",
        user->nickname ? user->nickname : user->name
    );

    return json;
}

static void addNotifyUsers(cJSON *json, int *notifyUsers, int notifyCount)
{
    cJSON *users = cJSON_CreateArray();

    for(int i = 0; i < notifyCount; i++)
    {
        cJSON_AddItemToArray(users, cJSON_CreateNumber(notifyUsers[i]));
    }

    cJSON_AddItemToObject(json, "notifyUsers", users);
}

void sendAuthResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username,
    const char *nickname
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "AUTH_RESPONSE"
    );

    cJSON_AddNumberToObject(
        json,
        "success",
        success
    );

    if(success)
    {
        cJSON_AddNumberToObject(
            json,
            "userId",
            userId
        );

        cJSON_AddStringToObject(
            json,
            "username",
            username
        );

        cJSON_AddStringToObject(
            json,
            "nickname",
            nickname ? nickname : username
        );

        cJSON_AddStringToObject(
            json,
            "nickname",
            nickname ? nickname : username
        );
    }

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendCreateAccountResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username,
    const char *nickname
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "CREATE_ACCOUNT_RESPONSE"
    );

    cJSON_AddNumberToObject(
        json,
        "success",
        success
    );
    if(nickname)
    {
        cJSON_AddStringToObject(
            json,
            "nickname",
            nickname
        );
    }
    if(success)
    {
        cJSON_AddNumberToObject(
            json,
            "userId",
            userId
        );

        cJSON_AddStringToObject(
            json,
            "username",
            username
        );
    }

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendSyncStart(int clientSocket)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "SYNC_START"
    );

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendSyncEnd(int clientSocket)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "SYNC_END"
    );

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendChatRoomJson(
    int clientSocket,
    ChatRoom *room
)
{
    cJSON *json = chatRoomPayload(room);

    cJSON_AddStringToObject(
        json,
        "type",
        "CHATROOM"
    );

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}


void sendChatUserJson(
    int clientSocket,
    int id,
    const char *username,
    const char *nickname
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "type", "CHAT_USER");
    cJSON_AddNumberToObject(json, "id", id);
    cJSON_AddStringToObject(json, "username", username);
    cJSON_AddStringToObject(json, "name", username);
    cJSON_AddStringToObject(json, "nickname", nickname ? nickname : username);

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}


void sendMessageJson(
    int clientSocket,
    int id,
    int userId,
    int chatRoomId,
    const char *text
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "MESSAGE"
    );

    cJSON_AddNumberToObject(
        json,
        "id",
        id
    );

    cJSON_AddNumberToObject(
        json,
        "userId",
        userId
    );

    cJSON_AddNumberToObject(
        json,
        "chatRoomId",
        chatRoomId
    );

    cJSON_AddStringToObject(
        json,
        "text",
        text
    );

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}
void sendNewMessageResponse(
    int clientSocket,
    int success,
    Message *message,
    int *notifyUsers,
    int notifyCount
)
{
    cJSON *json =
        cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "NEW_MESSAGE_RESPONSE"
    );

    cJSON_AddNumberToObject(
        json,
        "success",
        success
    );

    if(success)
    {
        /*
            Message object
        */

        cJSON *msg =
            cJSON_CreateObject();

        cJSON_AddNumberToObject(
            msg,
            "id",
            message->id
        );

        cJSON_AddStringToObject(
            msg,
            "text",
            message->text
        );

        cJSON_AddNumberToObject(
            msg,
            "userId",
            message->userId
        );

        cJSON_AddNumberToObject(
            msg,
            "chatRoomId",
            message->chatRoomId
        );

        cJSON_AddItemToObject(
            json,
            "message",
            msg
        );

        /*
            Notify users
        */

        cJSON *users =
            cJSON_CreateArray();

        for(int i = 0; i < notifyCount; i++)
        {
            cJSON_AddItemToArray(
                users,
                cJSON_CreateNumber(
                    notifyUsers[i]
                )
            );
        }

        cJSON_AddItemToObject(
            json,
            "notifyUsers",
            users
        );
    }

    sendJson(
        clientSocket,
        json
    );

    cJSON_Delete(json);
}
void sendNewChatRoomResponse(
    int clientSocket,
    int success,
    ChatRoom *room,
    int *notifyUsers,
    int notifyCount
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "type", "NEW_CHATROOM_RESPONSE");
    cJSON_AddNumberToObject(json, "success", success);

    if(success && room)
    {
        cJSON_AddItemToObject(json, "chatRoom", chatRoomPayload(room));
        addNotifyUsers(json, notifyUsers, notifyCount);
    }

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

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
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "type", responseType);
    cJSON_AddNumberToObject(json, "success", success);
    cJSON_AddNumberToObject(json, "userId", userId);
    cJSON_AddNumberToObject(json, "chatRoomId", chatRoomId);

    if(chatUser != NULL)
    {
        cJSON_AddItemToObject(json, "chatUser", userPayload(chatUser));
    }

    if(room != NULL)
    {
        cJSON_AddItemToObject(json, "chatRoom", chatRoomPayload(room));
    }

    addNotifyUsers(json, notifyUsers, notifyCount);

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendDeleteResponse(
    int clientSocket,
    const char *responseType,
    int success,
    const char *idFieldName,
    int objectId,
    int *notifyUsers,
    int notifyCount
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "type", responseType);

    cJSON_AddNumberToObject(json, "success", success);

    cJSON_AddNumberToObject(json, idFieldName, objectId);

    cJSON *users = cJSON_CreateArray();

    if(success)
    {
        for(int i = 0; i < notifyCount; i++)
        {
            cJSON_AddItemToArray(
                users,
                cJSON_CreateNumber(notifyUsers[i])
            );
        }
    }

    cJSON_AddItemToObject(json, "notifyUsers", users);

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}
void sendDeleteRequestResponseJson(
    int clientSocket,
    int success,
    ChatRoom *chatRoom,
    int userId
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "type", "DELETE_REQUEST_RESPONSE");
    cJSON_AddNumberToObject(json, "success", success);
    cJSON_AddNumberToObject(json, "userId", userId);

    if(chatRoom)
    {
        cJSON_AddNumberToObject(json, "chatRoomId", chatRoom->id);
        cJSON_AddItemToObject(json, "chatRoom", chatRoomPayload(chatRoom));

        int notifyUsers[2];
        notifyUsers[0] = chatRoom->coordinatorId;
        notifyUsers[1] = userId;

        addNotifyUsers(json, notifyUsers, 2);
    }
    else
    {
        addNotifyUsers(json, NULL, 0);
    }

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}
