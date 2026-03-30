import { classNames } from "../utils/ui";

const PrimaryNav = ({ value, onChange, disableEditor }) => (
  <nav className="primary-nav" role="navigation" aria-label="주요 내비게이션">
    <button
      className={classNames("primary-btn", value === "dashboard" && "active")}
      onClick={() => onChange("dashboard")}
      aria-label="대시보드 탭"
      aria-current={value === "dashboard" ? "page" : undefined}
    >
      <span className="nav-icon nav-icon-dashboard" />
      대시보드
    </button>
    <button
      className={classNames("primary-btn", value === "workflow" && "active")}
      onClick={() => onChange("workflow")}
      aria-label="워크플로우 탭"
      aria-current={value === "workflow" ? "page" : undefined}
    >
      <span className="nav-icon nav-icon-workflow" />
      워크플로우
    </button>
    <button
      className={classNames("primary-btn", value === "editor" && "active")}
      onClick={() => onChange("editor")}
      disabled={disableEditor}
      aria-label="에디터 탭"
      aria-current={value === "editor" ? "page" : undefined}
    >
      <span className="nav-icon nav-icon-editor" />
      에디터
    </button>
    <button
      className={classNames("primary-btn", value === "analyzer" && "active")}
      onClick={() => onChange("analyzer")}
      aria-label="Analyzer 탭"
      aria-current={value === "analyzer" ? "page" : undefined}
    >
      <span className="nav-icon nav-icon-analyzer" />
      Analyzer
    </button>
    <button
      className={classNames("primary-btn", value === "settings" && "active")}
      onClick={() => onChange("settings")}
      aria-label="설정 탭"
      aria-current={value === "settings" ? "page" : undefined}
    >
      <span className="nav-icon nav-icon-settings" />
      설정
    </button>
  </nav>
);

export default PrimaryNav;
