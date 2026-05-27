#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

#include "memory_utils.h"
#include "request_handler.h"
#include "protocol.h"
#include "database_repository.h"
#include "login_register.h"
#include "models.h"

void handleAuth(
    int clientSocket,
    cJSON *request
)
{
    const char *username =
        cJSON_GetObjectItem(
            request,
            "username"
        )->valuestring;

    const char *password =
        cJSON_GetObjectItem(
            request,
            "password"
        )->valuestring;

    User *user =
        authenticateUser(
            username,
            password
        );

    if(!user)
    {
        sendAuthResponse(
            clientSocket,
            0,
            0,
            NULL
        );

        return;
    }

    sendAuthResponse(
        clientSocket,
        1,
        user->id,
        user->name
    );

    sendSyncStart(clientSocket);

    /*
        Full database sync.

        Antes:
            Solo se mandaban los chatrooms relacionados al usuario.

        Ahora:
            Se mandan todos los usuarios, todos los chatrooms
            y todos los mensajes.
    */

    int userCount = 0;

    User *users =
        getAllUsers(
            &userCount
        );

    for(int i = 0; i < userCount; i++)
    {
        sendChatUserJson(
            clientSocket,
            users[i].id,
            users[i].name
        );
    }

    int roomCount = 0;

    ChatRoom *rooms =
        getAllChatRooms(
            &roomCount
        );

    for(int i = 0; i < roomCount; i++)
    {
        sendChatRoomJson(
            clientSocket,
            &rooms[i]
        );
    }

    int msgCount = 0;

    Message *messages =
        getAllMessages(
            &msgCount
        );

    for(int i = 0; i < msgCount; i++)
    {
        sendMessageJson(
            clientSocket,
            messages[i].id,
            messages[i].userId,
            messages[i].chatRoomId,
            messages[i].text
        );
    }

    sendSyncEnd(clientSocket);

    if(users)
    {
        freeUsers(
            users,
            userCount
        );
    }

    if(rooms)
    {
        freeChatRooms(
            rooms,
            roomCount
        );
    }

    if(messages)
    {
        freeMessages(
            messages,
            msgCount
        );
    }

    freeUser(user);
    free(user);
}

