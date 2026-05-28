#ifndef MODELS_MANAGER_H
#define MODELS_MANAGER_H

#include "models.h"
#include "cJSON.h"


/* User */


User createUser(const char *name, const char *password);

int saveUser(User *user);

int addChatRoomToUser(int userId, int chatRoomId);

int updateUser(User *updatedUser);

User *getUserById(int id);

/* ChatRoom */


ChatRoom createChatRoom(const char *name, int coordinatorId);

int saveChatRoom(ChatRoom *room);

int addMessageToChatRoom(int messageId, int chatRoomId);

int updateChatRoom(ChatRoom *updatedRoom);
ChatRoom *getChatRoomById(int id);

int removeUserFromChatRoom(int userId,int chatRoomId);

int deleteChatRoomById(
    int chatRoomId
);
/* Message */


Message createMessage(const char *text, int userId, int chatRoomId);

int saveMessage(Message *message);

int addUserToChatRoom(int userId, int chatRoomId);

int addJoinRequestToChatRoom(int userId, int chatRoomId);

int removeJoinRequestFromChatRoom(int userId, int chatRoomId);
Message *getMessageById(int id);
int deleteMessageById(
    int messageId
);

/* ================= GET ALL ================= */

User *getAllUsers(int *count);

ChatRoom *getAllChatRooms(int *count);

Message *getAllMessages(int *count);

/* ================= FILTERS ================= */

ChatRoom *getChatRoomsFromUser(int userId,int *count);

Message *getMessagesFromChatRoom(int chatRoomId,int *count);

#endif