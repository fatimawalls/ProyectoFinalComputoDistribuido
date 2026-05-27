# client_memory_db.py
# In-memory client-side database for the Python chat client.
#
# This module does NOT persist data to local JSON files.
# It keeps everything in memory using:
# - 3 global lists for the frontend
# - 3 global dictionaries for fast lookup by ID
#
# Lists and dictionaries store the same object references.
# If an object is modified through the dictionary, the list sees the change too.

import json
from dataclasses import dataclass, field
from cifrado import cifrar_texto, descifrar_texto


# ==================================================
# MODELS
# ==================================================

@dataclass
class Friend:
    id: int
    username: str


@dataclass
class ChatRoom:
    id: int
    name: str
    coordinatorId: int
    userIds: list[int] = field(default_factory=list)
    messageIds: list[int] = field(default_factory=list)
    unreadCount: int = 0


@dataclass
class Message:
    id: int
    text: str
    userId: int
    chatRoomId: int


# ==================================================
# GLOBAL MEMORY STATE
# ==================================================
# Frontend can use these lists directly.

friends: list[Friend] = []
chatRooms: list[ChatRoom] = []
messages: list[Message] = []

# Internal fast lookup dictionaries.

friendsById: dict[int, Friend] = {}
chatRoomsById: dict[int, ChatRoom] = {}
messagesById: dict[int, Message] = {}


# ==================================================
# BASIC STATE HELPERS
# ==================================================

def clearState():
    """
    Clears all in-memory data.

    Use this when:
    - user logs out
    - user logs in again
    - full resync is required
    """

    friends.clear()
    chatRooms.clear()
    messages.clear()

    friendsById.clear()
    chatRoomsById.clear()
    messagesById.clear()


def getState():
    """
    Returns the current in-memory state.

    Returns:
    - tuple:
        (friends, chatRooms, messages)
    """

    return friends, chatRooms, messages


def getFriendById(friendId: int):
    return friendsById.get(friendId)


def getChatRoomById(chatRoomId: int):
    return chatRoomsById.get(chatRoomId)


def getMessageById(messageId: int):
    return messagesById.get(messageId)


# ==================================================
# JSON STRING TO OBJECT CONVERTERS
# ==================================================

def strToFriend(jsonString):
    return dictToFriend(
        json.loads(jsonString)
    )


def strToChat(jsonString):
    return dictToChat(
        json.loads(jsonString)
    )


def strToMsg(jsonString):
    return dictToMsg(
        json.loads(jsonString)
    )
# ==================================================
# DICT OBJECT TO MODEL HELPERS
# ==================================================

def dictToFriend(data: dict) -> Friend:
    username = data.get("username")

    if username is None:
        username = data.get("name", "")

    username = descifrar_texto(username)

    return Friend(
        id=data["id"],
        username=username
    )


def dictToChat(data: dict) -> ChatRoom:
    user_ids = list(data.get("userIds", []))

    coordinator_id = data["coordinatorId"]

    if coordinator_id not in user_ids:
        user_ids.append(coordinator_id)

    return ChatRoom(
        id=data["id"],
        name=descifrar_texto(data["name"]),
        coordinatorId=coordinator_id,
        userIds=user_ids,
        messageIds=list(data.get("messageIds", [])),
        unreadCount=data.get("unreadCount", 0)
    )


def dictToMsg(data: dict) -> Message:
    return Message(
        id=data["id"],
        text=descifrar_texto(data["text"]),
        userId=data["userId"],
        chatRoomId=data["chatRoomId"]
    )

# ==================================================
# ADD / UPSERT HELPERS
# ==================================================

def addFriend(friend: Friend) -> Friend:
    """
    Adds a friend if it does not exist.
    If it already exists, updates the username.

    Returns:
    - Friend object stored in memory
    """

    existing = friendsById.get(friend.id)

    if existing:
        existing.username = friend.username
        return existing

    friends.append(friend)
    friendsById[friend.id] = friend

    return friend