void handleCreateAccount(
    int clientSocket,
    cJSON *request
)
{
    const char *username =
        cJSON_GetObjectItem(
            request,
            "username"
        )->valuestring;

    const char *password =
        cJSON_GetObjectItem(
            request,
            "password"
        )->valuestring;

    User user =
        createUser(
            username,
            password
        );

    saveUser(&user);

    sendCreateAccountResponse(
        clientSocket,
        1,
        user.id,
        user.name
    );
}
void handleNewMessage(
    int clientSocket,
    cJSON *request
)
{
    const char *text =
        cJSON_GetObjectItem(
            request,
            "text"
        )->valuestring;

    int userId =
        cJSON_GetObjectItem(
            request,
            "userId"
        )->valueint;

    int chatRoomId =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        )->valueint;

    /*
        Create message
    */

    Message message =
        createMessage(
            text,
            userId,
            chatRoomId
        );

    saveMessage(&message);

    /*
        Get users to notify
    */

    ChatRoom *room =
        getChatRoomById(
            chatRoomId
        );

    sendNewMessageResponse(
        clientSocket,
        1,
        &message,
        room->userIds,
        room->userCount
    );

    freeChatRoom(room);

    free(room);
}
void handleNewChatRoom(
    int clientSocket,
    cJSON *request
)
{
    const char *name =
        cJSON_GetObjectItem(
            request,
            "name"
        )->valuestring;

    int coordinatorId =
        cJSON_GetObjectItem(
            request,
            "coordinatorId"
        )->valueint;

    /*
        Create room
    */

    ChatRoom room =
        createChatRoom(
            name,
            coordinatorId
        );

    saveChatRoom(&room);

    /*
        Notify users
    */

    int notifyUsers[1];

    notifyUsers[0] =
        coordinatorId;

    sendNewChatRoomResponse(
        clientSocket,
        1,
        &room,
        notifyUsers,
        1
    );
}
void handleAddUser(
    int clientSocket,
    cJSON *request
)
{
    int userId =
        cJSON_GetObjectItem(
            request,
            "userId"
        )->valueint;

    int chatRoomId =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        )->valueint;

    int success =
        addUserToChatRoom(
            userId,
            chatRoomId
        );

    ChatRoom *room =
        getChatRoomById(chatRoomId);

    if(!room)
    {
        sendUserChatRelationResponse(
            clientSocket,
            "ADD_USER_RESPONSE",
            0,
            userId,
            chatRoomId,
            NULL,
            NULL,
            0
        );

        return;
    }

    User *addedUser =
    getUserById(userId);

    sendUserChatRelationResponse(
        clientSocket,
        "ADD_USER_RESPONSE",
        success,
        userId,
        chatRoomId,
        addedUser,
        room->userIds,
        room->userCount
    );

    if(addedUser)
    {
        freeUser(addedUser);
        free(addedUser);
    }

    freeChatRoom(room);
    free(room);
}
void handleRemoveUser(
    int clientSocket,
    cJSON *request
)
{
    int userId =
        cJSON_GetObjectItem(
            request,
            "userId"
        )->valueint;

    int chatRoomId =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        )->valueint;

    ChatRoom *roomBefore =
        getChatRoomById(chatRoomId);

    int *notifyUsers = NULL;
    int notifyCount = 0;

    if(roomBefore)
    {
        notifyCount = roomBefore->userCount;

        notifyUsers = malloc(
            sizeof(int) * notifyCount
        );

        for(int i = 0; i < notifyCount; i++)
        {
            notifyUsers[i] = roomBefore->userIds[i];
        }

        freeChatRoom(roomBefore);
        free(roomBefore);
    }

    int success =
        removeUserFromChatRoom(
            userId,
            chatRoomId
        );

    sendUserChatRelationResponse(
        clientSocket,
        "REMOVE_USER_RESPONSE",
        success,
        userId,
        chatRoomId,
        NULL,
        notifyUsers,
        notifyCount
    );

    free(notifyUsers);
}
void handleDeleteMessage(
    int clientSocket,
    cJSON *request
)
{
    int messageId =
        cJSON_GetObjectItem(
            request,
            "messageId"
        )->valueint;

    Message *message = getMessageById(messageId);

    if(!message)
    {
        sendDeleteResponse(
            clientSocket,
            "DELETE_MESSAGE_RESPONSE",
            0,
            "messageId",
            messageId,
            NULL,
            0
        );

        return;
    }

    ChatRoom *room =
        getChatRoomById(message->chatRoomId);

    int *notifyUsers = NULL;
    int notifyCount = 0;

    if(room)
    {
        notifyCount = room->userCount;

        notifyUsers = malloc(sizeof(int) * notifyCount);

        for(int i = 0; i < notifyCount; i++)
        {
            notifyUsers[i] = room->userIds[i];
        }

        freeChatRoom(room);
        free(room);
    }

    int success = deleteMessageById(messageId);

    sendDeleteResponse(
        clientSocket,
        "DELETE_MESSAGE_RESPONSE",
        success,
        "messageId",
        messageId,
        notifyUsers,
        notifyCount
    );

    free(notifyUsers);

    freeMessage(message);
    free(message);
}
void handleDeleteChatRoom(
    int clientSocket,
    cJSON *request
)
{
    int chatRoomId =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        )->valueint;

    ChatRoom *room = getChatRoomById(chatRoomId);

    if(!room)
    {
        sendDeleteResponse(
            clientSocket,
            "DELETE_CHATROOM_RESPONSE",
            0,
            "chatRoomId",
            chatRoomId,
            NULL,
            0
        );

        return;
    }

    int notifyUsers[1];
    int notifyCount = 0;

    if(room->userCount == 1 && room->userIds[0] == room->coordinatorId)
    {
        notifyUsers[0] = room->coordinatorId;
        notifyCount = 1;
    }

    freeChatRoom(room);
    free(room);

    int success = deleteChatRoomById(chatRoomId);

    sendDeleteResponse(
        clientSocket,
        "DELETE_CHATROOM_RESPONSE",
        success,
        "chatRoomId",
        chatRoomId,
        notifyUsers,
        notifyCount
    );
}
void handleJoinRequest(
    int clientSocket,
    cJSON *request
)
{
    cJSON *userIdJson     = cJSON_GetObjectItem(request, "userId");
    cJSON *chatRoomIdJson = cJSON_GetObjectItem(request, "chatRoomId");

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "type", "JOIN_REQUEST_RESPONSE");

    if (!userIdJson || !chatRoomIdJson)
    {
        cJSON_AddNumberToObject(resp, "success", 0);
        sendJson(clientSocket, resp);
        cJSON_Delete(resp);
        return;
    }

    int userId     = userIdJson->valueint;
    int chatRoomId = chatRoomIdJson->valueint;

    ChatRoom *room = getChatRoomById(chatRoomId);
    if (!room)
    {
        cJSON_AddNumberToObject(resp, "success", 0);
        cJSON_AddNumberToObject(resp, "chatRoomId", chatRoomId);
        sendJson(clientSocket, resp);
        cJSON_Delete(resp);
        return;
    }

    User *requester = getUserById(userId);

    cJSON_AddNumberToObject(resp, "success",     1);
    cJSON_AddNumberToObject(resp, "chatRoomId",  chatRoomId);
    cJSON_AddNumberToObject(resp, "requesterId", userId);
    if (requester)
        cJSON_AddStringToObject(resp, "requesterName", requester->name);

    /* notifyUsers: [coordinatorId] — el servidor C lo broadcastea via UDP */
    cJSON *notifyArr = cJSON_CreateArray();
    cJSON_AddItemToArray(notifyArr, cJSON_CreateNumber(room->coordinatorId));
    cJSON_AddItemToObject(resp, "notifyUsers", notifyArr);

    sendJson(clientSocket, resp);
    cJSON_Delete(resp);

    if (requester) { freeUser(requester); free(requester); }
    freeChatRoom(room);
    free(room);
}

