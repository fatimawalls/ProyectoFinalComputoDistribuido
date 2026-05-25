# 📑 Manual de Integración: Ecosistema de Chat
**Proyecto:** Sistema Distribuido (C Backend + Python Frontends)  
**Materia:** Computo Distribuido

Este documento define las reglas de comunicación y los estándares técnicos para la integración entre el núcleo del sistema (C) y las interfaces de usuario (Web/Desktop).

---

## 🛰️ 1. Parámetros de Red (Las Coordenadas)
Todos los componentes deben estar configurados con los siguientes valores para garantizar la visibilidad en la red:

| Parámetro | Valor | Descripción |
| :--- | :--- | :--- |
| **Dirección IP** | `127.0.0.1` | Localhost (Pruebas en entorno local). |
| **Puerto Backend (C)** | `5000` | Puerto principal de escucha (Sockets). |
| **Puerto Web (Flask)** | `5100` | Puerto de acceso para el navegador. |
| **Protocolo** | `TCP Sockets` | Flujo de bytes orientado a conexión. |

---

## 🚦 2. Orden de Ejecución (Pipeline Crítico)
Para evitar errores de tipo `ConnectionRefusedError`, se debe seguir este orden estrictamente:

1.  **Backend (`server.c`):** Iniciar el servidor central. Debe mostrar el estado `LISTENING` en el puerto 5000.
2.  **Pasarela Web (`web_server.py`):** Iniciar el servidor Flask. Este actuará como cliente interno del servidor en C.
3.  **Clientes Finales:** Ejecutar la aplicación de escritorio o acceder a `http://localhost:5100`.

---

## 📜 3. Especificación del Protocolo
La comunicación se basa en un **protocolo de texto delimitado**. Cada paquete de datos debe seguir esta gramática:

### Estructura de la Trama
`COMANDO|ARGUMENTO1|ARGUMENTO2|...|ARGUMENTON\n`

### 💡 Reglas de Oro
* **Terminador (`\n`):** Cada mensaje **DEBE** terminar con un salto de línea. El receptor utiliza este carácter para saber que la trama está completa.
* **Separador (`|`):** Se utiliza exclusivamente para dividir el comando de sus argumentos.
* **Sanitización:** Los frontends deben prohibir el uso de `|` y `\n` en los campos de entrada de texto para evitar errores de parseo en el servidor.

---

## 📖 4. Diccionario de Comandos
| Comando | Emisor | Propósito | Ejemplo de Trama |
| :--- | :--- | :--- | :--- |
| `REQ_LOGIN` | Frontend | Solicitar ingreso al sistema | `REQ_LOGIN|carlos\n` |
| `RES_LOGIN_OK` | Backend | Confirmar éxito de login | `RES_LOGIN_OK\n` |
| `REQ_CHAT_MSG` | Frontend | Enviar mensaje a la sala | `REQ_CHAT_MSG|Hola grupo\n` |
| `EVT_NEW_MSG` | Backend | Notificar mensaje nuevo (Broadcast) | `EVT_NEW_MSG|carlos|Hola grupo\n` |
| `EVT_JOINED` | Backend | Avisar que un usuario se conectó | `EVT_JOINED|fatima\n` |

---

## 🛠️ 5. Guía de Implementación para el Backend (C)
El servidor debe manejar el flujo de datos de la siguiente manera:

1.  **Recepción:** Usar `recv()` acumulando en un buffer hasta detectar el byte `\n`.
2.  **Procesamiento:** Utilizar `strtok()` con el delimitador `"|"` para separar el comando.
3.  **Respuesta:** Construir el string de respuesta y asegurar la concatenación del `\n` antes de llamar a `send()`.

```c
// Ejemplo de respuesta correcta en C
char *respuesta = "RES_LOGIN_OK\n";
send(client_fd, respuesta, strlen(respuesta), 0);