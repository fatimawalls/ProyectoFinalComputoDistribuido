#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

#include "models.h"
#include "constants.h"
#include "json_utils.h"
#include "index_manager.h"
#include "memory_utils.h"
#include "database_repository.h"

User *getUserById(int id);

ChatRoom *getChatRoomById(int id);

Message *getMessageById(int id);

int updateUser(User *user);

int updateChatRoom(ChatRoom *room);

void freeUser(User *user);

void freeChatRoom(ChatRoom *room);

void freeMessage(Message *message);

static int *appendIntToArray(int *array, int *count, int value)
{
    array = realloc(
        array,
        sizeof(int) * (*count + 1));

    array[*count] = value;

    (*count)++;

    return array;
}

static int containsInt(int *array, int count, int value)
{
    for (int i = 0; i < count; i++)
    {
        if (array[i] == value)
        {
            return 1;
        }
    }

    return 0;
}

/*----------------user----------------*/


User createUser(const char *name, const char *password)
{
    User user;

    user.id = getNextUserId();

    user.name = strdup(name);

    user.password = strdup(password);

    user.chatRoomIds = NULL;

    user.chatRoomCount = 0;

    return user;
}

int saveUser(User *user)
{
    char *content = readFile(USERS_FILE);

    cJSON *root = cJSON_Parse(content);

    cJSON_AddItemToArray(
        root,
        userToJson(user));

    char *updated = cJSON_Print(root);

    writeFile(
        USERS_FILE,
        updated);

    free(updated);

    free(content);

    cJSON_Delete(root);

    return 1;
}


int updateUser(User *updatedUser)
{
    char *content = readFile(USERS_FILE);

    cJSON *root = cJSON_Parse(content);

    int size = cJSON_GetArraySize(root);

    for (int i = 0; i < size; i++)
    {
        cJSON *item = cJSON_GetArrayItem(root, i);

        cJSON *idJson = cJSON_GetObjectItem(
            item,
            "id");

        if (idJson->valueint == updatedUser->id)
        {
            cJSON_ReplaceItemInArray(
                root,
                i,
                userToJson(updatedUser));

            break;
        }
    }

    char *updated = cJSON_Print(root);

    writeFile(
        USERS_FILE,
        updated);

    free(updated);

    free(content);

    cJSON_Delete(root);

    return 1;
}

/*----------------chatroom----------------*/


ChatRoom createChatRoom(const char *name, int coordinatorId)
{
    ChatRoom room;

    room.id = getNextChatRoomId();

    room.name = strdup(name);

    room.coordinatorId = coordinatorId;

    room.userIds = malloc(sizeof(int));

    room.userIds[0] = coordinatorId;

    room.userCount = 1;

    room.messageIds = NULL;

    room.messageCount = 0;

    return room;
}

int saveChatRoom(ChatRoom *room)
{
    char *content = readFile(CHATROOMS_FILE);

    cJSON *root = cJSON_Parse(content);

    cJSON_AddItemToArray(
        root,
        chatRoomToJson(room));

    char *updated = cJSON_Print(root);

    writeFile(
        CHATROOMS_FILE,
        updated);

    /*
        Add room to coordinator user
    */

    addUserToChatRoom(
        room->coordinatorId,
        room->id);

    free(updated);

    free(content);

    cJSON_Delete(root);

    return 1;
}

int addMessageToChatRoom(int messageId, int chatRoomId)
{
    ChatRoom *room = getChatRoomById(chatRoomId);

    if (!room)
    {
        return 0;
    }

    if (!containsInt(room->messageIds, room->messageCount, messageId))
    {
        room->messageIds = appendIntToArray(
            room->messageIds,
            &room->messageCount,
            messageId);
    }

    updateChatRoom(room);

    freeChatRoom(room);

    free(room);

    return 1;
}

int updateChatRoom(ChatRoom *updatedRoom)
{
    char *content = readFile(CHATROOMS_FILE);

    cJSON *root = cJSON_Parse(content);

    int size = cJSON_GetArraySize(root);

    for (int i = 0; i < size; i++)
    {
        cJSON *item = cJSON_GetArrayItem(root, i);

        cJSON *idJson = cJSON_GetObjectItem(
            item,
            "id");

        if (idJson->valueint == updatedRoom->id)
        {
            cJSON_ReplaceItemInArray(
                root,
                i,
                chatRoomToJson(updatedRoom));

            break;
        }
    }

    char *updated = cJSON_Print(root);

    writeFile(
        CHATROOMS_FILE,
        updated);

    free(updated);

    free(content);

    cJSON_Delete(root);

    return 1;
}

