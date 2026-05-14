#ifndef MODELS_H
#define MODELS_H

typedef struct {
    int id;

    char *name;
    char *password;

    int *chatRoomIds;
    int chatRoomCount;

    long filePosition;

} User;

typedef struct {

    int id;

    int userId;
    int chatRoomId;

    char *text;

    long filePosition;

} Message;

typedef struct {

    int id;

    char *name;

    int *userIds;
    int userCount;

    int *messageIds;
    int messageCount;

    int coordinatorId;

    long filePosition;

} ChatRoom;

#endif