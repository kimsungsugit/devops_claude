import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef } from "react";

// ── Toast Context ────────────────────────────────────────────────────

const ToastContext = createContext(null);

let _toastId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const showToast = useCallback((type, message, duration) => {
    const id = ++_toastId;
    setToasts((prev) => [...prev, { id, type, message, duration }]);
  }, []);
  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);
  const value = useMemo(() => ({ toasts, showToast, removeToast }), [toasts, showToast, removeToast]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}


// ── Confirm Dialog Context ───────────────────────────────────────────

const ConfirmContext = createContext(null);

export function ConfirmProvider({ children }) {
  const [confirmState, setConfirmState] = useState(null);
  const askConfirm = useCallback((opts) => {
    return new Promise((resolve) => {
      setConfirmState({ ...opts, resolve });
    });
  }, []);
  const handleOk = useCallback(() => {
    confirmState?.resolve(true);
    setConfirmState(null);
  }, [confirmState]);
  const handleCancel = useCallback(() => {
    confirmState?.resolve(false);
    setConfirmState(null);
  }, [confirmState]);
  const value = useMemo(
    () => ({ confirmState, askConfirm, handleOk, handleCancel }),
    [confirmState, askConfirm, handleOk, handleCancel],
  );
  return <ConfirmContext.Provider value={value}>{children}</ConfirmContext.Provider>;
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}


// ── UI Navigation Context ────────────────────────────────────────────

const UIContext = createContext(null);

export function UIProvider({ children }) {
  const [mode, setMode] = useState("local");
  const [primaryView, setPrimaryView] = useState("dashboard");
  const [localPrimaryView, setLocalPrimaryView] = useState("dashboard");
  const [jenkinsPrimaryView, setJenkinsPrimaryView] = useState("dashboard");
  const [activeTab, setActiveTab] = useState("overview");
  const [activeJenkinsTab, setActiveJenkinsTab] = useState("project");
  const [detailTab, setDetailTab] = useState("status");
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "light";
    return window.localStorage.getItem("devops_theme") || "light";
  });

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem("devops_theme", next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      mode, setMode,
      primaryView, setPrimaryView,
      localPrimaryView, setLocalPrimaryView,
      jenkinsPrimaryView, setJenkinsPrimaryView,
      activeTab, setActiveTab,
      activeJenkinsTab, setActiveJenkinsTab,
      detailTab, setDetailTab,
      theme, setTheme, toggleTheme,
    }),
    [mode, primaryView, localPrimaryView, jenkinsPrimaryView, activeTab, activeJenkinsTab, detailTab, theme, toggleTheme],
  );
  return <UIContext.Provider value={value}>{children}</UIContext.Provider>;
}

export function useUI() {
  const ctx = useContext(UIContext);
  if (!ctx) throw new Error("useUI must be used within UIProvider");
  return ctx;
}


// ── Session Context ──────────────────────────────────────────────────

const STORAGE_KEYS = {
  SESSION_ID: "devops_session_id",
  JENKINS: "devops_jenkins",
};

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(STORAGE_KEYS.SESSION_ID) || "";
  });
  const [sessionName, setSessionName] = useState("");
  const [config, setConfig] = useState(null);

  const persistSessionId = useCallback((id) => {
    setSessionId(id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEYS.SESSION_ID, id || "");
    }
  }, []);

  const value = useMemo(
    () => ({
      sessions, setSessions,
      sessionId, setSessionId: persistSessionId,
      sessionName, setSessionName,
      config, setConfig,
      STORAGE_KEYS,
    }),
    [sessions, sessionId, sessionName, config, persistSessionId],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}


// ── Jenkins Config Context ───────────────────────────────────────────

const JENKINS_STORAGE_KEY = "devops_jenkins";

function _readJenkinsStorage(field, defaultValue) {
  if (typeof window === "undefined") return defaultValue;
  try {
    const s = window.localStorage.getItem(JENKINS_STORAGE_KEY);
    if (!s) return defaultValue;
    const v = JSON.parse(s)[field];
    return v !== undefined && v !== null ? v : defaultValue;
  } catch {
    return defaultValue;
  }
}

const JenkinsConfigContext = createContext(null);

