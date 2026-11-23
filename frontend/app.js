(() => {
  const API_BASE = window.APP_CONFIG.API_BASE_URL;
  const STORAGE_TOKEN_KEY = "docrag_token";
  const STORAGE_USER_KEY = "docrag_user";

  const state = {
    token: localStorage.getItem(STORAGE_TOKEN_KEY) || null,
    user: JSON.parse(localStorage.getItem(STORAGE_USER_KEY) || "null"),
    documents: [],
    activeDocumentId: null,
    isUploading: false,
    isAsking: false,
  };

  // Elementos DOM
  const authView = document.getElementById("auth-view");
  const appView = document.getElementById("app-view");
  const tabLogin = document.getElementById("tab-login");
  const tabRegister = document.getElementById("tab-register");
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const authAlert = document.getElementById("auth-alert");
  const apiEnvBadge = document.getElementById("api-env-badge");

  const userNameEl = document.getElementById("user-name");
  const userEmailEl = document.getElementById("user-email");
  const logoutBtn = document.getElementById("logout-btn");

  const dropzone = document.getElementById("dropzone");
  const pdfInput = document.getElementById("pdf-input");
  const uploadStatus = document.getElementById("upload-status");
  const uploadStatusText = document.getElementById("upload-status-text");
  const docsCountBadge = document.getElementById("docs-count-badge");
  const documentsList = document.getElementById("documents-list");

  const noDocSelected = document.getElementById("no-doc-selected");
  const chatContainer = document.getElementById("chat-container");
  const activeDocTitle = document.getElementById("active-doc-title");
  const activeDocChunks = document.getElementById("active-doc-chunks");
  const activeDocDate = document.getElementById("active-doc-date");
  const deleteActiveDocBtn = document.getElementById("delete-active-doc-btn");
  const messagesArea = document.getElementById("messages-area");
  const quickPrompts = document.getElementById("quick-prompts");
  const queryForm = document.getElementById("query-form");
  const questionInput = document.getElementById("question-input");
  const askSubmit = document.getElementById("ask-submit");
  const toastContainer = document.getElementById("toast-container");

  function escapeHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatAnswerText(text) {
    const escaped = escapeHtml(text);
    return escaped
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function formatDate(isoString) {
    if (!isoString) return "--";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return "--";
    return date.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function showToast(message, isError = false) {
    const toast = document.createElement("div");
    toast.className = `toast${isError ? " error" : ""}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4200);
  }

  function showAuthAlert(message, isSuccess = false) {
    authAlert.textContent = message;
    authAlert.className = `inline-alert${isSuccess ? " success" : ""}`;
  }

  function clearAuthAlert() {
    authAlert.className = "inline-alert hidden";
    authAlert.textContent = "";
  }

  function setAuthTab(mode) {
    clearAuthAlert();
    const isLogin = mode === "login";
    tabLogin.classList.toggle("active", isLogin);
    tabRegister.classList.toggle("active", !isLogin);
    tabLogin.setAttribute("aria-selected", String(isLogin));
    tabRegister.setAttribute("aria-selected", String(!isLogin));
    loginForm.classList.toggle("hidden", !isLogin);
    registerForm.classList.toggle("hidden", isLogin);
  }

  function saveSession(token, user) {
    state.token = token;
    state.user = user;
    localStorage.setItem(STORAGE_TOKEN_KEY, token);
    localStorage.setItem(STORAGE_USER_KEY, JSON.stringify(user));
  }

  function clearSession(noticeMessage = "") {
    state.token = null;
    state.user = null;
    state.documents = [];
    state.activeDocumentId = null;
    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_USER_KEY);
    renderView();
    if (noticeMessage) {
      showAuthAlert(noticeMessage, false);
    }
  }

  function extractErrorMessage(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === "string") return payload.detail;
    const firstKey = Object.keys(payload)[0];
    if (firstKey && Array.isArray(payload[firstKey])) {
      return `${firstKey}: ${payload[firstKey][0]}`;
    }
    return fallback;
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token && !options.skipAuth) {
      headers.set("Authorization", `Bearer ${state.token}`);
    }

    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return null;
    }

    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (response.status === 401 && !options.skipAuth) {
      clearSession("Sua sessão expirou. Faça login novamente.");
      throw new Error("Sessão expirada.");
    }

    if (!response.ok) {
      throw new Error(extractErrorMessage(data, `Erro HTTP ${response.status}`));
    }

    return data;
  }

  async function checkApiHealth() {
    try {
      const data = await apiRequest("/health", { skipAuth: true });
      apiEnvBadge.textContent =
        data && data.pgvector
          ? `API online (${API_BASE}) • pgvector ativo`
          : `API online (${API_BASE})`;
    } catch {
      apiEnvBadge.textContent = `API indisponível em ${API_BASE}`;
    }
  }

  function renderView() {
    const loggedIn = Boolean(state.token && state.user);
    authView.classList.toggle("hidden", loggedIn);
    appView.classList.toggle("hidden", !loggedIn);

    if (loggedIn) {
      userNameEl.textContent = state.user.name || "Usuário";
      userEmailEl.textContent = state.user.email || "";
      loadDocuments();
    } else {
      checkApiHealth();
    }
  }

  function renderDocumentsList() {
    docsCountBadge.textContent = String(state.documents.length);

    if (state.documents.length === 0) {
      documentsList.innerHTML =
        '<div class="empty-docs">Nenhum PDF enviado ainda. Faça upload de um documento acima para começar.</div>';
      noDocSelected.classList.remove("hidden");
      chatContainer.classList.add("hidden");
      return;
    }

    documentsList.innerHTML = state.documents
      .map((doc) => {
        const isActive = doc.id === state.activeDocumentId;
        return `
          <div class="doc-item${isActive ? " active" : ""}" data-doc-id="${escapeHtml(doc.id)}">
            <div class="doc-item-title">${escapeHtml(doc.filename)}</div>
            <div class="doc-item-meta">
              <span>${escapeHtml(doc.chunks_count ?? 0)} trechos</span>
              <span>${escapeHtml(formatDate(doc.created_at))}</span>
            </div>
          </div>
        `;
      })
      .join("");

    documentsList.querySelectorAll(".doc-item").forEach((el) => {
      el.addEventListener("click", () => {
        selectDocument(el.dataset.docId);
      });
    });
  }

  async function loadDocuments() {
    try {
      const docs = await apiRequest("/documents");
      state.documents = Array.isArray(docs) ? docs : [];

      if (
        state.activeDocumentId &&
        !state.documents.some((d) => d.id === state.activeDocumentId)
      ) {
        state.activeDocumentId = null;
      }

      if (!state.activeDocumentId && state.documents.length > 0) {
        state.activeDocumentId = state.documents[0].id;
      }

      renderDocumentsList();

      if (state.activeDocumentId) {
        await selectDocument(state.activeDocumentId);
      } else {
        noDocSelected.classList.remove("hidden");
        chatContainer.classList.add("hidden");
      }
    } catch (err) {
      if (state.token) {
        showToast(`Erro ao carregar documentos: ${err.message}`, true);
      }
    }
  }

  async function selectDocument(docId) {
    const doc = state.documents.find((d) => d.id === docId);
    if (!doc) return;

    state.activeDocumentId = doc.id;
    renderDocumentsList();

    noDocSelected.classList.add("hidden");
    chatContainer.classList.remove("hidden");

    activeDocTitle.textContent = doc.filename;
    activeDocChunks.textContent = `${doc.chunks_count ?? 0} trechos indexados`;
    activeDocDate.textContent = `Enviado em ${formatDate(doc.created_at)}`;

    messagesArea.innerHTML =
      '<div class="chat-empty-history">Carregando histórico de consultas...</div>';

    try {
      const history = await apiRequest(`/documents/${doc.id}/queries`);
      renderMessages(Array.isArray(history) ? history : []);
    } catch (err) {
      messagesArea.innerHTML =
        '<div class="chat-empty-history">Não foi possível carregar o histórico deste documento.</div>';
      showToast(`Erro ao carregar histórico: ${err.message}`, true);
    }
  }

  function buildSourcesHtml(sources) {
    if (!Array.isArray(sources) || sources.length === 0) return "";
    const items = sources
      .map((src, idx) => {
        const pct = Math.round((src.similarity || 0) * 100);
        return `
          <div class="source-item">
            <span class="source-score">Trecho ${idx + 1} • Similaridade ${pct}%</span>
            <div class="source-text">${escapeHtml(src.content)}</div>
          </div>
        `;
      })
      .join("");

    return `
      <details class="sources-details">
        <summary>Ver trechos recuperados do documento (Top-${sources.length} pgvector)</summary>
        ${items}
      </details>
    `;
  }

  function createQaElement(item) {
    const group = document.createElement("div");
    group.className = "qa-group";
    group.innerHTML = `
      <div class="bubble bubble-user">
        <div>${escapeHtml(item.question)}</div>
        <div class="bubble-meta">${escapeHtml(formatDate(item.created_at))}</div>
      </div>
      <div class="bubble bubble-assistant">
        <div>${formatAnswerText(item.answer)}</div>
        ${buildSourcesHtml(item.sources)}
      </div>
    `;
    return group;
  }

  function renderMessages(items) {
    messagesArea.innerHTML = "";

    if (items.length === 0) {
      messagesArea.innerHTML =
        '<div class="chat-empty-history">Nenhuma consulta realizada ainda neste documento. Envie sua primeira pergunta abaixo!</div>';
      quickPrompts.classList.remove("hidden");
      return;
    }

    quickPrompts.classList.add("hidden");
    items.forEach((item) => {
      messagesArea.appendChild(createQaElement(item));
    });
    messagesArea.scrollTop = messagesArea.scrollHeight;
  }

  async function handlePdfUpload(file) {
    if (!file || state.isUploading) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showToast("Selecione um arquivo com extensão .pdf.", true);
      return;
    }

    if (file.size > 20 * 1024 * 1024) {
      showToast("O arquivo excede o limite de 20 MB.", true);
      return;
    }

    state.isUploading = true;
    uploadStatus.classList.remove("hidden");
    uploadStatusText.textContent = `Indexando "${file.name}" (pypdf + embeddings 768D)...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const created = await apiRequest("/documents", {
        method: "POST",
        body: formData,
      });

      showToast(
        `PDF "${created.filename}" indexado (${created.chunks_count} trechos)!`
      );
      state.documents.unshift(created);
      state.activeDocumentId = created.id;
      renderDocumentsList();
      await selectDocument(created.id);
    } catch (err) {
      showToast(`Falha no upload: ${err.message}`, true);
    } finally {
      state.isUploading = false;
      uploadStatus.classList.add("hidden");
      pdfInput.value = "";
    }
  }

  async function handleDeleteActiveDocument() {
    const doc = state.documents.find((d) => d.id === state.activeDocumentId);
    if (!doc) return;

    const confirmed = window.confirm(
      `Deseja excluir permanentemente "${doc.filename}" e todo o seu histórico de consultas?`
    );
    if (!confirmed) return;

    deleteActiveDocBtn.disabled = true;
    try {
      await apiRequest(`/documents/${doc.id}`, { method: "DELETE" });
      showToast(`Documento "${doc.filename}" excluído.`);
      state.documents = state.documents.filter((d) => d.id !== doc.id);
      state.activeDocumentId =
        state.documents.length > 0 ? state.documents[0].id : null;
      renderDocumentsList();
      if (state.activeDocumentId) {
        await selectDocument(state.activeDocumentId);
      } else {
        noDocSelected.classList.remove("hidden");
        chatContainer.classList.add("hidden");
      }
    } catch (err) {
      showToast(`Erro ao excluir documento: ${err.message}`, true);
    } finally {
      deleteActiveDocBtn.disabled = false;
    }
  }

  async function handleAskQuestion(questionText) {
    const question = questionText.trim();
    if (!question || !state.activeDocumentId || state.isAsking) return;

    state.isAsking = true;
    askSubmit.disabled = true;
    questionInput.disabled = true;
    quickPrompts.classList.add("hidden");

    const emptyNotice = messagesArea.querySelector(".chat-empty-history");
    if (emptyNotice) emptyNotice.remove();

    const pendingGroup = document.createElement("div");
    pendingGroup.className = "qa-group";
    pendingGroup.innerHTML = `
      <div class="bubble bubble-user">
        <div>${escapeHtml(question)}</div>
      </div>
      <div class="bubble bubble-assistant">
        <div class="thinking-row">
          <span class="spinner"></span>
          <span>Buscando trechos no pgvector e gerando resposta fundamentada...</span>
        </div>
      </div>
    `;
    messagesArea.appendChild(pendingGroup);
    messagesArea.scrollTop = messagesArea.scrollHeight;

    try {
      const result = await apiRequest(
        `/documents/${state.activeDocumentId}/queries`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        }
      );

      pendingGroup.replaceWith(createQaElement(result));
      questionInput.value = "";
      messagesArea.scrollTop = messagesArea.scrollHeight;
    } catch (err) {
      pendingGroup.remove();
      showToast(`Erro ao consultar documento: ${err.message}`, true);
    } finally {
      state.isAsking = false;
      askSubmit.disabled = false;
      questionInput.disabled = false;
      questionInput.focus();
    }
  }

  // Eventos de Autenticação
  tabLogin.addEventListener("click", () => setAuthTab("login"));
  tabRegister.addEventListener("click", () => setAuthTab("register"));

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearAuthAlert();
    const submitBtn = document.getElementById("login-submit");
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;

    submitBtn.disabled = true;
    submitBtn.textContent = "Entrando...";
    try {
      const data = await apiRequest("/auth/login", {
        method: "POST",
        skipAuth: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      saveSession(data.access_token, data.user);
      loginForm.reset();
      showToast(`Bem-vindo(a), ${data.user.name}!`);
      renderView();
    } catch (err) {
      showAuthAlert(err.message, false);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Entrar no Sistema";
    }
  });

  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearAuthAlert();
    const submitBtn = document.getElementById("register-submit");
    const name = document.getElementById("register-name").value.trim();
    const email = document.getElementById("register-email").value.trim();
    const password = document.getElementById("register-password").value;

    submitBtn.disabled = true;
    submitBtn.textContent = "Criando conta...";
    try {
      await apiRequest("/users", {
        method: "POST",
        skipAuth: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      registerForm.reset();
      setAuthTab("login");
      document.getElementById("login-email").value = email;
      showAuthAlert("Conta criada com sucesso! Agora faça login.", true);
    } catch (err) {
      showAuthAlert(err.message, false);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Criar Conta";
    }
  });

  logoutBtn.addEventListener("click", () => {
    clearSession();
    showToast("Você saiu da sua conta.");
  });

  // Eventos de Upload (clique + drag & drop)
  pdfInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handlePdfUpload(file);
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) handlePdfUpload(file);
  });

  deleteActiveDocBtn.addEventListener("click", handleDeleteActiveDocument);

  // Eventos do Chat
  queryForm.addEventListener("submit", (e) => {
    e.preventDefault();
    handleAskQuestion(questionInput.value);
  });

  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAskQuestion(questionInput.value);
    }
  });

  quickPrompts.querySelectorAll(".chip-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      questionInput.value = btn.dataset.prompt || "";
      handleAskQuestion(questionInput.value);
    });
  });

  // Inicialização
  renderView();
})();
