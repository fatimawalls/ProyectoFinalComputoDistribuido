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

void sendAuthResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username
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
    }

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendCreateAccountResponse(
    int clientSocket,
    int success,
    int userId,
    const char *username
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
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "CHATROOM"
    );

    cJSON_AddNumberToObject(
        json,
        "id",
        room->id
    );

    cJSON_AddStringToObject(
        json,
        "name",
        room->name
    );

    cJSON_AddNumberToObject(
        json,
        "coordinatorId",
        room->coordinatorId
    );

    cJSON *users = cJSON_CreateArray();

    for(int i = 0; i < room->userCount; i++)
    {
        cJSON_AddItemToArray(
            users,
            cJSON_CreateNumber(room->userIds[i])
        );
    }

    cJSON_AddItemToObject(
        json,
        "userIds",
        users
    );

    sendJson(clientSocket, json);

    cJSON_Delete(json);
}

void sendChatUserJson(
    int clientSocket,
    int id,
    const char *name
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "CHAT_USER"
    );

    cJSON_AddNumberToObject(
        json,
        "id",
        id
    );

    cJSON_AddStringToObject(
        json,
        "name",
        name
    );

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
    cJSON *json =
        cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        "NEW_CHATROOM_RESPONSE"
    );

    cJSON_AddNumberToObject(
        json,
        "success",
        success
    );

    if(success)
    {
        /*
            Chat room object
        */

        cJSON *chat =
            cJSON_CreateObject();

        cJSON_AddNumberToObject(
            chat,
            "id",
            room->id
        );

        cJSON_AddStringToObject(
            chat,
            "name",
            room->name
        );

        cJSON_AddNumberToObject(
            chat,
            "coordinatorId",
            room->coordinatorId
        );

        cJSON_AddItemToObject(
            json,
            "chatRoom",
            chat
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
void sendUserChatRelationResponse(
    int clientSocket,
    const char *responseType,
    int success,
    int userId,
    int chatRoomId,
    User *chatUser,
    int *notifyUsers,
    int notifyCount
)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(
        json,
        "type",
        responseType
    );

    cJSON_AddNumberToObject(
        json,
        "success",
        success
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

    /*
        Added user info
    */

    if(chatUser != NULL)
    {
        cJSON *user =
            cJSON_CreateObject();

        cJSON_AddNumberToObject(
            user,
            "id",
            chatUser->id
        );

        cJSON_AddStringToObject(
            user,
            "username",
            chatUser->name
        );

        cJSON_AddItemToObject(
            json,
            "chatUser",
            user
        );
    }

    /*
        Notify users
    */

    cJSON *users =
        cJSON_CreateArray();

    for(int i=0;i<notifyCount;i++)
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

    sendJson(
        clientSocket,
        json
    );

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