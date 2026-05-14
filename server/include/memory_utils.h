#ifndef MEMORY_UTILS_H
#define MEMORY_UTILS_H

#include "models.h"

void freeUser(User *user);

void freeUsers(
    User *users,
    int count
);

void freeMessage(Message *message);

void freeMessages(
    Message *messages,
    int count
);

void freeChatRoom(ChatRoom *chatRoom);

void freeChatRooms(
    ChatRoom *chatRooms,
    int count
);



#endif