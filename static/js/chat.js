"use strict";

(() => {
  const feed = document.getElementById("chat-feed");
  const form = document.getElementById("message-form");
  const input = document.getElementById("message-input");
  const sendButton = document.getElementById("send-button");
  const overlay = document.getElementById("join-overlay");
  const usernameInput = document.getElementById("username-input");
  const joinForm = document.getElementById("join-form");
  const connectionState = document.getElementById("connection-state");
  const userList = document.getElementById("user-list");
  const userCount = document.getElementById("online-count");
  let username = "";
  let clientId = "";
  let socket = null;
  let reconnectTimer = null;
  let manuallyClosed = false;

  function safeTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "now" : new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
  }

  function scrollToBottom() {
    feed.scrollTop = feed.scrollHeight;
  }

  function addSystem(text, time, isError = false) {
    const item = document.createElement("div");
    item.className = isError ? "error-note" : "system-note";
    item.textContent = text;
    if (time && !isError) item.title = safeTime(time);
    feed.appendChild(item);
    scrollToBottom();
  }

  function addMessage(message) {
    const empty = feed.querySelector(".empty-state");
    if (empty) empty.remove();
    const own = message.sender_id === clientId;
    const row = document.createElement("article");
    row.className = `message-row${own ? " own" : ""}`;
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = (message.username || "?").trim().charAt(0).toUpperCase();
    avatar.setAttribute("aria-hidden", "true");
    const content = document.createElement("div");
    content.className = "message-content";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const name = document.createElement("strong");
    name.textContent = own ? "You" : (message.username || "Guest");
    const time = document.createElement("time");
    time.textContent = safeTime(message.time);
    time.dateTime = message.time || "";
    meta.append(name, time);
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = message.text || "";
    content.append(meta, bubble);
    row.append(avatar, content);
    feed.appendChild(row);
    scrollToBottom();
  }

  function renderUsers(users) {
    userList.replaceChildren();
    for (const user of users) {
      const item = document.createElement("div");
      item.className = "user-item";
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      avatar.textContent = (user.username || "?").trim().charAt(0).toUpperCase();
      const name = document.createElement("span");
      name.className = "user-name";
      name.textContent = user.id === clientId ? `${user.username} (you)` : user.username;
      const dot = document.createElement("span");
      dot.className = "online-dot";
      item.append(avatar, name, dot);
      userList.appendChild(item);
    }
    userCount.textContent = String(users.length);
  }

  function setConnected(connected) {
    connectionState.textContent = connected ? "Connected" : "Reconnecting";
    connectionState.classList.toggle("offline", !connected);
    sendButton.disabled = !connected;
    input.disabled = !connected;
  }

  function connect() {
    if (!username || manuallyClosed) return;
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${scheme}//${location.host}/ws?username=${encodeURIComponent(username)}`;
    socket = new WebSocket(url);
    socket.addEventListener("open", () => setConnected(true));
    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.type === "welcome") {
        clientId = data.client_id;
        username = data.username;
        sessionStorage.setItem("lan-chat-username", username);
        overlay.classList.add("hidden");
        input.focus();
      } else if (data.type === "history") {
        feed.replaceChildren();
        for (const message of data.messages || []) addMessage(message);
        if (!data.messages || data.messages.length === 0) {
          const empty = document.createElement("div");
          empty.className = "empty-state";
          empty.textContent = "You're in. Say hello and start the conversation.";
          feed.appendChild(empty);
        }
      } else if (data.type === "users") {
        renderUsers(data.users || []);
      } else if (data.type === "message") {
        addMessage(data);
      } else if (data.type === "system") {
        addSystem(data.text, data.time);
      } else if (data.type === "error") {
        addSystem(data.text || "Something went wrong.", null, true);
      }
    });
    socket.addEventListener("close", () => {
      setConnected(false);
      if (!manuallyClosed) reconnectTimer = window.setTimeout(connect, 1800);
    });
    socket.addEventListener("error", () => setConnected(false));
  }

  joinForm.addEventListener("submit", (event) => {
    event.preventDefault();
    username = usernameInput.value.trim().slice(0, 24) || "Guest";
    manuallyClosed = false;
    connect();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "message", text }));
    input.value = "";
    input.focus();
  });

  window.addEventListener("beforeunload", () => {
    manuallyClosed = true;
    window.clearTimeout(reconnectTimer);
    if (socket) socket.close();
  });

  const requestedName = new URLSearchParams(location.search).get("username");
  const saved = sessionStorage.getItem("lan-chat-username");
  if (requestedName) usernameInput.value = requestedName.slice(0, 24);
  else if (saved) usernameInput.value = saved;
  usernameInput.focus();
})();