/*----------------message----------------*/



Message createMessage(const char *text, int userId, int chatRoomId)
{
    Message message;

    message.id = getNextMessageId();

    message.text = strdup(text);

    message.userId = userId;

    message.chatRoomId = chatRoomId;

    return message;
}

int saveMessage(Message *message)
{
    char *content = readFile(MESSAGES_FILE);

    cJSON *root = cJSON_Parse(content);

    cJSON_AddItemToArray(
        root,
        messageToJson(message));

    char *updated = cJSON_Print(root);

    writeFile(
        MESSAGES_FILE,
        updated);

    /*
        Add message to room
    */

    addMessageToChatRoom(
        message->id,
        message->chatRoomId);

    free(updated);

    free(content);

    cJSON_Delete(root);

    return 1;
}

int addUserToChatRoom(int userId, int chatRoomId)
{
    User *user = getUserById(userId);

    if (!user)
    {
        return 0;
    }

    ChatRoom *room = getChatRoomById(chatRoomId);

    if (!room)
    {
        freeUser(user);

        free(user);

        return 0;
    }

    /*
        Add room to user
    */

    if (!containsInt(user->chatRoomIds, user->chatRoomCount, chatRoomId))
    {
        user->chatRoomIds = appendIntToArray(
            user->chatRoomIds,
            &user->chatRoomCount,
            chatRoomId);
    }

    /*
        Add user to room
    */

    if (!containsInt(room->userIds, room->userCount, userId))
    {
        room->userIds = appendIntToArray(
            room->userIds,
            &room->userCount,
            userId);
    }

    /*
        Save changes
    */

    updateUser(user);

    updateChatRoom(room);

    /*
        Free memory
    */

    freeUser(user);

    free(user);

    freeChatRoom(room);

    free(room);

    return 1;
}
/*-----------------utils to bbj----------------*/
static User jsonToUser(cJSON *json)
{
    User user;

    user.id = cJSON_GetObjectItem(
        json,
        "id"
    )->valueint;

    user.name = strdup(
        cJSON_GetObjectItem(
            json,
            "name"
        )->valuestring
    );

    user.password = strdup(
        cJSON_GetObjectItem(
            json,
            "password"
        )->valuestring
    );

    cJSON *rooms = cJSON_GetObjectItem(
        json,
        "chatRoomsIds"
    );

    user.chatRoomCount = cJSON_GetArraySize(rooms);

    user.chatRoomIds = malloc(
        sizeof(int) * user.chatRoomCount
    );

    for(int i = 0; i < user.chatRoomCount; i++)
    {
        user.chatRoomIds[i] =
            cJSON_GetArrayItem(
                rooms,
                i
            )->valueint;
    }

    return user;
}

static ChatRoom jsonToChatRoom(cJSON *json)
{
    ChatRoom room;

    room.id = cJSON_GetObjectItem(
        json,
        "id"
    )->valueint;

    room.name = strdup(
        cJSON_GetObjectItem(
            json,
            "name"
        )->valuestring
    );

    room.coordinatorId = cJSON_GetObjectItem(
        json,
        "coordinatorId"
    )->valueint;

    /*
        Users
    */

    cJSON *users = cJSON_GetObjectItem(
        json,
        "userIds"
    );

    room.userCount = cJSON_GetArraySize(users);

    room.userIds = malloc(
        sizeof(int) * room.userCount
    );

    for(int i = 0; i < room.userCount; i++)
    {
        room.userIds[i] =
            cJSON_GetArrayItem(
                users,
                i
            )->valueint;
    }

    /*
        Messages
    */

    cJSON *messages = cJSON_GetObjectItem(
        json,
        "messageIds"
    );

    room.messageCount = cJSON_GetArraySize(messages);

    room.messageIds = malloc(
        sizeof(int) * room.messageCount
    );

    for(int i = 0; i < room.messageCount; i++)
    {
        room.messageIds[i] =
            cJSON_GetArrayItem(
                messages,
                i
            )->valueint;
    }

    return room;
}

static Message jsonToMessage(cJSON *json)
{
    Message message;

    message.id = cJSON_GetObjectItem(
        json,
        "id"
    )->valueint;

    message.userId = cJSON_GetObjectItem(
        json,
        "userId"
    )->valueint;

    message.chatRoomId = cJSON_GetObjectItem(
        json,
        "chatRoomId"
    )->valueint;

    message.text = strdup(
        cJSON_GetObjectItem(
            json,
            "text"
        )->valuestring
    );

    return message;
}
/*-----------utilidades auth----------------*/