void handleRequest(
    int clientSocket,
    const char *requestText
)
{
    cJSON *request =
        cJSON_Parse(requestText);

    if(!request)
    {
        return;
    }

    cJSON *typeJson =
        cJSON_GetObjectItem(
            request,
            "type"
        );

    if(!typeJson)
    {
        cJSON_Delete(request);

        return;
    }

    const char *type =
        typeJson->valuestring;

    /*
        AUTH
    */

    if(strcmp(type, "AUTH") == 0)
    {
        handleAuth(
            clientSocket,
            request
        );
    }

    /*
        CREATE ACCOUNT
    */

    else if(
        strcmp(type, "CREATE_ACCOUNT") == 0
    )
    {
        handleCreateAccount(
            clientSocket,
            request
        );
    }
    else if(
        strcmp(type, "NEW_MESSAGE") == 0
    )
    {
        handleNewMessage(
            clientSocket,
            request
        );
    }

    else if(
        strcmp(type, "NEW_CHATROOM") == 0
    )
    {
        handleNewChatRoom(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "ADD_USER") == 0)
    {
        handleAddUser(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "REMOVE_USER") == 0)
    {
        handleRemoveUser(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "DELETE_MESSAGE") == 0)
    {
        handleDeleteMessage(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "DELETE_CHATROOM") == 0)
    {
        handleDeleteChatRoom(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "JOIN_REQUEST") == 0)
    {
        handleJoinRequest(
            clientSocket,
            request
        );
    }

    cJSON_Delete(request);
}