export function JenkinsConfigProvider({ children }) {
  const [jenkinsBaseUrl, setJenkinsBaseUrl] = useState(() => _readJenkinsStorage("jenkinsBaseUrl", ""));
  const [jenkinsJobUrl, setJenkinsJobUrl] = useState(() => _readJenkinsStorage("jenkinsJobUrl", ""));
  const [jenkinsUsername, setJenkinsUsername] = useState(() => _readJenkinsStorage("jenkinsUsername", ""));
  const [jenkinsToken, setJenkinsToken] = useState(() => _readJenkinsStorage("jenkinsToken", ""));
  const [jenkinsVerifyTls, setJenkinsVerifyTls] = useState(() => _readJenkinsStorage("jenkinsVerifyTls", true) !== false);
  const [jenkinsCacheRoot, setJenkinsCacheRoot] = useState(() => _readJenkinsStorage("jenkinsCacheRoot", ""));
  const [jenkinsBuildSelector, setJenkinsBuildSelector] = useState(() => _readJenkinsStorage("jenkinsBuildSelector", "lastSuccessfulBuild"));
  const [jenkinsServerRoot, setJenkinsServerRoot] = useState(() => _readJenkinsStorage("jenkinsServerRoot", "C:\\ProgramData\\Jenkins\\.jenkins"));
  const [jenkinsServerRelPath, setJenkinsServerRelPath] = useState(() => _readJenkinsStorage("jenkinsServerRelPath", "workspace"));
  const [jenkinsScmType, setJenkinsScmType] = useState(() => _readJenkinsStorage("jenkinsScmType", "svn"));
  const [jenkinsScmUrl, setJenkinsScmUrl] = useState(() => _readJenkinsStorage("jenkinsScmUrl", ""));
  const [jenkinsScmUsername, setJenkinsScmUsername] = useState(() => _readJenkinsStorage("jenkinsScmUsername", ""));
  const [jenkinsScmPassword, setJenkinsScmPassword] = useState(() => _readJenkinsStorage("jenkinsScmPassword", ""));
  const [jenkinsScmBranch, setJenkinsScmBranch] = useState(() => _readJenkinsStorage("jenkinsScmBranch", ""));
  const [jenkinsScmRevision, setJenkinsScmRevision] = useState(() => _readJenkinsStorage("jenkinsScmRevision", ""));

  const persistRef = useRef(null);
  persistRef.current = {
    jenkinsBaseUrl, jenkinsJobUrl, jenkinsUsername, jenkinsToken,
    jenkinsVerifyTls, jenkinsCacheRoot, jenkinsBuildSelector,
    jenkinsServerRoot, jenkinsServerRelPath,
    jenkinsScmType, jenkinsScmUrl, jenkinsScmUsername, jenkinsScmPassword,
    jenkinsScmBranch, jenkinsScmRevision,
  };

  const depsArray = [
    jenkinsBaseUrl, jenkinsJobUrl, jenkinsUsername, jenkinsToken,
    jenkinsVerifyTls, jenkinsCacheRoot, jenkinsBuildSelector,
    jenkinsServerRoot, jenkinsServerRelPath,
    jenkinsScmType, jenkinsScmUrl, jenkinsScmUsername, jenkinsScmPassword,
    jenkinsScmBranch, jenkinsScmRevision,
  ];

  /* eslint-disable react-hooks/exhaustive-deps */
  useMemo(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(JENKINS_STORAGE_KEY, JSON.stringify(persistRef.current));
    } catch { /* quota */ }
  }, depsArray);
  /* eslint-enable react-hooks/exhaustive-deps */

  const value = useMemo(
    () => ({
      jenkinsBaseUrl, setJenkinsBaseUrl,
      jenkinsJobUrl, setJenkinsJobUrl,
      jenkinsUsername, setJenkinsUsername,
      jenkinsToken, setJenkinsToken,
      jenkinsVerifyTls, setJenkinsVerifyTls,
      jenkinsCacheRoot, setJenkinsCacheRoot,
      jenkinsBuildSelector, setJenkinsBuildSelector,
      jenkinsServerRoot, setJenkinsServerRoot,
      jenkinsServerRelPath, setJenkinsServerRelPath,
      jenkinsScmType, setJenkinsScmType,
      jenkinsScmUrl, setJenkinsScmUrl,
      jenkinsScmUsername, setJenkinsScmUsername,
      jenkinsScmPassword, setJenkinsScmPassword,
      jenkinsScmBranch, setJenkinsScmBranch,
      jenkinsScmRevision, setJenkinsScmRevision,
      JENKINS_STORAGE_KEY,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    depsArray,
  );
  return <JenkinsConfigContext.Provider value={value}>{children}</JenkinsConfigContext.Provider>;
}

export function useJenkinsConfig() {
  const ctx = useContext(JenkinsConfigContext);
  if (!ctx) throw new Error("useJenkinsConfig must be used within JenkinsConfigProvider");
  return ctx;
}


// ── Chat Context ─────────────────────────────────────────────────────

const CHAT_STORAGE_KEY = "devops_chat_messages";
const _defaultChatMessage = { role: "assistant", text: "대시보드 요약을 해석하거나 다음 단계 추천을 도와드릴게요.", ts: Date.now() };

function _readChatStorage() {
  if (typeof window === "undefined") return [_defaultChatMessage];
  try {
    const s = window.localStorage.getItem(CHAT_STORAGE_KEY);
    if (s) { const p = JSON.parse(s); if (Array.isArray(p) && p.length) return p; }
  } catch { /* ignore */ }
  return [_defaultChatMessage];
}

const ChatContext = createContext(null);

export function ChatProvider({ children }) {
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState(_readChatStorage);
  const [chatPending, setChatPending] = useState(false);
  const [chatSidebarOpen, setChatSidebarOpen] = useState(true);
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
  const chatEndRef = useRef(null);
  const lastChatQuestion = useRef("");

  useEffect(() => {
    try { window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(chatMessages.slice(-50))); } catch { /* quota */ }
  }, [chatMessages]);

  const value = useMemo(
    () => ({
      chatInput, setChatInput,
      chatMessages, setChatMessages,
      chatPending, setChatPending,
      chatSidebarOpen, setChatSidebarOpen,
      chatDrawerOpen, setChatDrawerOpen,
      chatEndRef, lastChatQuestion,
    }),
    [chatInput, chatMessages, chatPending, chatSidebarOpen, chatDrawerOpen],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}


// ── UDS Context ──────────────────────────────────────────────────────

const UDSContext = createContext(null);

export function UDSProvider({ children }) {
  const [udsTemplatePath, setUdsTemplatePath] = useState("");
  const [udsUploading, setUdsUploading] = useState(false);
  const [udsGenerating, setUdsGenerating] = useState(false);
  const [udsResultUrl, setUdsResultUrl] = useState("");
  const [udsVersions, setUdsVersions] = useState([]);
  const [udsPreviewHtml, setUdsPreviewHtml] = useState("");
  const [udsPlaceholders, setUdsPlaceholders] = useState([]);
  const [udsSourceOnly, setUdsSourceOnly] = useState(false);
  const [udsReqPreview, setUdsReqPreview] = useState(null);
  const [udsReqMapping, setUdsReqMapping] = useState([]);
  const [udsReqCompare, setUdsReqCompare] = useState(null);
  const [udsReqFunctionMapping, setUdsReqFunctionMapping] = useState(null);
  const [udsReqTraceability, setUdsReqTraceability] = useState(null);
  const [udsReqTraceMatrix, setUdsReqTraceMatrix] = useState(null);
  const [udsDiff, setUdsDiff] = useState(null);

  const value = useMemo(
    () => ({
      udsTemplatePath, setUdsTemplatePath,
      udsUploading, setUdsUploading,
      udsGenerating, setUdsGenerating,
      udsResultUrl, setUdsResultUrl,
      udsVersions, setUdsVersions,
      udsPreviewHtml, setUdsPreviewHtml,
      udsPlaceholders, setUdsPlaceholders,
      udsSourceOnly, setUdsSourceOnly,
      udsReqPreview, setUdsReqPreview,
      udsReqMapping, setUdsReqMapping,
      udsReqCompare, setUdsReqCompare,
      udsReqFunctionMapping, setUdsReqFunctionMapping,
      udsReqTraceability, setUdsReqTraceability,
      udsReqTraceMatrix, setUdsReqTraceMatrix,
      udsDiff, setUdsDiff,
    }),
    [udsTemplatePath, udsUploading, udsGenerating, udsResultUrl, udsVersions,
     udsPreviewHtml, udsPlaceholders, udsSourceOnly, udsReqPreview, udsReqMapping,
     udsReqCompare, udsReqFunctionMapping, udsReqTraceability, udsReqTraceMatrix, udsDiff],
  );
  return <UDSContext.Provider value={value}>{children}</UDSContext.Provider>;
}

export function useUDS() {
  const ctx = useContext(UDSContext);
  if (!ctx) throw new Error("useUDS must be used within UDSProvider");
  return ctx;
}


// ── Combined Provider ────────────────────────────────────────────────

export function AppProviders({ children }) {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <UIProvider>
          <SessionProvider>
            <JenkinsConfigProvider>
              <ChatProvider>
                <UDSProvider>
                  {children}
                </UDSProvider>
              </ChatProvider>
            </JenkinsConfigProvider>
          </SessionProvider>
        </UIProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}
