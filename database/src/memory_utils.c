#include <stdlib.h>

#include "memory_utils.h"

void freeUser(User *user)
{
    free(user->name);

    free(user->nickname);

    free(user->password);

    free(user->chatRoomIds);
}

void freeUsers(User *users,int count)
{
    for(int i = 0; i < count; i++)
    {
        freeUser(&users[i]);
    }

    free(users);
}

void freeMessage(Message *message)
{
    free(message->text);
}

void freeMessages(Message *messages,int count)
{
    for(int i = 0; i < count; i++)
    {
        freeMessage(&messages[i]);
    }

    free(messages);
}

void freeChatRoom(ChatRoom *chatRoom)
{
    free(chatRoom->name);

    free(chatRoom->userIds);

    free(chatRoom->messageIds);

    free(chatRoom->requestIds);
}

void freeChatRooms(ChatRoom *chatRooms,int count)
{
    for(int i = 0; i < count; i++)
    {
        freeChatRoom(&chatRooms[i]);
    }

    free(chatRooms);
}
