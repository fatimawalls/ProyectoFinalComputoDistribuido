CC = gcc

CFLAGS = -Wall -Wextra -Iinclude -Ilibs

SRC = \
	src/database_server.c \
	src/database_repository.c \
	src/json_utils.c \
	src/index_manager.c \
	src/memory_utils.c \
	src/protocol.c \
	src/login_register.c \
	src/request_handler.c \
	libs/cJSON.c

OUT = app

all:
	$(CC) $(SRC) $(CFLAGS) -o $(OUT)

run:
	./$(OUT)

clean:
	rm -f $(OUT)