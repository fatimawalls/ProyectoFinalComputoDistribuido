# Pimentel Company IS de GC ChatRoom System - Distributed Computing Project

## Project Overview
This project involves the development of a proprietary, distributed ChatRoom system tailored for **Pimentel Company IS de GC**. The solution is designed to provide a secure and focused communication environment for employees, avoiding the distractions associated with public social media platforms like WhatsApp or Instagram.

The architecture is built on distributed computing principles, featuring an **E-lobby**: a central hub where users manage their presence, navigate multiple chatrooms, and handle administrative permissions.

## Objectives
* **Authentication & Secure Access**
    * **Objective:** Implement a registration and login process to ensure only authorized personnel access the environment.
    * **Distributed Principle:** Use **TCP Sockets** to establish a reliable, connection-oriented stream between the client and the authentication server. Implement **Data Integrity** checks to ensure credentials are not corrupted during transit, utilizing a request-response protocol over specific **Logical Ports**.

* **Scalable Communication Channels**
    * **Objective:** Create a multi-room environment where users can belong to zero, one, or several concurrent chatrooms.
    * **Distributed Principle:** Utilize **Process Forking** on the server side to handle multiple concurrent client connections. Implement a **Service Directory** logic to map different chatrooms to specific internal data structures, allowing the server to multiplex messages across different logical groups.

* **Hierarchical Management & Access Control**
    * **Objective:** Establish a "Coordinator" role with administrative privileges to manage room membership and maintain order.
    * **Distributed Principle:** Implement **State Management** across the network. The server must maintain a synchronized "Source of Truth" regarding user roles, ensuring that administrative commands are validated against the user's session ID and permissions before execution.

* **Real-time Interaction & Reliable Messaging**
    * **Objective:** Ensure proper delivery of messages and system notifications (user joins, leaves, and requests) across a distributed network.
    * **Distributed Principle:** Rely on **IP Networking** to route packets between distinct machines using their **IP Addresses**. To ensure information arrives **complete and correctly**, the system utilizes the TCP sliding window and acknowledgment (ACK) mechanisms.

* **Productivity Focus & System Integration**
    * **Objective:** Provide a professional tool that meets specific business requirements without the overhead of external social features.
    * **Distributed Principle:** Achieve **Interoperability** between different programming environments. This requires a strict **Data Serialization** protocol to ensure that messages sent from the client are correctly interpreted by the server across the network.

## Scope of the System

### 1. Authentication & Identity
* Mandatory registration and authentication process.
* Unique username/password access.
* Internal nickname management within the E-lobby.

### 2. The E-Lobby (Central Hub)
The E-lobby serves as the primary dashboard where users can:
* View real-time lists of active users and existing chatrooms.
* Create new chatrooms (becoming the **Coordinator**).
* Request access to private chatrooms and track request status.
* Monitor message notifications across all joined rooms simultaneously.

### 3. Permissions & Role Logic
The system distinguishes between General Users and Coordinators:
* **General Users:** Can browse, join, and participate in rooms upon approval.
* **Coordinators:** Have the authority to:
    * Accept or reject join requests.
    * Invite/Add specific logged-in users to a room.
    * Remove (kick) users from a chatroom.
    * Delete a chatroom (permitted only if the coordinator is the last remaining member).

### 4. Chatroom Interaction
Within an individual room, the system supports:
* Multi-user broadcast messaging.
* Status notifications (e.g., when a user leaves the room).
* In-room message reception alerts.

## Project Structure
* **Frontend:** Python Tkinter-based GUI for user interaction and socket-based server communication.
* **Business Logic & Access Control:** Manages permissions, room state, and the coordinator-user relationship.
* **Backend/Networking:** Socket management and data distribution (distributed architecture).

## Constraints
* **Distraction-Free:** No integration with external social media.
* **Room Deletion:** Restricted to empty rooms (except for the coordinator) to prevent accidental data loss or disruption.

## Contributors Sub Teams

### Database:
Heidi Meiners Muñoz  
Fátima Sofía Walls Fernández  
Valeria Pérez Maciel  

### Frontend:
José Eduardo Paredes Moreno  
Carlos Jiménez Zepeda  

### E-lobby (General user & Coordinator):
Kenzo Matoo López  
Omar Alejandro Sánchez López  
Alberto Stephen Dubin Hernández  

### Chatroom & Security:
Álvaro Samuel Velázquez Ramírez  
José Pablo Soto Sánchez  
Jaime Rincón Burboa  