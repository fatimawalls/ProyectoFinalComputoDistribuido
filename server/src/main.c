#include <stdio.h>
#include <stdlib.h>
#include "models.h"
#include "database_repository.h"

int main()
{
    User user = createUser("juan","1234");

    saveUser(&user);

    ChatRoom room = createChatRoom("general",user.id);

    saveChatRoom(&room);

    Message message = createMessage("hola mundo",user.id,room.id);

    saveMessage(&message);

    printf("Everything saved correctly\n");

    return 0;
}