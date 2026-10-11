
const el = id => document.getElementById(id);
const channels = new Set();
let connected = false;
let cursor = 0;
let generation = 0;
let isAdmin = false;
let currentRole = "user";
let currentUser = "";
let registerMode = false;
const pendingReports = new Map();

function authMode(value) {
  registerMode = value;
  el("authTitle").textContent = value ? "Create account" : "Sign in";
  el("connect").textContent = value ? "Create account" : "Sign in";
  el("authToggle").textContent = value ? "Back to sign in" : "Create an account";
  el("confirmLabel").hidden = !value;
  el("confirmPassword").required = value;
  el("password").autocomplete = value ? "new-password" : "current-password";
  el("authHint").textContent = value
    ? "Username: 3–32 lowercase letters, numbers, _ or -. Password: 8–128 characters."
    : "Use your saved account. New here? Create an account below.";
  message("loginMessage", "");
}
el("authToggle").onclick = () => authMode(!registerMode);
el("showPassword").onclick = () => {
  const show = el("password").type === "password";
  for (const id of ["password", "confirmPassword"]) el(id).type = show ? "text" : "password";
  el("showPassword").textContent = show ? "Hide password" : "Show password";
  el("showPassword").setAttribute("aria-pressed", String(show));
};

async function authRequest(path, data = {}) {
  const response = await fetch(path, {
    method: "POST", headers: {"Content-Type":"application/json", "X-STOMP-UI":"1"},
    body: JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}
let report = null;
let summaryContent = "";
let serverLines = [];
const history = [];

function message(id, text, error = false) {
  el(id).textContent = text;
  el(id).classList.toggle("error", error);
}

function showView(id) {
  document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== id);
  document.querySelectorAll("[data-view]").forEach(b =>
    b.classList.toggle("active", b.dataset.view === id));
  if (id === "registryView") loadIncidents();
  if (id === "systemView" && isAdmin) loadAccess();
}
document.querySelectorAll("[data-view]").forEach(b =>
  b.addEventListener("click", () => showView(b.dataset.view)));

async function request(action, data = {}) {
  const fingerprint = action === "report" ? JSON.stringify(data.report) : null;
  if (fingerprint && !pendingReports.has(fingerprint)) {
    if (pendingReports.size >= 10) pendingReports.delete(pendingReports.keys().next().value);
    pendingReports.set(fingerprint, crypto.randomUUID());
  }
  const response = await fetch("/command", {
    method: "POST",
    headers: {"Content-Type":"application/json", "X-STOMP-UI":"1"},
    body: JSON.stringify({action, ...data, ...(action === "report" ? {request_id: pendingReports.get(fingerprint)} : {})})
  });
  const result = await response.json();
  if (response.ok && fingerprint) pendingReports.delete(fingerprint);
  if (response.status === 401) resetSession("Session expired. Please sign in.");
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

function drawChannels() {
  const selected = el("composeChannel").value;
  el("composeChannel").replaceChildren();
  if (!channels.size) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Join a channel first";
    el("composeChannel").append(option);
  } else {
    for (const name of channels) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      el("composeChannel").append(option);
    }
    if (channels.has(selected)) el("composeChannel").value = selected;
  }
  el("composeSend").disabled = !connected || !channels.size;
  el("channelList").replaceChildren();
  if (!channels.size) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = "You have not joined any channels.";
    el("channelList").append(p);
  }
  for (const channel of channels) {
    const row = document.createElement("div");
    row.className = "channel";
    const label = document.createElement("span");
    label.textContent = channel;
    const button = document.createElement("button");
    button.textContent = "Leave";
    button.onclick = async () => {
      button.disabled = true;
      try {
        await request("leave", {channel});
      } catch (error) {
        message("channelStatus", error.message, true);
        button.disabled = false;
      }
    };
    row.append(label, button);
    el("channelList").append(row);
  }
}

