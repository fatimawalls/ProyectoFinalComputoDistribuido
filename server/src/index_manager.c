#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "constants.h"

static int getNextId(
    const char *entity
)
{
    FILE *file = fopen(INDEX_FILE, "r");

    if (!file)
        return -1;

    int userId;
    int chatroomId;
    int messageId;

    fscanf(
        file,
        "user:%d\nchatroom:%d\nmessage:%d",
        &userId,
        &chatroomId,
        &messageId
    );

    fclose(file);

    int result = 0;

    if (strcmp(entity, "user") == 0)
    {
        result = userId;
        userId++;
    }
    else if (strcmp(entity, "chatroom") == 0)
    {
        result = chatroomId;
        chatroomId++;
    }
    else
    {
        result = messageId;
        messageId++;
    }

    file = fopen(INDEX_FILE, "w");

    fprintf(
        file,
        "user:%d\nchatroom:%d\nmessage:%d",
        userId,
        chatroomId,
        messageId
    );

    fclose(file);

    return result;
}

int getNextUserId()
{
    return getNextId("user");
}

int getNextChatRoomId()
{
    return getNextId("chatroom");
}

int getNextMessageId()
{
    return getNextId("message");
}