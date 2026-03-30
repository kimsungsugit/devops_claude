import { memo, useRef } from "react";
import { classNames } from "../utils/ui";
import Icon from "../components/Icon";

const SettingsPanel = memo(
  ({
    mode,
    setMode,
    selectedProfile,
    setSelectedProfile,
    profiles,
    loadProfile,
    refreshProfiles,
    profileName,
    setProfileName,
    saveProfile,
    setShowProfileDelete,
    sessions,
    sessionId,
    setSessionId,
    createSession,
    deleteSession,
    sessionName,
    setSessionName,
    updateSessionName,
    config,
    updateConfig,
    options,
    updatePreset,
    splitList,
    joinList,
    pickDirectory,
    pickFile,
    appendConfigList,
    ragStatus,
    ragIngestResult,
    checkRagStatus,
    runRagIngest,
    switchRagToPgvector,
    loading,
    exportSession,
    refreshExports,
    cleanupExports,
    exports,
    deleteExport,
    restoreExport,
    pickerBusy,
    pickerLabel,
    message,
    jenkinsBaseUrl,
    setJenkinsBaseUrl,
    jenkinsUsername,
    setJenkinsUsername,
    jenkinsToken,
    setJenkinsToken,
    jenkinsVerifyTls,
    setJenkinsVerifyTls,
    jenkinsCacheRoot,
    setJenkinsCacheRoot,
    jenkinsBuildSelector,
    setJenkinsBuildSelector,
    jenkinsServerRoot,
    setJenkinsServerRoot,
    jenkinsServerRelPath,
    setJenkinsServerRelPath,
  }) => {
    const busyText = (fallback) => (pickerBusy ? "열리는 중..." : fallback);
    const callTreeExternalMapText = (() => {
      const raw = config?.call_tree_external_map;
      if (!raw) return "[]";
      if (typeof raw === "string") return raw;
      try {
        return JSON.stringify(raw, null, 2);
      } catch (e) {
        return "[]";
      }
    })();
    const callTreeHtmlTemplateText =
      typeof config?.call_tree_html_template === "string"
        ? config.call_tree_html_template
        : "";
    const callTreeMapInputRef = useRef(null);
    const callTreeTemplateInputRef = useRef(null);

    const downloadText = (filename, text, mime = "text/plain") => {
      const blob = new Blob([text || ""], { type: mime });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    };

    return (
      <div className="settings-panel">
        <div className="sidebar-group">
          <div className="sidebar-group-title">네비게이션</div>
          <h2 className="app-brand">
            <span className="brand-icon" />
            Devops
          </h2>
          <div className="section">
            <label>모드</label>
            <div className="segmented">
              <button
                className={classNames(
                  "segmented-btn",
                  mode === "local" && "active",
                )}
                onClick={() => setMode("local")}
              >
                로컬
              </button>
              <button
                className={classNames(
                  "segmented-btn",
                  mode === "jenkins" && "active",
                )}
                onClick={() => setMode("jenkins")}
              >
                Jenkins
              </button>
            </div>
          </div>
        </div>

        {pickerBusy ? (
          <div className="hint">폴더/파일 선택 창을 여는 중...</div>
        ) : null}

        {mode === "local" && (
          <div className="sidebar-group">
            <div className="sidebar-group-title">세션 & 프로파일</div>
            <div className="section">
              <label>설정 프로파일</label>
              <select
                value={selectedProfile}
                onChange={(e) => setSelectedProfile(e.target.value)}
              >
                <option value="">(선택)</option>
                {profiles.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <div className="row">
                <button onClick={loadProfile} disabled={!selectedProfile}>
                  불러오기
                </button>
                <button onClick={refreshProfiles}>새로고침</button>
              </div>
              <label>프로파일 이름</label>
              <input
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
              />
              <div className="row">
                <button
                  onClick={saveProfile}
                  disabled={!profileName || !config}
                >
                  저장
                </button>
                <button
                  onClick={() => setShowProfileDelete(true)}
                  disabled={!selectedProfile}
                >
                  삭제
                </button>
              </div>
            </div>
            <div className="section">
              <label>세션 선택</label>
              <select
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
              >
                <option value="">(선택)</option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {(s.name || s.id) + " · " + (s.generated_at || "-")}
                  </option>
                ))}
              </select>
              <div className="row">
                <button onClick={createSession}>새 세션</button>
                <button onClick={deleteSession} disabled={!sessionId}>
                  삭제
                </button>
              </div>
              <label>세션 이름</label>
              <input
                value={sessionName}
                onChange={(e) => setSessionName(e.target.value)}
              />
              <button onClick={updateSessionName} disabled={!sessionId}>
                이름 저장
              </button>
            </div>
          </div>
        )}

        {mode === "local" && config && (
          <div className="sidebar-group">
            <div className="sidebar-group-title">프로젝트 설정</div>
            <div className="settings-section-grid">
              <details className="section" open>
                <summary>
                  <span className="summary-icon">
                    <Icon name="folder" />
                  </span>
                  프로젝트 경로
                </summary>
                <label>프로젝트 루트</label>
                <div className="input-row">
                  <input
                    value={config.project_root || ""}
                    onChange={(e) =>
                      updateConfig("project_root", e.target.value)
                    }
                  />
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("프로젝트 루트 선택");
                      if (path) updateConfig("project_root", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
                <label>리포트 경로</label>
                <div className="input-row">
                  <input
                    value={config.report_dir || ""}
                    onChange={(e) => updateConfig("report_dir", e.target.value)}
                  />
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("리포트 폴더 선택");
                      if (path) updateConfig("report_dir", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
                <label>파일 패턴 (glob)</label>
                <input
                  value={config.targets_glob || ""}
                  onChange={(e) => updateConfig("targets_glob", e.target.value)}
                />
                <label>제외 폴더 (쉼표 구분)</label>
                <input
                  value={joinList(config.exclude_dirs)}
                  onChange={(e) =>
                    updateConfig("exclude_dirs", splitList(e.target.value))
                  }
                />
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.git_incremental}
                    onChange={(e) =>
                      updateConfig("git_incremental", e.target.checked)
                    }
                  />
                  변경 파일만 분석(Git)
                </label>
                <label>기준 브랜치/커밋 (Git diff 기준)</label>
                <input
                  value={config.git_base_ref || ""}
                  onChange={(e) => updateConfig("git_base_ref", e.target.value)}
                />
                <label>SCM 모드</label>
                <select
                  value={config.scm_mode || "auto"}
                  onChange={(e) => updateConfig("scm_mode", e.target.value)}
                >
                  <option value="auto">auto</option>
                  <option value="git">git</option>
                  <option value="svn">svn</option>
                </select>
                <label>기준 리비전/브랜치 (SVN diff 기준)</label>
                <input
                  value={config.svn_base_ref || ""}
                  onChange={(e) => updateConfig("svn_base_ref", e.target.value)}
                />
              </details>

              <details className="section">
                <summary>
                  <span className="summary-icon">
                    <Icon name="compass" />
                  </span>
                  소스 선택
                </summary>
                <label>소스 우선순위</label>
                <select
                  multiple
                  value={config.source_priority || []}
                  onChange={(e) =>
                    updateConfig(
                      "source_priority",
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                >
                  {(options.source_priority_options || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>로컬/서버 소스 경로(줄바꿈/콤마)</label>
                <textarea
                  rows={3}
                  value={
                    Array.isArray(config.local_source_roots)
                      ? config.local_source_roots.join("\n")
                      : ""
                  }
                  onChange={(e) =>
                    updateConfig(
                      "local_source_roots",
                      splitList(e.target.value),
                    )
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("소스 경로 추가");
                      appendConfigList("local_source_roots", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("폴더 추가")}
                  </button>
                </div>
                <label>아티팩트 빌드 성공 판정</label>
                <select
                  value={config.artifact_success_rule || "either"}
                  onChange={(e) =>
                    updateConfig("artifact_success_rule", e.target.value)
                  }
                >
                  {(options.artifact_success_rules || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>아티팩트 소스 경로(옵션)</label>
                <div className="input-row">
                  <input
                    value={config.artifact_source_root || ""}
                    onChange={(e) =>
                      updateConfig("artifact_source_root", e.target.value)
                    }
                  />
                  <button
                    onClick={async () => {
                      const path =
                        await pickDirectory("아티팩트 소스 폴더 선택");
                      if (path) updateConfig("artifact_source_root", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
              </details>

              <details className="section">
                <summary>
                  <span className="summary-icon">
                    <Icon name="chart" />
                  </span>
                  정적 분석
                </summary>
                <label>품질 프리셋</label>
                <select
                  value={config.quality_preset || "high"}
                  onChange={(e) => updatePreset(e.target.value)}
                >
                  {(options.quality_presets || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>Cppcheck 항목</label>
                <select
                  multiple
                  value={config.cppcheck_levels || []}
                  onChange={(e) =>
                    updateConfig(
                      "cppcheck_levels",
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                >
                  {(options.cppcheck_levels || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_clang_tidy}
                    onChange={(e) =>
                      updateConfig("do_clang_tidy", e.target.checked)
                    }
                  />
                  Clang-Tidy 활성화
                </label>
                <label>Clang-Tidy Checks (쉼표 또는 세미콜론 구분)</label>
                <input
                  value={joinList(config.clang_checks)}
                  onChange={(e) =>
                    updateConfig(
                      "clang_checks",
                      splitList(e.target.value.replace(/;/g, ",")),
                    )
                  }
                />
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.enable_semgrep}
                    onChange={(e) =>
                      updateConfig("enable_semgrep", e.target.checked)
                    }
                  />
                  Semgrep 활성화
                </label>
                <label>Semgrep Ruleset (예: p/ci, p/default)</label>
                <input
                  value={config.semgrep_config || ""}
                  onChange={(e) =>
                    updateConfig("semgrep_config", e.target.value)
                  }
                />
                <label>복잡도 경고 기준(CCN)</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={config.complexity_threshold || 10}
                  onChange={(e) =>
                    updateConfig("complexity_threshold", Number(e.target.value))
                  }
                />
              </details>

              <details className="section">
                <summary>
                  <span className="summary-icon">
                    <Icon name="target" />
                  </span>
                  콜 트리
                </summary>
                <label>외부 함수 매핑(JSON)</label>
                <textarea
                  rows={6}
                  value={callTreeExternalMapText}
                  onChange={(e) =>
                    updateConfig("call_tree_external_map", e.target.value)
                  }
                  placeholder='[{"name":"printf","header":"stdio.h","library":"stdio"}]'
                />
                <div className="row">
                  <button
                    type="button"
                    onClick={() => callTreeMapInputRef.current?.click()}
                  >
                    Import
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      downloadText(
                        "call_tree_external_map.json",
                        callTreeExternalMapText,
                        "application/json",
                      )
                    }
                  >
                    Export
                  </button>
                </div>
                <input
                  ref={callTreeMapInputRef}
                  type="file"
                  accept=".json,.txt"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = () => {
                      updateConfig(
                        "call_tree_external_map",
                        String(reader.result || "[]"),
                      );
                    };
                    reader.readAsText(file);
                    e.target.value = "";
                  }}
                />
                <label>
                  HTML 템플릿(옵션, {"{{tree}}"} 또는 {"{{content}}"} 치환)
                </label>
                <textarea
                  rows={6}
                  value={callTreeHtmlTemplateText}
                  onChange={(e) =>
                    updateConfig("call_tree_html_template", e.target.value)
                  }
                  placeholder="<html><body>{{tree}}</body></html>"
                />
                <div className="row">
                  <button
                    type="button"
                    onClick={() => callTreeTemplateInputRef.current?.click()}
                  >
                    Import
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      downloadText(
                        "call_tree_template.html",
                        callTreeHtmlTemplateText,
                        "text/html",
                      )
                    }
                  >
                    Export
                  </button>
                </div>
                <input
                  ref={callTreeTemplateInputRef}
                  type="file"
                  accept=".html,.htm,.txt"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = () => {
                      updateConfig(
                        "call_tree_html_template",
                        String(reader.result || ""),
                      );
                    };
                    reader.readAsText(file);
                    e.target.value = "";
                  }}
                />
              </details>

              <details className="section">
                <summary>
                  <span className="summary-icon">
                    <Icon name="alert" />
                  </span>
                  임계치(대시보드)
                </summary>
                <label>커버리지 경고 기준(%)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={config.coverage_warn_pct ?? 80}
                  onChange={(e) =>
                    updateConfig("coverage_warn_pct", Number(e.target.value))
                  }
                />
                <label>커버리지 실패 기준(%)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={config.coverage_fail_pct ?? 50}
                  onChange={(e) =>
                    updateConfig("coverage_fail_pct", Number(e.target.value))
                  }
                />
                <label>테스트 최소 케이스 수</label>
                <input
                  type="number"
                  min={0}
                  max={100000}
                  value={config.tests_min_count ?? 1}
                  onChange={(e) =>
                    updateConfig("tests_min_count", Number(e.target.value))
                  }
                />
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.require_tests_enabled}
                    onChange={(e) =>
                      updateConfig("require_tests_enabled", e.target.checked)
                    }
                  />{" "}
                  테스트 활성화 필요
                </label>
              </details>

              <details className="section">
                <summary>⚙️ 빌드 & 동적 분석</summary>
                <label>빌드 전략</label>
                <select
                  value={config.build_strategy || "auto"}
                  onChange={(e) =>
                    updateConfig("build_strategy", e.target.value)
                  }
                >
                  {(options.build_strategy_options || ["auto", "manual"]).map(
                    (opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ),
                  )}
                </select>
                <label>빌드 디렉터리(선택)</label>
                <div className="input-row">
                  <input
                    value={config.build_dir || ""}
                    onChange={(e) => updateConfig("build_dir", e.target.value)}
                  />
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("빌드 디렉터리 선택");
                      if (path) updateConfig("build_dir", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
                {(config.build_strategy || "auto") === "auto" && (
                  <>
                    <label>로컬 빌드 환경 미탐지 시</label>
                    <select
                      value={config.build_fallback || "static"}
                      onChange={(e) =>
                        updateConfig("build_fallback", e.target.value)
                      }
                    >
                      {(
                        options.build_fallback_options || ["jenkins", "static"]
                      ).map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </>
                )}
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_build}
                    onChange={(e) => updateConfig("do_build", e.target.checked)}
                  />{" "}
                  CMake Build + CTest 실행
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_asan}
                    onChange={(e) => updateConfig("do_asan", e.target.checked)}
                  />{" "}
                  AddressSanitizer 사용
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_fuzz}
                    onChange={(e) => updateConfig("do_fuzz", e.target.checked)}
                  />{" "}
                  AI Fuzzing 실행
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_qemu}
                    onChange={(e) => updateConfig("do_qemu", e.target.checked)}
                  />{" "}
                  QEMU Smoke Test 실행
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.do_docs}
                    onChange={(e) => updateConfig("do_docs", e.target.checked)}
                  />{" "}
                  Doxygen 문서 생성
                </label>
              </details>

              <details className="section">
                <summary>
                  <span className="summary-icon">
                    <Icon name="target" />
                  </span>
                  타깃 / 컴파일
                </summary>
                <label>MCU 프리셋</label>
                <select
                  value={config.mcu_preset || "(직접입력)"}
                  onChange={(e) => {
                    const val = e.target.value;
                    updateConfig("mcu_preset", val);
                    const presetArch = options.mcu_presets?.[val];
                    if (presetArch) updateConfig("target_arch", presetArch);
                  }}
                >
                  {[
                    "(직접입력)",
                    ...Object.keys(options.mcu_presets || {}),
                  ].map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>타깃 아키텍처</label>
                <input
                  value={config.target_arch || ""}
                  onChange={(e) => updateConfig("target_arch", e.target.value)}
                />
                <label>추가 매크로 (공백/쉼표 구분)</label>
                <input
                  value={config.target_macros || ""}
                  onChange={(e) =>
                    updateConfig("target_macros", e.target.value)
                  }
                />
                <label>추가 include 경로 (쉼표 구분)</label>
                <input
                  value={joinList(config.include_paths)}
                  onChange={(e) =>
                    updateConfig("include_paths", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("include 경로 추가");
                      appendConfigList("include_paths", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("폴더 추가")}
                  </button>
                </div>
                <label>툴체인 프로파일</label>
                <select
                  value={config.toolchain_profile || "(사용 안 함)"}
                  onChange={(e) => {
                    const val = e.target.value;
                    updateConfig("toolchain_profile", val);
                    const prof = options.toolchain_profiles?.[val];
                    if (prof) {
                      updateConfig(
                        "cmake_toolchain_file",
                        prof.cmake_toolchain_file || "",
                      );
                      updateConfig(
                        "cmake_generator",
                        prof.cmake_generator || "",
                      );
                    }
                  }}
                >
                  {[
                    "(사용 안 함)",
                    "(직접 입력)",
                    ...Object.keys(options.toolchain_profiles || {}),
                  ].map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>CMake Toolchain 파일(옵션)</label>
                <div className="input-row">
                  <input
                    value={config.cmake_toolchain_file || ""}
                    onChange={(e) =>
                      updateConfig("cmake_toolchain_file", e.target.value)
                    }
                  />
                  <button
                    onClick={async () => {
                      const path = await pickFile("Toolchain 파일 선택");
                      if (path) updateConfig("cmake_toolchain_file", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
                <label>CMake Generator(옵션)</label>
                <input
                  value={config.cmake_generator || ""}
                  onChange={(e) =>
                    updateConfig("cmake_generator", e.target.value)
                  }
                />
              </details>

              <details className="section span-2">
                <summary>
                  <span className="summary-icon">
                    <Icon name="bot" />
                  </span>
                  AI 에이전트
                </summary>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.enable_agent}
                    onChange={(e) =>
                      updateConfig("enable_agent", e.target.checked)
                    }
                  />{" "}
                  AI 자동 수정 에이전트 사용
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.enable_test_gen}
                    onChange={(e) =>
                      updateConfig("enable_test_gen", e.target.checked)
                    }
                  />{" "}
                  AI 유닛 테스트 자동 생성
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.auto_run_tests}
                    onChange={(e) =>
                      updateConfig("auto_run_tests", e.target.checked)
                    }
                  />{" "}
                  테스트 자동 실행(빌드/CTest)
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.auto_fix_on_fail}
                    onChange={(e) =>
                      updateConfig("auto_fix_on_fail", e.target.checked)
                    }
                  />{" "}
                  빌드/테스트 실패 시 자동 복구
                </label>
                <label>실패 단계별 자동 복구 범위</label>
                <select
                  multiple
                  value={config.auto_fix_on_fail_stages || []}
                  onChange={(e) =>
                    updateConfig(
                      "auto_fix_on_fail_stages",
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                >
                  {(options.auto_fix_scope_options || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>자동 수정 범위</label>
                <select
                  multiple
                  value={config.auto_fix_scope || []}
                  onChange={(e) =>
                    updateConfig(
                      "auto_fix_scope",
                      Array.from(e.target.selectedOptions, (o) => o.value),
                    )
                  }
                >
                  {(options.auto_fix_scope_options || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>최대 수정 라운드</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={config.max_iterations || 3}
                  onChange={(e) =>
                    updateConfig("max_iterations", Number(e.target.value))
                  }
                />
                <label>에이전트 단계 최대 반복</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={config.agent_max_steps || 3}
                  onChange={(e) =>
                    updateConfig("agent_max_steps", Number(e.target.value))
                  }
                />
                <label>에이전트 역할(쉼표 구분)</label>
                <input
                  value={joinList(config.agent_roles)}
                  onChange={(e) =>
                    updateConfig("agent_roles", splitList(e.target.value))
                  }
                />
                <label>에이전트 실행 모드</label>
                <select
                  value={config.agent_run_mode || "auto"}
                  onChange={(e) =>
                    updateConfig("agent_run_mode", e.target.value)
                  }
                >
                  {(options.agent_run_modes || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.agent_review}
                    onChange={(e) =>
                      updateConfig("agent_review", e.target.checked)
                    }
                  />{" "}
                  에이전트 리뷰어 사용
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.agent_rag}
                    onChange={(e) =>
                      updateConfig("agent_rag", e.target.checked)
                    }
                  />{" "}
                  RAG/지식베이스 사용
                </label>
                <label>RAG Top-K</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={config.agent_rag_top_k || 3}
                  onChange={(e) =>
                    updateConfig("agent_rag_top_k", Number(e.target.value))
                  }
                />
                <label>UDS RAG Top-K</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={config.uds_rag_top_k || 3}
                  onChange={(e) =>
                    updateConfig("uds_rag_top_k", Number(e.target.value))
                  }
                />
                <label>UDS RAG 카테고리(쉼표 구분)</label>
                <input
                  value={joinList(config.uds_rag_categories)}
                  onChange={(e) =>
                    updateConfig("uds_rag_categories", splitList(e.target.value))
                  }
                  placeholder="uds, requirements, code, vectorcast"
                />
                <label>패치 모드</label>
                <select
                  value={config.agent_patch_mode || "auto"}
                  onChange={(e) =>
                    updateConfig("agent_patch_mode", e.target.value)
                  }
                >
                  {(options.agent_patch_modes || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
                <label>LLM 설정 파일 경로</label>
                <div className="input-row">
                  <input
                    value={config.oai_config_path || ""}
                    onChange={(e) =>
                      updateConfig("oai_config_path", e.target.value)
                    }
                  />
                  <button
                    onClick={async () => {
                      const path = await pickFile("LLM 설정 파일 선택");
                      if (path) updateConfig("oai_config_path", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("찾기")}
                  </button>
                </div>
                <label>LLM 모델</label>
                <input
                  value={config.llm_model || ""}
                  onChange={(e) => updateConfig("llm_model", e.target.value)}
                />
              </details>

              <details className="section span-2">
                <summary>
                  <span className="summary-icon">
                    <Icon name="book" />
                  </span>
                  RAG 인제스트(외부 지식)
                </summary>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.rag_ingest_enable}
                    onChange={(e) =>
                      updateConfig("rag_ingest_enable", e.target.checked)
                    }
                  />{" "}
                  RAG 인제스트 활성화
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.rag_ingest_on_pipeline}
                    onChange={(e) =>
                      updateConfig("rag_ingest_on_pipeline", e.target.checked)
                    }
                  />{" "}
                  파이프라인 실행 시 자동 인제스트
                </label>
                <label>인제스트 최대 파일 수</label>
                <input
                  type="number"
                  min={10}
                  max={5000}
                  value={config.rag_ingest_max_files ?? 200}
                  onChange={(e) =>
                    updateConfig("rag_ingest_max_files", Number(e.target.value || 200))
                  }
                />
                <label>파일당 최대 청크 수</label>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={config.rag_ingest_max_chunks ?? 12}
                  onChange={(e) =>
                    updateConfig("rag_ingest_max_chunks", Number(e.target.value || 12))
                  }
                />
                <label>청크 크기</label>
                <input
                  type="number"
                  min={200}
                  max={5000}
                  value={config.rag_chunk_size ?? 1200}
                  onChange={(e) =>
                    updateConfig("rag_chunk_size", Number(e.target.value || 1200))
                  }
                />
                <label>청크 오버랩</label>
                <input
                  type="number"
                  min={0}
                  max={2000}
                  value={config.rag_chunk_overlap ?? 200}
                  onChange={(e) =>
                    updateConfig("rag_chunk_overlap", Number(e.target.value || 200))
                  }
                />
                <label>KB 저장소</label>
                <select
                  value={config.kb_storage || "sqlite"}
                  onChange={(e) => updateConfig("kb_storage", e.target.value)}
                >
                  <option value="sqlite">sqlite</option>
                  <option value="pgvector">pgvector</option>
                </select>
                <label>PGVector DSN</label>
                <input
                  value={config.pgvector_dsn || ""}
                  onChange={(e) => updateConfig("pgvector_dsn", e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/dbname"
                />
                <label>PGVector URL</label>
                <input
                  value={config.pgvector_url || ""}
                  onChange={(e) => updateConfig("pgvector_url", e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/dbname"
                />
                <div className="row">
                  <button
                    onClick={() => checkRagStatus && checkRagStatus()}
                    disabled={loading}
                  >
                    상태 확인
                  </button>
                  <button
                    onClick={() => runRagIngest && runRagIngest()}
                    disabled={loading}
                  >
                    인제스트 실행
                  </button>
                  <button
                    onClick={() => switchRagToPgvector && switchRagToPgvector()}
                    disabled={loading || !(config.pgvector_dsn || config.pgvector_url)}
                  >
                    PGVector 전환
                  </button>
                </div>
                {ragStatus ? (
                  <div className="hint">
                    RAG: storage={ragStatus.kb_storage || "-"} · ingest=
                    {String(ragStatus.rag_ingest_enable)} · pgvector=
                    {ragStatus.pgvector_ready ? "ready" : "not-ready"}
                  </div>
                ) : null}
                {ragIngestResult ? (
                  <div className="hint">
                    인제스트 결과: updated={ragIngestResult.updated ?? 0} / skipped=
                    {ragIngestResult.skipped ?? 0}
                  </div>
                ) : null}
                <label>VectorCAST 리포트 경로(쉼표 구분)</label>
                <input
                  value={joinList(config.vc_reports_paths)}
                  onChange={(e) =>
                    updateConfig("vc_reports_paths", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickFile("VectorCAST 리포트 선택");
                      appendConfigList("vc_reports_paths", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("파일 추가")}
                  </button>
                </div>
                <label>UDS 스펙 경로(쉼표 구분)</label>
                <input
                  value={joinList(config.uds_spec_paths)}
                  onChange={(e) =>
                    updateConfig("uds_spec_paths", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickFile("UDS 스펙 파일 선택");
                      appendConfigList("uds_spec_paths", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("파일 추가")}
                  </button>
                </div>
                <label>요구사항 문서 경로(쉼표 구분)</label>
                <input
                  value={joinList(config.req_docs_paths)}
                  onChange={(e) =>
                    updateConfig("req_docs_paths", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickFile("요구사항 문서 선택");
                      appendConfigList("req_docs_paths", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("파일 추가")}
                  </button>
                </div>
                <label>코드베이스 경로(쉼표 구분)</label>
                <input
                  value={joinList(config.codebase_paths)}
                  onChange={(e) =>
                    updateConfig("codebase_paths", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickDirectory("코드베이스 경로 추가");
                      appendConfigList("codebase_paths", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("폴더 추가")}
                  </button>
                </div>
              </details>

              <details className="section span-2">
                <summary>
                  <span className="summary-icon">
                    <Icon name="flask" />
                  </span>
                  도메인 테스트 패널
                </summary>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.enable_domain_tests}
                    onChange={(e) =>
                      updateConfig("enable_domain_tests", e.target.checked)
                    }
                  />{" "}
                  도메인 전용 테스트 패널 실행
                </label>
                <label className="full-row">
                  <input
                    type="checkbox"
                    checked={!!config.domain_tests_auto}
                    onChange={(e) =>
                      updateConfig("domain_tests_auto", e.target.checked)
                    }
                  />{" "}
                  코드 변경 기반 자동 실행
                </label>
                <label>타깃 파일(상대 경로, 쉼표 구분)</label>
                <input
                  value={joinList(config.domain_targets)}
                  onChange={(e) =>
                    updateConfig("domain_targets", splitList(e.target.value))
                  }
                />
                <div className="row">
                  <button
                    onClick={async () => {
                      const path = await pickFile("도메인 테스트 파일 선택");
                      appendConfigList("domain_targets", path);
                    }}
                    disabled={pickerBusy}
                  >
                    {busyText("파일 추가")}
                  </button>
                </div>
              </details>
            </div>
          </div>
        )}

        <div className="sidebar-group">
          <div className="sidebar-group-title">Jenkins 연결</div>
          <details className="section">
            <summary>
              <span className="summary-icon">
                <Icon name="link" />
              </span>
              Jenkins 서버 설정
            </summary>
            <label>Jenkins URL</label>
            <input
              value={jenkinsBaseUrl || ""}
              onChange={(e) => setJenkinsBaseUrl?.(e.target.value)}
              placeholder="http://jenkins.example.com:8080"
            />
            <label>사용자 이름</label>
            <input
              value={jenkinsUsername || ""}
              onChange={(e) => setJenkinsUsername?.(e.target.value)}
              placeholder="admin"
            />
            <label>API Token</label>
            <input
              type="password"
              value={jenkinsToken || ""}
              onChange={(e) => setJenkinsToken?.(e.target.value)}
              placeholder="Jenkins API Token"
            />
            <label className="full-row">
              <input
                type="checkbox"
                checked={jenkinsVerifyTls !== false}
                onChange={(e) => setJenkinsVerifyTls?.(e.target.checked)}
              />{" "}
              TLS 인증서 검증
            </label>
            <label>빌드 선택 기준</label>
            <select
              value={jenkinsBuildSelector || "latest"}
              onChange={(e) => setJenkinsBuildSelector?.(e.target.value)}
            >
              <option value="latest">최신 빌드</option>
              <option value="lastSuccessfulBuild">마지막 성공 빌드</option>
              <option value="lastCompletedBuild">마지막 완료 빌드</option>
            </select>
            <label>캐시 루트</label>
            <div className="input-row">
              <input
                value={jenkinsCacheRoot || ""}
                onChange={(e) => setJenkinsCacheRoot?.(e.target.value)}
                placeholder="Jenkins 캐시 디렉토리"
              />
              <button
                onClick={async () => {
                  const path = await pickDirectory("Jenkins 캐시 폴더 선택");
                  if (path) setJenkinsCacheRoot?.(path);
                }}
                disabled={pickerBusy}
              >
                {busyText("찾기")}
              </button>
            </div>
            <label>Jenkins 서버 루트</label>
            <div className="input-row">
              <input
                value={jenkinsServerRoot || ""}
                onChange={(e) => setJenkinsServerRoot?.(e.target.value)}
                placeholder="C:\ProgramData\Jenkins\.jenkins"
              />
              <button
                onClick={async () => {
                  const path = await pickDirectory("Jenkins 서버 루트 선택");
                  if (path) setJenkinsServerRoot?.(path);
                }}
                disabled={pickerBusy}
              >
                {busyText("찾기")}
              </button>
            </div>
            <label>서버 상대 경로</label>
            <input
              value={jenkinsServerRelPath || ""}
              onChange={(e) => setJenkinsServerRelPath?.(e.target.value)}
              placeholder="workspace"
            />
          </details>
        </div>

        {mode === "local" && (
          <div className="sidebar-group">
            <div className="sidebar-group-title">실행 & 백업</div>
            <div className="section">
              <button onClick={exportSession} disabled={!sessionId}>
                세션 백업
              </button>
            </div>
            <details className="section">
              <summary>
                <span className="summary-icon">
                  <Icon name="archive" />
                </span>
                세션 백업 관리
              </summary>
              <div className="row">
                <button onClick={refreshExports}>백업 목록 새로고침</button>
                <button onClick={() => cleanupExports(30)}>30일 정리</button>
              </div>
              <div className="export-list">
                {exports.map((ex) => (
                  <div key={ex.file} className="export-row">
                    <div>
                      <div className="export-file">{ex.file}</div>
                      <div className="export-meta">
                        {ex.size_mb}MB · {ex.mtime}
                      </div>
                    </div>
                    <div className="row">
                      <a
                        className="btn-link"
                        href={ex.download_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        다운로드
                      </a>
                      <button
                        className="btn-outline"
                        onClick={() => restoreExport(ex.file)}
                      >
                        바로 적용
                      </button>
                      <button
                        className="btn-outline"
                        onClick={() => deleteExport(ex.file)}
                      >
                        삭제
                      </button>
                    </div>
                  </div>
                ))}
                {exports.length === 0 && <div className="empty">백업 없음</div>}
              </div>
            </details>
          </div>
        )}

        {mode === "local" && config && (
          <details className="section">
            <summary>현재 설정(JSON)</summary>
            <pre className="json">{JSON.stringify(config, null, 2)}</pre>
          </details>
        )}
        {message ? <div className="message">{message}</div> : null}
      </div>
    );
  },
);

SettingsPanel.displayName = "SettingsPanel";

export default SettingsPanel;