function resetSession(text, error = false) {
  generation++;
  cursor = 0;
  isAdmin = false;
  currentRole = "user";
  currentUser = "";
  pendingReports.clear();
  el("passwordForm").reset();
  message("passwordNotice", "");
  for (const id of ["currentPassword","newPassword","newPasswordConfirm"]) el(id).type = "password";
  el("showAccountPassword").textContent = "Show passwords";
  el("showAccountPassword").setAttribute("aria-pressed", "false");
  el("incidentList").replaceChildren();
  el("accessSummary").replaceChildren();
  el("accessHistory").replaceChildren();
  el("adminTab").hidden = true;
  history.length = 0;
  el("clientEvents").textContent = "";
  el("serverLogs").textContent = "";
  connected = false;
  channels.clear();
  report = null;
  summaryContent = "";
  el("incidentDrawer").close();
  el("notificationDialog").close();
  el("notificationList").replaceChildren();
  el("notificationCount").textContent = "0";
  el("appPage").hidden = true;
  el("loginPage").hidden = false;
  el("connect").disabled = false;
  el("logout").disabled = false;
  el("password").value = "";
  el("confirmPassword").value = "";
  for (const id of ["password","confirmPassword"]) el(id).type = "password";
  el("showPassword").textContent = "Show password";
  el("showPassword").setAttribute("aria-pressed", "false");
  el("reportFile").value = "";
  el("composeForm").reset();
  message("composeStatus", "");
  el("sendReport").disabled = true;
  el("reports").replaceChildren();
  el("reportsEmpty").hidden = false;
  el("summaryText").textContent = "";
  el("summaryText").hidden = true;
  el("downloadSummary").disabled = true;
  message("loginMessage", text, error);
  for (const id of ["channelStatus","reportStatus","summaryStatus","connectionNote"])
    message(id, "");
  el("fileInfo").textContent = "No file selected.";
  drawChannels();
}

el("loginForm").onsubmit = async event => {
  event.preventDefault();
  if (registerMode && el("password").value !== el("confirmPassword").value) {
    message("loginMessage", "Passwords do not match.", true);
    return;
  }
  el("connect").disabled = true;
  el("authToggle").disabled = true;
  message("loginMessage", registerMode ? "Creating account..." : "Signing in...");
  try {
    await authRequest(registerMode ? "/auth/register" : "/auth/login", {
      username: el("username").value, password: el("password").value
    });
    authMode(false);
    el("confirmPassword").value = "";
    await restoreSession();
  } catch (error) { message("loginMessage", error.message, true); }
  finally {
    el("connect").disabled = false;
    el("authToggle").disabled = false;
  }
};

el("logout").onclick = async () => {
  el("logout").disabled = true;
  generation++;
  try {
    await authRequest("/auth/logout");
    resetSession("You have signed out.");
  } catch (error) {
    message("connectionNote", error.message, true);
    el("logout").disabled = false;
  }
};

el("channelForm").onsubmit = async event => {
  event.preventDefault();
  const channel = el("channel").value.trim();
  if (channels.has(channel)) {
    message("channelStatus", "You have already joined this channel.");
    return;
  }
  message("channelStatus", "Joining channel...");
  try { await request("join", {channel}); }
  catch (error) { message("channelStatus", error.message, true); }
};

el("composeForm").onsubmit = async event => {
  event.preventDefault();
  const channel = el("composeChannel").value;
  const title = el("composeTitle").value.trim();
  const city = el("composeCity").value.trim();
  const description = el("composeDescription").value.trim();

  if (!connected || !channels.has(channel)) {
    message("composeStatus", "Join the destination channel first.", true);
    return;
  }
  if (!title || !city || !description) {
    message("composeStatus", "Enter a title, city and description.", true);
    return;
  }

  const report = {
    channel_name: channel,
    events: [{
      event_name: title,
      priority: el("composePriority").value,
      location: el("composeLocation").value.trim(),
      city,
      date_time: Math.floor(Date.now() / 1000),
      description,
      general_information: {
        active: el("composeActive").checked,
        forces_arrival_at_scene: el("composeArrived").checked
      }
    }]
  };

  el("composeSend").disabled = true;
  message("composeStatus", "Submitting report...");
  try {
    const result = await request("report", {report});
    message("composeStatus", savedMessage(result));
    el("composeTitle").value = "";
    el("composeDescription").value = "";
  } catch (error) {
    message("composeStatus", error.message, true);
  } finally {
    el("composeSend").disabled = !connected || !channels.size;
  }
};