def addChatRoomObject(chatRoom: ChatRoom) -> ChatRoom:
    """
    Adds a chat room if it does not exist.
    If it already exists, updates its fields.

    Returns:
    - ChatRoom object stored in memory
    """

    existing = chatRoomsById.get(chatRoom.id)

    if existing:
        existing.name = chatRoom.name
        existing.coordinatorId = chatRoom.coordinatorId
        existing.userIds = list(chatRoom.userIds)
        existing.messageIds = list(chatRoom.messageIds)

        # Keep unreadCount unless the server explicitly sends it.
        existing.unreadCount = chatRoom.unreadCount

        return existing

    chatRooms.append(chatRoom)
    chatRoomsById[chatRoom.id] = chatRoom

    return chatRoom


def addMessageObject(message: Message, increaseUnread: bool = False) -> Message:
    """
    Adds a message if it does not exist.
    Also adds the message ID to the corresponding chat room.

    Parameters:
    - message: Message
    - increaseUnread: bool
        True when the message arrives as a live notification.
        False during sync to avoid showing old messages as unread.

    Returns:
    - Message object stored in memory
    """

    existing = messagesById.get(message.id)

    if existing:
        existing.text = message.text
        existing.userId = message.userId
        existing.chatRoomId = message.chatRoomId
        return existing

    messages.append(message)
    messagesById[message.id] = message

    chatRoom = chatRoomsById.get(message.chatRoomId)

    if chatRoom:
        if message.id not in chatRoom.messageIds:
            chatRoom.messageIds.append(message.id)

        if increaseUnread:
            chatRoom.unreadCount += 1

    return message


# ==================================================
# SYNC HANDLING
# ==================================================

def loadData(jsonStrings: list[str]):
    """
    Loads data received from AUTH sync.

    Parameters:
    - jsonStrings: list[str]

    The list can contain:
    - CHATROOM
    - CHAT_USER
    - MESSAGE
    - SYNC_START
    - SYNC_END
    - AUTH_RESPONSE

    This function:
    1. Parses each JSON string.
    2. Converts each relevant JSON into an object.
    3. Stores the object in global lists and dictionaries.
    4. Avoids duplicates.
    5. Returns only the objects that were newly added.

    Returns:
    - tuple:
        (newFriends, newChatRooms, newMessages)
    """

    newFriends: list[Friend] = []
    newChatRooms: list[ChatRoom] = []
    newMessages: list[Message] = []

    for jsonString in jsonStrings:
        if not jsonString or not jsonString.strip():
            continue

        data = json.loads(jsonString)
        objType = data.get("type")

        if objType == "CHAT_USER":
            friend = dictToFriend(data)

            wasNew = friend.id not in friendsById
            stored = addFriend(friend)

            if wasNew:
                newFriends.append(stored)

        elif objType == "CHATROOM":
            chatRoom = dictToChat(data)

            wasNew = chatRoom.id not in chatRoomsById
            stored = addChatRoomObject(chatRoom)

            if wasNew:
                newChatRooms.append(stored)

        elif objType == "MESSAGE":
            message = dictToMsg(data)

            wasNew = message.id not in messagesById
            stored = addMessageObject(
                message,
                increaseUnread=False
            )

            if wasNew:
                newMessages.append(stored)

    return newFriends, newChatRooms, newMessages


# ==================================================
# NOTIFICATION / RESPONSE HANDLERS
# ==================================================

