# Local Chat — Desktop App

A native Python desktop chat application for devices on the same Wi-Fi or wired LAN. The user interface is a regular desktop window (Tkinter), not a website or browser. It automatically looks for active rooms, lets you create or join one, and handles the chat inside the app. The host and discovery services use Python's built-in TCP and UDP socket libraries. There are no third-party Python packages, external websites, CDNs, or internet services required at runtime.

## Start the app

### Windows — open without a terminal

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/) if it is not already installed. During installation, enable the Python launcher. Tkinter is included with the standard Windows installer.
2. Extract the project ZIP to a folder.
3. Double-click **`LocalChat.pyw`**. Windows starts it as a GUI application without opening a command window.
4. If Windows Firewall asks, allow Python on **Private networks** so the app can discover and accept other devices.

All normal actions happen in the app window. It scans for rooms on startup. If one or more are found, select one and choose **Join selected room**. If none are found, choose **Create a room**. Enter a display name to join. To look again, use **Scan again**.

`main.py` also launches the same window if you prefer to start it from an IDE or a terminal. The `.pyw` file is the recommended double-click launcher on Windows.

### macOS / Linux

Install Python 3.10+ with Tk support, extract the folder, then launch `main.py` from your desktop Python launcher or IDE. If your system only associates `.py` files with a terminal, create a desktop shortcut that launches `python /path/to/local-chat-app/main.py`. No `pip install` step is needed.

## How discovery and hosting work

The desktop app broadcasts a small UDP discovery message on port **37020** and waits briefly for active Local Chat hosts. The list shows each room's name and host address. Selecting **Join selected room** connects the desktop app directly to the host using a local TCP connection. If no active room is found, the same window offers **Create a room**. The first person to create a room hosts it; other devices can discover and join it from their own app windows.

The host binds its chat server to the local network and advertises its TCP port. Keep the host device and app running while the room is in use. The room owner can close it by exiting Local Chat. The host's chat history is held in memory (up to the last 200 messages) and is cleared when the host closes the app.

## Sending files

In a room, choose an online member from **Send file to**, then choose **Choose file…** and select a file up to 25 MB. The recipient sees who sent it and the file name, and must accept and choose where to save it before any file data is sent. Declining or closing the save dialog rejects the offer. Files are sent only to the selected recipient; the room host relays the data but does not save it.

## Network requirements

- All devices must be on a network that allows device-to-device traffic. Guest Wi-Fi/client isolation must be turned off.
- The host firewall should allow inbound UDP **37020** and the TCP port selected automatically by the app on the private/local network profile. On Windows, allow Python on private networks when prompted.
- Some routers block UDP broadcast across VLANs or guest networks. If discovery is blocked, connect the devices to the same non-isolated LAN and rescan. No internet or cloud relay is used.

## Privacy and security

Chat data stays on the LAN and in the host's memory; chat messages are not written to disk. Received files are saved only to the location chosen by the recipient. The app is intended for trusted private networks. It does not provide user accounts, encryption, moderation, or protection from untrusted people who can access the same LAN. Do not expose it to the public internet.

## Project files

```text
local-chat-app/
├── app/
│   ├── __init__.py
│   ├── discovery.py    # UDP broadcast and room discovery
│   ├── desktop.py      # Native Tkinter interface and app flow
│   └── sockets.py      # TCP host/client and real-time chat events
├── LocalChat.pyw       # Windows double-click, no-console launcher
├── main.py             # Desktop app entry point
├── requirements.txt    # No third-party dependencies
└── README.md
```