el("reportFile").onchange = async () => {
  report = null;
  el("sendReport").disabled = true;
  message("reportStatus", "");
  const file = el("reportFile").files[0];
  if (!file) {
    el("fileInfo").textContent = "No file selected.";
    return;
  }
  try {
    if (file.size > 200000) throw new Error("Choose a file smaller than 200 KB.");
    const candidate = JSON.parse(await file.text());
    if (!candidate || typeof candidate.channel_name !== "string" ||
        !candidate.channel_name || !Array.isArray(candidate.events))
      throw new Error("This file is not a supported report.");
    report = candidate;
    el("fileInfo").textContent =
      "Destination: " + report.channel_name + " · Reports: " + report.events.length;
    el("sendReport").disabled = false;
  } catch (error) {
    el("fileInfo").textContent = "File could not be loaded.";
    message("reportStatus", error.message, true);
  }
};

el("sendReport").onclick = async () => {
  if (!report) return;
  if (!channels.has(report.channel_name)) {
    message("reportStatus",
      'Join "' + report.channel_name + '" before sending this report.', true);
    return;
  }
  el("sendReport").disabled = true;
  message("reportStatus", "Submitting report...");
  try {
    const result = await request("report", {report});
    message("reportStatus", savedMessage(result));
  } catch (error) {
    message("reportStatus", error.message, true);
  } finally {
    el("sendReport").disabled = !connected || !report;
  }
};

el("summaryForm").onsubmit = async event => {
  event.preventDefault();
  summaryContent = "";
  el("downloadSummary").disabled = true;
  el("summaryText").hidden = true;
  message("summaryStatus", "Generating summary...");
  try {
    await request("summary", {
      channel: el("summaryChannel").value.trim(),
      user: el("summaryUser").value.trim()
    });
  } catch (error) { message("summaryStatus", error.message, true); }
};

