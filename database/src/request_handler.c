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
            NULL,
            NULL
        );

        return;
    }

    sendAuthResponse(
        clientSocket,
        1,
        user->id,
        user->name,
        user->nickname
    );

    sendSyncStart(clientSocket);

    int userCount = 0;
    User *users = getAllUsers(&userCount);

    for(int i = 0; i < userCount; i++)
    {
        sendChatUserJson(
            clientSocket,
            users[i].id,
            users[i].name,
            users[i].nickname
        );
    }

    int roomCount = 0;
    ChatRoom *rooms = getAllChatRooms(&roomCount);

    for(int i = 0; i < roomCount; i++)
    {
        sendChatRoomJson(
            clientSocket,
            &rooms[i]
        );
    }

    int msgCount = 0;
    Message *messages = getAllMessages(&msgCount);

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
        freeUsers(users, userCount);
    }

    if(rooms)
    {
        freeChatRooms(rooms, roomCount);
    }

    if(messages)
    {
        freeMessages(messages, msgCount);
    }

    freeUser(user);
    free(user);
}


void handleCreateAccount(
    int clientSocket,
    cJSON *request
)
{
    cJSON *usernameItem =
        cJSON_GetObjectItem(
            request,
            "username"
        );

    cJSON *passwordItem =
        cJSON_GetObjectItem(
            request,
            "password"
        );

    cJSON *nicknameItem =
        cJSON_GetObjectItem(
            request,
            "nickname"
        );

    if(
        !cJSON_IsString(usernameItem) ||
        !cJSON_IsString(passwordItem)
    )
    {
        sendCreateAccountResponse(
            clientSocket,
            0,
            0,
            NULL,
            NULL
        );

        return;
    }

    const char *username = usernameItem->valuestring;
    const char *password = passwordItem->valuestring;
    const char *nickname =
        cJSON_IsString(nicknameItem)
            ? nicknameItem->valuestring
            : username;

    int userId =
        registerUser(
            username,
            password,
            nickname
        );

    sendCreateAccountResponse(
        clientSocket,
        userId > 0,
        userId,
        username,
        nickname
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
            NULL,
            0
        );

        return;
    }

    User *addedUser =
        getUserById(userId);

    int notifyUsers[2];
    int notifyCount = 0;

    notifyUsers[notifyCount++] = room->coordinatorId;

    if(userId != room->coordinatorId)
    {
        notifyUsers[notifyCount++] = userId;
    }

    sendUserChatRelationResponse(
        clientSocket,
        "ADD_USER_RESPONSE",
        success,
        userId,
        chatRoomId,
        addedUser,
        room,
        notifyUsers,
        notifyCount
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
        NULL,
        notifyUsers,
        notifyCount
    );

    free(notifyUsers);
}
void handleJoinRequest(
    int clientSocket,
    cJSON *request
)
{
    cJSON *chatRoomIdItem =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        );

    cJSON *userIdItem =
        cJSON_GetObjectItem(
            request,
            "userId"
        );

    if(
        !cJSON_IsNumber(chatRoomIdItem) ||
        !cJSON_IsNumber(userIdItem)
    )
    {
        sendUserChatRelationResponse(
            clientSocket,
            "REQUEST_RESPONSE",
            0,
            0,
            0,
            NULL,
            NULL,
            NULL,
            0
        );

        return;
    }

    int chatRoomId = chatRoomIdItem->valueint;
    int userId = userIdItem->valueint;

    int success =
        addJoinRequestToChatRoom(
            userId,
            chatRoomId
        );

    ChatRoom *room =
        getChatRoomById(chatRoomId);

    User *requestUser =
        getUserById(userId);

    int notifyUsers[2];
    int notifyCount = 0;

    if(room)
    {
        notifyUsers[notifyCount++] = room->coordinatorId;
    }

    notifyUsers[notifyCount++] = userId;

    sendUserChatRelationResponse(
        clientSocket,
        "REQUEST_RESPONSE",
        success,
        userId,
        chatRoomId,
        requestUser,
        room,
        notifyUsers,
        notifyCount
    );

    if(requestUser)
    {
        freeUser(requestUser);
        free(requestUser);
    }

    if(room)
    {
        freeChatRoom(room);
        free(room);
    }
}

void handleDeleteRequest(
    int clientSocket,
    cJSON *request
)
{
    cJSON *chatRoomIdItem =
        cJSON_GetObjectItem(
            request,
            "chatRoomId"
        );

    cJSON *userIdItem =
        cJSON_GetObjectItem(
            request,
            "userId"
        );

    if(
        !cJSON_IsNumber(chatRoomIdItem) ||
        !cJSON_IsNumber(userIdItem)
    )
    {
        sendDeleteRequestResponseJson(
            clientSocket,
            0,
            NULL,
            0
        );

        return;
    }

    int chatRoomId = chatRoomIdItem->valueint;
    int userId = userIdItem->valueint;

    int success =
        removeJoinRequestFromChatRoom(
            userId,
            chatRoomId
        );

    ChatRoom *room =
        getChatRoomById(chatRoomId);

    sendDeleteRequestResponseJson(
        clientSocket,
        success,
        room,
        userId
    );

    if(room)
    {
        freeChatRoom(room);
        free(room);
    }
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
    else if(strcmp(type, "REQUEST") == 0)
    {
        handleJoinRequest(
            clientSocket,
            request
        );
    }
    else if(strcmp(type, "DELETE_REQUEST") == 0)
    {
        handleDeleteRequest(
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

    cJSON_Delete(request);
}