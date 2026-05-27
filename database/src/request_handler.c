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

    int roomCount;

    ChatRoom *rooms =
        getChatRoomsFromUser(
            user->id,
            &roomCount
        );

    for(int i = 0; i < roomCount; i++)
    {
        sendChatRoomJson(
            clientSocket,
            &rooms[i]
        );

        /*
            Send users in room
        */

        for(int j = 0; j < rooms[i].userCount; j++)
        {
            User *roomUser =
                getUserById(
                    rooms[i].userIds[j]
                );

            if(roomUser)
            {
                sendChatUserJson(
                    clientSocket,
                    roomUser->id,
                    roomUser->name
                );
            }
        }

        /*
            Send messages
        */

        int msgCount;

        Message *messages =
            getMessagesFromChatRoom(
                rooms[i].id,
                &msgCount
            );

        for(int j = 0; j < msgCount; j++)
        {
            sendMessageJson(
                clientSocket,
                messages[j].id,
                messages[j].userId,
                messages[j].chatRoomId,
                messages[j].text
            );
        }
    }

    sendSyncEnd(clientSocket);
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

void handleGetUsers(int clientSocket)
{
    int count;
    User* users = getAllUsers(&count);

    for (int i = 0; i < count; i++) {
        sendChatUserJson(clientSocket, users[i].id, users[i].name);
    }

    /* Señal de fin — reutilizamos SYNC_END o un tipo propio */
    cJSON* end = cJSON_CreateObject();
    cJSON_AddStringToObject(end, "type", "GET_USERS_END");
    sendJson(clientSocket, end);
    cJSON_Delete(end);

    freeUsers(users, count);
}

void handleGetRooms(int clientSocket)
{
    int count;
    ChatRoom* rooms = getAllChatRooms(&count);

    for (int i = 0; i < count; i++) {
        sendChatRoomJson(clientSocket, &rooms[i]);
    }

    cJSON* end = cJSON_CreateObject();
    cJSON_AddStringToObject(end, "type", "GET_ROOMS_END");
    sendJson(clientSocket, end);
    cJSON_Delete(end);

    freeChatRooms(rooms, count);
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

    else if (strcmp(type, "GET_USERS") == 0)
    {
        handleGetUsers(clientSocket);
    }
    else if (strcmp(type, "GET_ROOMS") == 0)
    {
        handleGetRooms(clientSocket);
    }

    cJSON_Delete(request);
}