def addUser(chatRoomId: int, userId: int, chatUser=None):
    """
    Handles ADD_USER notification/response locally.

    Parameters:
    - chatRoomId: int
    - userId: int
    - chatUser: Friend | dict | str | None

    Behavior:
    1. Adds userId to the chat room's userIds list.
    2. If chatUser is provided, saves/updates the friend in memory.
    3. Returns the modified ChatRoom object.

    Returns:
    - ChatRoom
    - None if chat room does not exist locally
    """

    chatRoom = chatRoomsById.get(chatRoomId)

    if not chatRoom:
        return None

    if userId not in chatRoom.userIds:
        chatRoom.userIds.append(userId)

    if chatUser is not None:
        if isinstance(chatUser, Friend):
            addFriend(chatUser)

        elif isinstance(chatUser, str):
            addFriend(strToFriend(chatUser))

        elif isinstance(chatUser, dict):
            addFriend(dictToFriend(chatUser))

    return chatRoom


def removeUser(chatRoomId: int, userId: int):
    """
    Handles REMOVE_USER notification/response locally.

    Parameters:
    - chatRoomId: int
    - userId: int

    Behavior:
    1. Removes userId from the chat room's userIds list.
    2. Does NOT remove the user from friends.

    Returns:
    - ChatRoom
    - None if chat room does not exist locally
    """

    chatRoom = chatRoomsById.get(chatRoomId)

    if not chatRoom:
        return None

    if userId in chatRoom.userIds:
        chatRoom.userIds.remove(userId)

    return chatRoom


def newChatRoom(chatRoomData):
    """
    Handles NEW_CHATROOM notification/response locally.

    Parameters:
    - chatRoomData: ChatRoom | dict | str

    Behavior:
    1. Converts the input into a ChatRoom object if needed.
    2. Adds it to memory if it does not exist.
    3. Updates it if it already exists.

    Returns:
    - ChatRoom
    """

    if isinstance(chatRoomData, ChatRoom):
        chatRoom = chatRoomData

    elif isinstance(chatRoomData, str):
        chatRoom = strToChat(chatRoomData)

    elif isinstance(chatRoomData, dict):
        chatRoom = dictToChat(chatRoomData)

    else:
        raise TypeError("chatRoomData must be ChatRoom, dict, or JSON string")

    return addChatRoomObject(chatRoom)


def newMessage(messageData, increaseUnread: bool = True):
    """
    Handles NEW_MESSAGE notification/response locally.

    Parameters:
    - messageData: Message | dict | str
    - increaseUnread: bool

    Behavior:
    1. Converts the input into a Message object if needed.
    2. Adds it to memory if it does not exist.
    3. Adds the message ID to the corresponding chat room.
    4. Increases unreadCount if increaseUnread is True.

    Returns:
    - Message
    """

    if isinstance(messageData, Message):
        message = messageData

    elif isinstance(messageData, str):
        message = strToMsg(messageData)

    elif isinstance(messageData, dict):
        message = dictToMsg(messageData)

    else:
        raise TypeError("messageData must be Message, dict, or JSON string")

    return addMessageObject(
        message,
        increaseUnread=increaseUnread
    )


def deleteMessage(messageId: int):
    """
    Handles DELETE_MESSAGE notification/response locally.

    Parameters:
    - messageId: int

    Behavior:
    1. Finds the message.
    2. Removes it from messages list.
    3. Removes it from messagesById.
    4. Removes messageId from the corresponding chat room's messageIds list.

    Returns:
    - deleted Message
    - None if message does not exist
    """

    message = messagesById.get(messageId)

    if not message:
        return None

    if message in messages:
        messages.remove(message)

    del messagesById[messageId]

    chatRoom = chatRoomsById.get(message.chatRoomId)

    if chatRoom and messageId in chatRoom.messageIds:
        chatRoom.messageIds.remove(messageId)

    return message


def deleteChatRoom(chatRoomId: int):
    """
    Handles DELETE_CHATROOM notification/response locally.

    Parameters:
    - chatRoomId: int

    Behavior:
    1. Finds the chat room.
    2. Removes it from chatRooms list.
    3. Removes it from chatRoomsById.
    4. Keeps messages in memory by default.

    Returns:
    - deleted ChatRoom
    - None if chat room does not exist
    """

    chatRoom = chatRoomsById.get(chatRoomId)

    if not chatRoom:
        return None

    if chatRoom in chatRooms:
        chatRooms.remove(chatRoom)

    del chatRoomsById[chatRoomId]

    return chatRoom


