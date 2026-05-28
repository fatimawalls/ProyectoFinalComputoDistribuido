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

int loginUser(const char *name, const char *password);



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
static int removeIntFromArray(
    int **array,
    int *count,
    int value
)
{
    int found = 0;

    for(int i = 0; i < *count; i++)
    {
        if((*array)[i] == value)
        {
            found = 1;

            for(int j = i; j < (*count) - 1; j++)
            {
                (*array)[j] = (*array)[j + 1];
            }

            break;
        }
    }

    if(!found)
    {
        return 0;
    }

    (*count)--;

    if(*count == 0)
    {
        free(*array);
        *array = NULL;
    }
    else
    {
        int *temp = realloc(
            *array,
            sizeof(int) * (*count)
        );

        if(temp)
        {
            *array = temp;
        }
    }

    return 1;
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
static cJSON *userToJson(User *user)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddNumberToObject(
        json,
        "id",
        user->id);

    cJSON_AddStringToObject(
        json,
        "name",
        user->name);

    cJSON_AddStringToObject(
        json,
        "password",
        user->password);

    cJSON *rooms = cJSON_CreateArray();

    for (int i = 0; i < user->chatRoomCount; i++)
    {
        cJSON_AddItemToArray(
            rooms,
            cJSON_CreateNumber(user->chatRoomIds[i]));
    }

    cJSON_AddItemToObject(
        json,
        "chatRoomsIds",
        rooms);

    return json;
}

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
static cJSON *chatRoomToJson(ChatRoom *room)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddNumberToObject(json, "id", room->id);

    cJSON_AddStringToObject(json, "name", room->name);

    cJSON_AddNumberToObject(json, "coordinatorId", room->coordinatorId);

    cJSON *users = cJSON_CreateArray();

    for (int i = 0; i < room->userCount; i++)
    {
        cJSON_AddItemToArray(
            users,
            cJSON_CreateNumber(room->userIds[i]));
    }

    cJSON_AddItemToObject(json, "userIds", users);

    cJSON *messages = cJSON_CreateArray();

    for (int i = 0; i < room->messageCount; i++)
    {
        cJSON_AddItemToArray(
            messages,
            cJSON_CreateNumber(room->messageIds[i]));
    }

    cJSON_AddItemToObject(
        json,
        "messageIds",
        messages);

    cJSON *requests = cJSON_CreateArray();

    for (int i = 0; i < room->requestCount; i++)
    {
        cJSON_AddItemToArray(
            requests,
            cJSON_CreateNumber(room->requestIds[i]));
    }

    cJSON_AddItemToObject(
        json,
        "requestIds",
        requests);

    return json;
}

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

    room.requestIds = NULL;

    room.requestCount = 0;

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
int removeUserFromChatRoom(
    int userId,
    int chatRoomId
)
{
    User *user = getUserById(userId);

    if(!user)
    {
        return 0;
    }

    ChatRoom *room = getChatRoomById(chatRoomId);

    if(!room)
    {
        freeUser(user);
        free(user);

        return 0;
    }

    removeIntFromArray(
        &user->chatRoomIds,
        &user->chatRoomCount,
        chatRoomId
    );

    removeIntFromArray(
        &room->userIds,
        &room->userCount,
        userId
    );

    updateUser(user);

    updateChatRoom(room);

    freeUser(user);
    free(user);

    freeChatRoom(room);
    free(room);

    return 1;
}
int deleteChatRoomById(int chatRoomId)
{
    ChatRoom *room = getChatRoomById(chatRoomId);

    if(!room)
    {
        return 0;
    }

    /*
        Only allow deletion if the chat room only has
        the coordinator as participant.
    */

    if(room->userCount != 1 || room->userIds[0] != room->coordinatorId)
    {
        freeChatRoom(room);
        free(room);

        return 0;
    }

    User *coordinator = getUserById(room->coordinatorId);

    if(coordinator)
    {
        removeIntFromArray(
            &coordinator->chatRoomIds,
            &coordinator->chatRoomCount,
            chatRoomId
        );

        updateUser(coordinator);

        freeUser(coordinator);
        free(coordinator);
    }

    char *content = readFile(CHATROOMS_FILE);

    cJSON *root = cJSON_Parse(content);

    if(!root)
    {
        free(content);
        freeChatRoom(room);
        free(room);
        return 0;
    }

    int size = cJSON_GetArraySize(root);

    for(int i = 0; i < size; i++)
    {
        cJSON *item = cJSON_GetArrayItem(root, i);
        cJSON *idJson = cJSON_GetObjectItem(item, "id");

        if(idJson && idJson->valueint == chatRoomId)
        {
            cJSON_DeleteItemFromArray(root, i);
            break;
        }
    }

    char *updated = cJSON_Print(root);

    writeFile(CHATROOMS_FILE, updated);

    free(updated);
    free(content);
    cJSON_Delete(root);

    freeChatRoom(room);
    free(room);

    return 1;
}
/*----------------message----------------*/