el("downloadSummary").onclick = () => {
  const url = URL.createObjectURL(new Blob([summaryContent], {type:"text/plain;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "stomp-summary.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function handle(event) {
  history.push(JSON.stringify(event));
  if (history.length > 100) history.shift();
  el("clientEvents").textContent = history.join("\n");

  if (event.type === "login_success") {
    connected = true;
    el("loginPage").hidden = true;
    el("appPage").hidden = false;
    el("accountName").textContent = event.user + " · " + ({admin:"Administrator",responder:"Responder",user:"User"}[currentRole] || currentRole);
    el("summaryUser").value = event.user;
    el("password").value = "";
    el("logout").disabled = false;
    message("connectionNote", "");
    showView("registryView");
    drawChannels();
  } else if (event.type === "logout_success") {
    resetSession("You have signed out.");
  } else if (["server_error","connection_failed","connection_closed","client_stopped"].includes(event.type)) {
    resetSession(event.message || "Connection closed. Please sign in again.", true);
  } else if (event.type === "subscription_receipt") {
    const text = event.message || "";
    if (text.startsWith("Joined channel ")) {
      const name = text.slice("Joined channel ".length);
      channels.add(name);
      el("summaryChannel").value = name;
    } else if (text.startsWith("Exited channel ")) {
      channels.delete(text.slice("Exited channel ".length));
    }
    message("channelStatus", text);
    drawChannels();
  } else if (event.type === "report_received") {
    el("reportsEmpty").hidden = true;
    const card = document.createElement("article");
    card.className = "report";
    const title = document.createElement("h3");
    title.textContent = event.name;
    const meta = document.createElement("p");
    meta.className = "muted small";
    meta.textContent = event.channel + " · " + event.city + " · " + event.user;
    const body = document.createElement("p");
    body.textContent = event.description;
    card.append(title, meta, body);
    el("reports").prepend(card);
    while (el("reports").children.length > 100)
      el("reports").lastElementChild.remove();
  } else if (event.type === "summary_ready") {
    summaryContent = event.content;
    el("summaryText").textContent = summaryContent;
    el("summaryText").hidden = false;
    el("downloadSummary").disabled = false;
    message("summaryStatus", "Summary ready.");
  } else if (event.type === "summary_error") {
    message("summaryStatus", event.message, true);
  }
}

async function poll() {
  const current = generation;
  try {
    if (!connected) return;
    const response = await fetch("/events?after=" + cursor, {cache:"no-store"});
    if (current !== generation) return;
    if (response.status === 401) {
      resetSession("Session expired or signed in elsewhere. Please sign in.");
      return;
    }
    if (!response.ok) throw new Error("Service unavailable");
    const data = await response.json();
    if (current !== generation) return;
    if (data.resync) { await restoreSession(); return; }
    cursor = data.cursor;
    for (const event of data.events) handle(event);
  } catch (error) {
    message("connectionNote", "Cannot reach the service. Retrying...", true);
  } finally { setTimeout(poll, 700); }
}

function renderLogs() {
  const level = el("logLevel").value;
  const lines = serverLines.filter(line =>
    level === "ALL" || line.split(/\s+/)[1] === level);
  el("serverLogs").textContent = lines.join("\n") || "No matching events.";
}
el("logLevel").onchange = renderLogs;

async function pollMonitor() {
  if (connected && isAdmin && !el("systemView").hidden) {
    try {
      const response = await fetch("/server-status", {cache:"no-store"});
      if (!response.ok) throw new Error("Monitor unavailable");
      const result = await response.json();
      if (!result.available) throw new Error("Monitor unavailable");
      const data = result.status;
      el("monitorValues").hidden = false;
      message("monitorStatus", "Local server process is running.");
      el("metricConnections").textContent = data.connections;
      el("metricUsers").textContent = data.users;
      el("metricChannels").textContent = data.channels;
      el("monitorDetails").textContent =
        "Mode: " + data.mode.toUpperCase() +
        " · Port: " + data.port +
        " · Running for " + Math.floor(data.uptime_seconds / 60) + " min";
    } catch (error) {
      el("monitorValues").hidden = true;
      message("monitorStatus",
        "Local server monitor is unavailable. Its status cannot be confirmed.", true);
    }
  }
  setTimeout(pollMonitor, 2000);
}

async function pollLogs() {
  if (connected && isAdmin && !el("systemView").hidden) {
    try {
      const response = await fetch("/server-logs", {cache:"no-store"});
      if (!response.ok) throw new Error("Server log unavailable.");
      const data = await response.json();
      serverLines = data.lines;
      message("serverLogStatus", data.message);
      renderLogs();
    } catch (error) { message("serverLogStatus", error.message, true); }
  }
  setTimeout(pollLogs, 1500);
}
async function restoreSession() {
  el("connect").disabled = true;
  try {
    const response = await fetch("/session", {cache:"no-store"});
    if (!response.ok) throw new Error("Could not restore the session. Try signing in again.");
    const snapshot = await response.json();
    resetSession("");
    if (snapshot.user) {
      currentRole = snapshot.user.role;
      currentUser = snapshot.user.name;
      isAdmin = currentRole === "admin";
      el("adminTab").hidden = !isAdmin;
      cursor = snapshot.cursor;
      for (const event of snapshot.events) handle(event);
    }
  } finally { el("connect").disabled = false; }
}

drawChannels();
restoreSession().catch(error => message("loginMessage", error.message, true));
poll();
pollLogs();
pollMonitor();

function savedMessage(result) {
  const ids = (result.incident_ids || []).map(id => "#" + id).join(", ");
  return "Saved incident " + ids + (result.delivery === "submitted"
    ? ". Passed to STOMP; this does not confirm every recipient received it."
    : ". Transmission outcome is unknown. Check the incident before submitting again.");
}

async function getJSON(path) {
  const response = await fetch(path, {cache:"no-store"});
  const data = await response.json();
  if (response.status === 401) resetSession("Session expired. Please sign in.");
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
const statusLabels = {new:"New", in_progress:"In progress", closed:"Closed"};
let nextIncident = null;
let incidentQuery = "";
let listGeneration = 0;

async function loadIncidents(more = false) {
  const sessionGeneration = generation;
  const queryGeneration = ++listGeneration;
  if (!connected) return;
  el("incidentMore").disabled = true;
  if (!more) {
    const params = new URLSearchParams();
    for (const [key,id] of [["q","incidentQuery"],["channel","incidentChannel"],["status","incidentStatus"],["priority","incidentPriority"],["from","incidentFrom"],["to","incidentTo"]]) {
      if (el(id).value) params.set(key,el(id).value);
    }
    if (el("incidentMine").checked) params.set("mine", "1");
    incidentQuery = params.toString();
  }
  try {
    const result = await getJSON("/incidents?" + incidentQuery + (more && nextIncident ? "&before="+nextIncident : ""));
    if (sessionGeneration !== generation || queryGeneration !== listGeneration) return;
    if (!more) el("incidentList").replaceChildren();
    for (const item of result.items) renderIncident(item);
    refreshOverview();
    nextIncident = result.next;
    el("incidentMore").hidden = !nextIncident;
    message("incidentNotice", el("incidentList").children.length ? "Saved reports · newest first" : "No incidents match these filters.");
  } catch (error) {
    if (sessionGeneration === generation) message("incidentNotice", error.message,true);
  } finally { el("incidentMore").disabled = false; }
}
el("incidentFilters").onsubmit = event => { event.preventDefault(); loadIncidents(); };
el("incidentMore").onclick = () => loadIncidents(true);

function renderIncident(item) {
  const row=node("tr");
  const title=node("td"); const open=node("button",item.title);
  open.onclick=()=>openIncident(item.id);
  title.append(open,node("small","#"+item.id+" · "+item.channel)); row.append(title);
  const priority=node("td"); priority.append(node("span",item.priority,"badge priority-"+item.priority)); row.append(priority);
  const status=node("td"); status.append(node("span",statusLabels[item.status],"badge status-"+item.status)); row.append(status);
  row.append(node("td",item.location || item.city),node("td",item.assignee || "Unassigned"),node("td",new Date(item.created*1000).toLocaleDateString()));
  el("incidentList").append(row);
}
let drawerRequest = 0;
async function openIncident(id) {
  const request = ++drawerRequest;
  const current=generation;
  el("drawerTitle").textContent="Loading incident…";
  el("drawerContent").replaceChildren();
  if (!el("incidentDrawer").open) el("incidentDrawer").showModal();
  try {
    const incident=await getJSON("/incidents/"+id);
    if(current!==generation || request!==drawerRequest) return;
    el("drawerTitle").textContent="#"+incident.id+" · "+incident.title;
    const content=el("drawerContent");
    content.append(node("span",statusLabels[incident.status],"badge status-"+incident.status),document.createTextNode(" "),node("span",incident.priority,"badge priority-"+incident.priority));
    const meta=node("div",undefined,"detail-meta");
    for (const [label,value] of [["CHANNEL",incident.channel],["LOCATION",incident.location || incident.city],["REPORTED BY",incident.author],["ASSIGNED TO",incident.assignee || "Unassigned"]]) {
      const cell=node("div");cell.append(node("small",label),node("span",value));meta.append(cell);
    }
    content.append(meta,node("p",incident.description,"drawer-description"));
    content.append(node("p", "Created "+new Date(incident.created*1000).toLocaleString(),"muted small"));
    const delivery={submitted:"Message submitted to STOMP. Individual delivery is not guaranteed.",pending:"Transmission pending.",unknown:"Transmission outcome unknown. This incident is safely stored."};
    content.append(node("p",delivery[incident.delivery],"muted small"),node("h3","Activity timeline"));
    const audit=node("ol",undefined,"audit-list");
    for(const entry of incident.audit){
      let change="Created this incident";
      if(entry.action==="updated"){
        const d=JSON.parse(entry.details);
        change=statusLabels[d.status.from]+" → "+statusLabels[d.status.to]+" · "+(d.assignee.to || "Unassigned");
      }
      audit.append(node("li",entry.actor+" · "+change+" · "+new Date(entry.at*1000).toLocaleString()));
    }
    content.append(audit);
    if(!["admin","responder"].includes(currentRole)) return;
    const form=node("form",undefined,"incident-actions");
    const stateLabel=node("label","Status");const select=node("select");
    for(const [value,label] of Object.entries(statusLabels)){const option=node("option",label);option.value=value;select.append(option);}
    select.value=incident.status;stateLabel.append(select);
    const ownerLabel=node("label","Assigned responder");const owner=node("input");
    owner.value=incident.assignee || (currentRole==="responder" ? currentUser : "");
    owner.placeholder="Responder username";owner.maxLength=32;owner.readOnly=currentRole!=="admin";ownerLabel.append(owner);
    const submit=node("button","Save changes","primary");const notice=node("p","","notice");notice.setAttribute("role","status");form.append(stateLabel,ownerLabel,submit,notice);
    form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;
      try{await authRequest("/incidents/update",{id:incident.id,version:incident.version,status:select.value,assignee:owner.value.trim()});
        if(current===generation){await openIncident(id);await loadIncidents();}
      }catch(error){notice.textContent=error.message;notice.classList.add("error");}finally{submit.disabled=false;}
    };content.append(form);
  }catch(error){if(current===generation) el("drawerContent").replaceChildren(node("p",error.message,"error"));}
}
el("closeDrawer").onclick=()=>{drawerRequest++;el("incidentDrawer").close();};
el("quickReport").onclick=()=>showView("reportsView");
async function refreshOverview(){
  const current=generation;
  try{const data=await getJSON("/overview");if(current!==generation)return;
    for(const [id,key] of [["overviewOpen","open"],["overviewUrgent","urgent"],["overviewMine","mine"],["overviewAging","aging"]])el(id).textContent=data[key];
  }catch(error){if(current===generation)message("incidentNotice",error.message,true);}
}
let latestNotifications=[];
async function refreshNotifications(){
  const current=generation;
  try{if(!connected)return;const data=await getJSON("/notifications");if(current!==generation)return;
    latestNotifications=data.items;el("notificationCount").textContent=data.items.filter(n=>!n.seen).length;
  }catch(error){}finally{setTimeout(refreshNotifications,5000);}
}
el("notificationsButton").onclick=async()=>{
  const current=generation;el("notificationList").replaceChildren();
  el("notificationDialog").showModal();
  el("notificationsButton").setAttribute("aria-expanded", "true");
  try{const data=await getJSON("/notifications");if(current!==generation)return;
    for(const n of data.items){const button=node("button","#"+n.incident_id+" · "+n.title,"notification-item"+(n.seen?"":" unread"));
      button.append(node("small",n.actor+" assigned this to you · "+new Date(n.created*1000).toLocaleString()));
      button.onclick=()=>{el("notificationDialog").close();openIncident(n.incident_id);};el("notificationList").append(button);
    }
    if(!data.items.length)el("notificationList").append(node("p","No assignments yet. You’re all caught up.","muted"));
    await authRequest("/notifications/read",{ids:data.items.map(n=>n.id)});
    if(current===generation)el("notificationCount").textContent="0";
  }catch(error){if(current===generation)el("notificationList").append(node("p",error.message,"error"));}
};
el("closeInbox").onclick=()=>el("notificationDialog").close();
refreshNotifications();

function options(id, values) {
  const selected=el(id).value;
  el(id).replaceChildren();
  for (const [value,label] of values) {
    const option=node("option",label); option.value=value; el(id).append(option);
  }
  if (values.some(([value])=>value===selected)) el(id).value=selected;
}
async function loadAccess() {
  const current=generation;
  try {
    const data=await getJSON("/access");
    if (current!==generation || !isAdmin) return;
    options("roleUser",data.users.map(u=>[u.username,u.username+" · "+u.role]));
    el("roleUser").onchange = () => {
      const selected = data.users.find(u => u.username === el("roleUser").value);
      el("roleValue").value = selected ? selected.role : "user";
      const self = el("roleUser").value === currentUser;
      el("roleValue").disabled = self;
      el("saveRole").disabled = self;
      message("roleHint", self ? "This is your current role. Another administrator must change it." : "");
    };
    el("roleUser").onchange();
    options("memberUser",data.users.map(u=>[u.username,u.username]));
    options("memberChannel",data.channels.map(c=>[c.name,c.name]));
    el("accessSummary").replaceChildren();
    for (const channel of data.channels) {
      const members=data.members.filter(m=>m.channel===channel.name).map(m=>m.username);
      el("accessSummary").append(node("p",channel.name+" · "+(channel.restricted ? "Restricted" : "Public")+" · Members: "+(members.join(", ") || "none"),"small"));
    }
    el("accessHistory").replaceChildren();
    for (const entry of data.audit) el("accessHistory").append(node("p",new Date(entry.at*1000).toLocaleString()+" · "+entry.actor+" · "+entry.details,"small"));
  } catch (error) { if (current===generation) message("accessNotice",error.message,true); }
}
for (const id of ["roleForm","policyForm","memberForm"]) el(id).onsubmit=async event => {
  event.preventDefault();
  const button=event.currentTarget.querySelector("button"); button.disabled=true;
  const data=id==="roleForm" ? {action:"role",username:el("roleUser").value,role:el("roleValue").value}
    : id==="policyForm" ? {action:"channel",channel:el("policyChannel").value.trim(),restricted:el("policyRestricted").value==="true"}
    : {action:"member",channel:el("memberChannel").value,username:el("memberUser").value,grant:el("memberGrant").value==="true"};
  try { await authRequest("/access",data); message("accessNotice","Saved. Affected users must sign in again."); await loadAccess(); }
  catch(error) { message("accessNotice",error.message,true); }
  finally { button.disabled=id === "roleForm" && el("roleUser").value === currentUser; }
};


el("showAccountPassword").onclick = () => {
  const show = el("currentPassword").type === "password";
  for (const id of ["currentPassword","newPassword","newPasswordConfirm"]) el(id).type = show ? "text" : "password";
  el("showAccountPassword").textContent = show ? "Hide passwords" : "Show passwords";
  el("showAccountPassword").setAttribute("aria-pressed", String(show));
};
el("passwordForm").onsubmit = async event => {
  event.preventDefault();
  if (el("newPassword").value !== el("newPasswordConfirm").value) {
    message("passwordNotice", "New passwords do not match.", true);
    return;
  }
  el("savePassword").disabled = true;
  try {
    await authRequest("/auth/password", {
      current_password: el("currentPassword").value,
      new_password: el("newPassword").value,
      confirm_password: el("newPasswordConfirm").value
    });
    authMode(false);
    resetSession("Password changed. Sign in with your new password.");
  } catch (error) { message("passwordNotice", error.message, true); }
  finally { el("savePassword").disabled = false; }
};

el("notificationDialog").addEventListener("close",()=>el("notificationsButton").setAttribute("aria-expanded","false"));