def openChat(chatRoomId: int):
    """
    Marks a chat room as opened/read.

    Parameters:
    - chatRoomId: int

    Behavior:
    - Sets unreadCount to 0.

    Returns:
    - ChatRoom
    - None if chat room does not exist
    """

    chatRoom = chatRoomsById.get(chatRoomId)

    if not chatRoom:
        return None

    chatRoom.unreadCount = 0

    return chatRoom


# ==================================================
# GENERIC SERVER EVENT HANDLER
# ==================================================
def printState():
    print("Friends:")
    for friend in friends:
        print(friend)

    print("\nChatRooms:")
    for chatRoom in chatRooms:
        print(chatRoom)

    print("\nMessages:")
    for message in messages:
        print(message)
def applyServerJson(jsonString: str):
    """
    Applies a single JSON string received from the server.

    This can be used for notifications or responses.

    Supported types:
    - CHATROOM
    - CHAT_USER
    - MESSAGE
    - NEW_CHATROOM_RESPONSE
    - NEW_CHATROOM_NOTIFICATION
    - NEW_MESSAGE_RESPONSE
    - NEW_MESSAGE_NOTIFICATION
    - ADD_USER_RESPONSE
    - ADD_USER_NOTIFICATION
    - REMOVE_USER_RESPONSE
    - REMOVE_USER_NOTIFICATION
    - DELETE_MESSAGE_RESPONSE
    - DELETE_MESSAGE_NOTIFICATION
    - DELETE_CHATROOM_RESPONSE
    - DELETE_CHATROOM_NOTIFICATION

    Returns:
    - The object modified/created/deleted when applicable
    - None when nothing should be changed
    """
    print(f"Applying server JSON: {jsonString}")
    if not jsonString or not jsonString.strip():
        return None

    data = json.loads(jsonString)
    objType = data.get("type")

    if objType == "CHAT_USER":
        return addFriend(dictToFriend(data))

    if objType == "CHATROOM":
        return addChatRoomObject(dictToChat(data))

    if objType == "MESSAGE":
        return addMessageObject(
            dictToMsg(data),
            increaseUnread=False
        )

    if objType in ("NEW_CHATROOM_RESPONSE", "NEW_CHATROOM_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        chatRoomData = data.get("chatRoom")

        if not chatRoomData:
            return None

        return newChatRoom(chatRoomData)

    if objType in ("NEW_MESSAGE_RESPONSE", "NEW_MESSAGE_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        messageData = data.get("message")

        if not messageData:
            return None

        return newMessage(
            messageData,
            increaseUnread=True
        )

    if objType in ("ADD_USER_RESPONSE", "ADD_USER_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        return addUser(
            chatRoomId=data["chatRoomId"],
            userId=data["userId"],
            chatUser=data.get("chatUser")
        )

    if objType in ("REMOVE_USER_RESPONSE", "REMOVE_USER_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        return removeUser(
            chatRoomId=data["chatRoomId"],
            userId=data["userId"]
        )

    if objType in ("DELETE_MESSAGE_RESPONSE", "DELETE_MESSAGE_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        return deleteMessage(
            data["messageId"]
        )

    if objType in ("DELETE_CHATROOM_RESPONSE", "DELETE_CHATROOM_NOTIFICATION"):
        if not data.get("success", 0):
            return None

        return deleteChatRoom(
            data["chatRoomId"]
        )
    
    return None


def applyServerJsonList(jsonStrings: list[str]):
    """
    Applies multiple JSON strings from the server.

    Useful for:
    - sync list
    - batch notifications
    """

    results = []

    for jsonString in jsonStrings:
        result = applyServerJson(jsonString)

        if result is not None:
            results.append(result)

    return results


# ==================================================
# DEBUG HELPERS
# ==================================================