static cJSON *messageToJson(Message *message)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddNumberToObject(json, "id", message->id);

    cJSON_AddNumberToObject(json, "userId", message->userId);

    cJSON_AddNumberToObject(json, "chatRoomId", message->chatRoomId);

    cJSON_AddStringToObject(json, "text", message->text);

    return json;
}

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
        If this user had requested access before, remove the pending request.
    */

    if (containsInt(room->requestIds, room->requestCount, userId))
    {
        removeIntFromArray(
            &room->requestIds,
            &room->requestCount,
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

int addJoinRequestToChatRoom(int userId, int chatRoomId)
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
        If the user is already a member, there is no pending request to add.
    */

    if (containsInt(room->userIds, room->userCount, userId))
    {
        freeUser(user);
        free(user);

        freeChatRoom(room);
        free(room);

        return 1;
    }

    /*
        Add user to pending requests if it is not already there.
    */

    if (!containsInt(room->requestIds, room->requestCount, userId))
    {
        room->requestIds = appendIntToArray(
            room->requestIds,
            &room->requestCount,
            userId);
    }

    updateChatRoom(room);

    freeUser(user);
    free(user);

    freeChatRoom(room);
    free(room);

    return 1;
}

int removeJoinRequestFromChatRoom(int userId, int chatRoomId)
{
    ChatRoom *room = getChatRoomById(chatRoomId);

    if (!room)
    {
        return 0;
    }

    if (containsInt(room->requestIds, room->requestCount, userId))
    {
        removeIntFromArray(
            &room->requestIds,
            &room->requestCount,
            userId);
    }

    updateChatRoom(room);

    freeChatRoom(room);
    free(room);

    return 1;
}

int deleteMessageById(int messageId)
{
    Message *message = getMessageById(messageId);

    if(!message)
    {
        return 0;
    }

    ChatRoom *room = getChatRoomById(message->chatRoomId);

    if(room)
    {
        removeIntFromArray(
            &room->messageIds,
            &room->messageCount,
            messageId
        );

        updateChatRoom(room);

        freeChatRoom(room);
        free(room);
    }

    char *content = readFile(MESSAGES_FILE);

    cJSON *root = cJSON_Parse(content);

    if(!root)
    {
        free(content);
        freeMessage(message);
        free(message);
        return 0;
    }

    int size = cJSON_GetArraySize(root);

    for(int i = 0; i < size; i++)
    {
        cJSON *item = cJSON_GetArrayItem(root, i);
        cJSON *idJson = cJSON_GetObjectItem(item, "id");

        if(idJson && idJson->valueint == messageId)
        {
            cJSON_DeleteItemFromArray(root, i);
            break;
        }
    }

    char *updated = cJSON_Print(root);

    writeFile(MESSAGES_FILE, updated);

    free(updated);
    free(content);
    cJSON_Delete(root);

    freeMessage(message);
    free(message);

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

    /*
        Pending join requests.
        requestIds is optional for compatibility with older JSON files.
    */

    cJSON *requests = cJSON_GetObjectItem(
        json,
        "requestIds"
    );

    if(cJSON_IsArray(requests))
    {
        room.requestCount = cJSON_GetArraySize(requests);

        room.requestIds = malloc(
            sizeof(int) * room.requestCount
        );

        for(int i = 0; i < room.requestCount; i++)
        {
            room.requestIds[i] =
                cJSON_GetArrayItem(
                    requests,
                    i
                )->valueint;
        }
    }
    else
    {
        room.requestIds = NULL;
        room.requestCount = 0;
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
/* -------------utilidades auth-----------------------*/
User *getAllUsers(int *count)
{
    char *content = readFile(USERS_FILE);

    cJSON *root = cJSON_Parse(content);

    *count = cJSON_GetArraySize(root);

    User *users = malloc(
        sizeof(User) * (*count)
    );

    for(int i = 0; i < *count; i++)
    {
        users[i] = jsonToUser(
            cJSON_GetArrayItem(root, i)
        );
    }

    free(content);

    cJSON_Delete(root);

    return users;
}

ChatRoom *getAllChatRooms(int *count)
{
    char *content = readFile(CHATROOMS_FILE);

    cJSON *root = cJSON_Parse(content);

    *count = cJSON_GetArraySize(root);

    ChatRoom *rooms = malloc(
        sizeof(ChatRoom) * (*count)
    );

    for(int i = 0; i < *count; i++)
    {
        rooms[i] = jsonToChatRoom(
            cJSON_GetArrayItem(root, i)
        );
    }

    free(content);

    cJSON_Delete(root);

    return rooms;
}

Message *getAllMessages(int *count)
{
    char *content = readFile(MESSAGES_FILE);

    cJSON *root = cJSON_Parse(content);

    *count = cJSON_GetArraySize(root);

    Message *messages = malloc(
        sizeof(Message) * (*count)
    );

    for(int i = 0; i < *count; i++)
    {
        messages[i] = jsonToMessage(
            cJSON_GetArrayItem(root, i)
        );
    }

    free(content);

    cJSON_Delete(root);

    return messages;
}

static ChatRoom cloneChatRoom(ChatRoom *room)
{
    ChatRoom copy;

    copy.id = room->id;

    copy.name = strdup(room->name);

    copy.coordinatorId = room->coordinatorId;

    copy.userCount = room->userCount;

    copy.userIds = malloc(
        sizeof(int) * copy.userCount
    );

    memcpy(
        copy.userIds,
        room->userIds,
        sizeof(int) * copy.userCount
    );

    copy.messageCount = room->messageCount;

    if(copy.messageCount > 0)
    {
        copy.messageIds = malloc(
            sizeof(int) * copy.messageCount
        );

        memcpy(
            copy.messageIds,
            room->messageIds,
            sizeof(int) * copy.messageCount
        );
    }
    else
    {
        copy.messageIds = NULL;
    }

    copy.requestCount = room->requestCount;

    if(copy.requestCount > 0)
    {
        copy.requestIds = malloc(
            sizeof(int) * copy.requestCount
        );

        memcpy(
            copy.requestIds,
            room->requestIds,
            sizeof(int) * copy.requestCount
        );
    }
    else
    {
        copy.requestIds = NULL;
    }

    return copy;
}
ChatRoom *getChatRoomsFromUser(int userId,int *count)
{
    User *user = getUserById(userId);

    if(!user)
    {
        *count = 0;

        return NULL;
    }

    int totalRooms;

    ChatRoom *allRooms = getAllChatRooms(
        &totalRooms
    );

    ChatRoom *result = malloc(
        sizeof(ChatRoom) * user->chatRoomCount
    );

    int found = 0;

    for(int i = 0; i < user->chatRoomCount; i++)
    {
        int roomId = user->chatRoomIds[i];

        for(int j = 0; j < totalRooms; j++)
        {
            if(allRooms[j].id == roomId)
            {
               result[found++] = cloneChatRoom(&allRooms[j]);
            }
        }
    }

    *count = found;

    freeUser(user);

    free(user);

    for(int i = 0; i < totalRooms; i++){
    freeChatRoom(&allRooms[i]);
    }

    free(allRooms);

    return result;
}
int removeRequestFromChatRoom(
    int chatRoomId,
    int userId
)
{
    int roomCount = 0;

    ChatRoom *rooms =
        getAllChatRooms(
            &roomCount
        );

    if(!rooms)
    {
        return 0;
    }

    for(int i = 0; i < roomCount; i++)
    {
        if(rooms[i].id == chatRoomId)
        {
            int found = 0;

            for(int j = 0; j < rooms[i].requestCount; j++)
            {
                if(rooms[i].requestIds[j] == userId)
                {
                    found = 1;

                    /*
                        Shift left:
                        remove the userId from requestIds
                    */
                    for(
                        int k = j;
                        k < rooms[i].requestCount - 1;
                        k++
                    )
                    {
                        rooms[i].requestIds[k] =
                            rooms[i].requestIds[k + 1];
                    }

                    rooms[i].requestCount--;

                    break;
                }
            }

            if(found)
            {
                saveChatRoom(
                    &rooms[i]
                );
            }

            freeChatRooms(
                rooms,
                roomCount
            );

            return found;
        }
    }

    freeChatRooms(
        rooms,
        roomCount
    );

    return 0;
}
Message *getMessagesFromChatRoom(int chatRoomId,int *count)
{
    ChatRoom *room = getChatRoomById(
        chatRoomId
    );

    if(!room)
    {
        *count = 0;

        return NULL;
    }

    int totalMessages;

    Message *allMessages = getAllMessages(
        &totalMessages
    );

    Message *result = malloc(
        sizeof(Message) * room->messageCount
    );

    int found = 0;

    for(int i = 0; i < room->messageCount; i++)
    {
        int messageId = room->messageIds[i];

        for(int j = 0; j < totalMessages; j++)
        {
            if(allMessages[j].id == messageId)
            {
                result[found++] = allMessages[j];
            }
        }
    }

    *count = found;

    freeChatRoom(room);

    free(room);

    free(allMessages);

    return result;
}

User *getUserById(int id)
{
    int count;

    User *users = getAllUsers(&count);

    for(int i = 0; i < count; i++)
    {
        if(users[i].id == id)
        {
            User *result = malloc(sizeof(User));

            *result = users[i];

            free(users);

            return result;
        }
    }

    free(users);

    return NULL;
}
ChatRoom *getChatRoomById(int id)
{
    int count;

    ChatRoom *rooms = getAllChatRooms(&count);

    for(int i = 0; i < count; i++)
    {
        if(rooms[i].id == id)
        {
            ChatRoom *result = malloc(sizeof(ChatRoom));

            *result = rooms[i];

            free(rooms);

            return result;
        }
    }

    free(rooms);

    return NULL;
}
Message *getMessageById(int id)
{
    int count;

    Message *messages = getAllMessages(&count);

    for(int i = 0; i < count; i++)
    {
        if(messages[i].id == id)
        {
            Message *result = malloc(sizeof(Message));

            *result = messages[i];

            free(messages);

            return result;
        }
    }

    free(messages);

    return NULL;
}
