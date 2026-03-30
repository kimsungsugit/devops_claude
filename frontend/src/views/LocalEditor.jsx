import { useEffect, useMemo, useRef, useState } from 'react'
import Editor from 'react-simple-code-editor'
import Prism from 'prismjs'
import prettier from 'prettier/standalone'
import prettierBabel from 'prettier/parser-babel'
import prettierTypescript from 'prettier/parser-typescript'
import prettierPostcss from 'prettier/parser-postcss'
import prettierMarkdown from 'prettier/parser-markdown'
import prettierYaml from 'prettier/parser-yaml'
import prettierHtml from 'prettier/parser-html'
import 'prismjs/components/prism-clike'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-yaml'
import Icon from '../components/Icon'
import SimpleMarkdown from '../components/SimpleMarkdown'
import { normalizePct, formatPct, toneForStatus as statusTone } from '../utils/ui'

const EXT_ICON_MAP = {
  c: 'code', h: 'code', cpp: 'code', cxx: 'code', cc: 'code', hpp: 'code',
  js: 'code', jsx: 'code', ts: 'code', tsx: 'code', py: 'code',
  json: 'settings', yaml: 'settings', yml: 'settings', xml: 'settings',
  md: 'file', txt: 'file', log: 'file', csv: 'file',
}
const fileExtIcon = (p) => {
  if (!p) return 'file'
  const ext = String(p).split('.').pop()?.toLowerCase()
  return EXT_ICON_MAP[ext] || 'file'
}

const LocalEditor = ({
  editorPath,
  setEditorPath,
  onPickFile,
  onOpenFile,
  mode,
  jenkinsSourceRoot,
  explorerRoot,
  setExplorerRoot,
  explorerMap,
  expandedPaths,
  explorerLoading,
  explorerRootOptions,
  message,
  loadExplorerRoot,
  toggleExplorerPath,
  searchQuery,
  setSearchQuery,
  searchResults,
  runSearch,
  replaceQuery,
  setReplaceQuery,
  replaceValue,
  setReplaceValue,
  runReplaceText,
  gitStatusInfo,
  gitDiffRows,
  gitDiffStagedRows,
  gitLog,
  gitBranches,
  gitBranchName,
  setGitBranchName,
  gitCommitMessage,
  setGitCommitMessage,
  gitPathInput,
  setGitPathInput,
  loadGitStatus,
  loadGitDiff,
  loadGitLog,
  loadGitBranches,
  runGitStage,
  runGitCommit,
  runGitCheckout,
  editorRead,
  editorWrite,
  editorStartLine,
  editorEndLine,
  setEditorStartLine,
  setEditorEndLine,
  editorReplace,
  editorText,
  setEditorText,
  summary,
  status,
  sessionId,
  focusRequest,
  logFiles,
  logContent,
  selectedLogPath,
  setSelectedLogPath,
  loadLogList,
  readLog,
  refreshSession,
  onGoWorkflow,
  onRequestAiGuide,
  onFormatCCode,
  findings,
  reportDir,
  onOpenEditorFile,
  onSendToChat,
}) => {
  const changedSet = new Set([
    ...(gitStatusInfo?.staged || []),
    ...(gitStatusInfo?.unstaged || []),
    ...(gitStatusInfo?.untracked || []),
  ])
  const statusByPath = gitStatusInfo?.byPath || {}
  const [treeFilter, setTreeFilter] = useState('all')
  const [aiPrompt, setAiPrompt] = useState('')
  const [aiAnswer, setAiAnswer] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [formatNotice, setFormatNotice] = useState('')
  const [currentLine, setCurrentLine] = useState(1)
  const [tabSize, setTabSize] = useState(() => {
    if (typeof window === 'undefined') return 2
    const saved = Number(window.localStorage.getItem('editor_tab_size') || 2)
    return Number.isFinite(saved) ? saved : 2
  })
  const [indentGuideMode, setIndentGuideMode] = useState(() => {
    if (typeof window === 'undefined') return 'tab'
    return window.localStorage.getItem('editor_indent_mode') || 'tab'
  })
  const [indentGuideStep, setIndentGuideStep] = useState(() => {
    if (typeof window === 'undefined') return 2
    const saved = Number(window.localStorage.getItem('editor_indent_step') || 2)
    return Number.isFinite(saved) ? saved : 2
  })
  const [indentGuideColor, setIndentGuideColor] = useState(() => {
    if (typeof window === 'undefined') return '#94a3b8'
    return window.localStorage.getItem('editor_indent_color') || '#94a3b8'
  })
  const [lineHighlightColor, setLineHighlightColor] = useState(() => {
    if (typeof window === 'undefined') return '#93c5fd'
    return window.localStorage.getItem('editor_line_highlight') || '#93c5fd'
  })
  const [isCodeFocus, setIsCodeFocus] = useState(false)
  const [lineMenu, setLineMenu] = useState(null)
  const [rangeStart, setRangeStart] = useState(null)
  const [rangeEnd, setRangeEnd] = useState(null)
  const [issueFilter, setIssueFilter] = useState(() => {
    if (typeof window === 'undefined') return 'all'
    return window.localStorage.getItem('editor_issue_filter') || 'all'
  })
  const [issueQuery, setIssueQuery] = useState(() => {
    if (typeof window === 'undefined') return ''
    return window.localStorage.getItem('editor_issue_query') || ''
  })
  const [issueLimit, setIssueLimit] = useState(() => {
    if (typeof window === 'undefined') return 50
    const saved = Number(window.localStorage.getItem('editor_issue_limit') || 50)
    return Number.isFinite(saved) ? saved : 50
  })
  const [issueSort, setIssueSort] = useState(() => {
    if (typeof window === 'undefined') return 'severity'
    return window.localStorage.getItem('editor_issue_sort') || 'severity'
  })
  const [issueSortDir, setIssueSortDir] = useState(() => {
    if (typeof window === 'undefined') return 'asc'
    return window.localStorage.getItem('editor_issue_sort_dir') || 'asc'
  })
  const [openTabs, setOpenTabs] = useState([])
  const [activeTabId, setActiveTabId] = useState(null)
  const tabCacheRef = useRef(new Map())
  const [hoveredIssueLine, setHoveredIssueLine] = useState(null)
  const [issueFixLoading, setIssueFixLoading] = useState(false)
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false)
  const [inFileSearchOpen, setInFileSearchOpen] = useState(false)
  const [inFileSearchTerm, setInFileSearchTerm] = useState('')
  const [inFileSearchRegex, setInFileSearchRegex] = useState(false)
  const [inFileSearchCase, setInFileSearchCase] = useState(false)
  const [inFileMatchIdx, setInFileMatchIdx] = useState(0)
  const [explorerFilter, setExplorerFilter] = useState('')
  const [recentFiles, setRecentFiles] = useState(() => {
    if (typeof window === 'undefined') return []
    try { return JSON.parse(window.localStorage.getItem('editor_recent_files') || '[]') } catch { return [] }
  })
  const [gotoLineOpen, setGotoLineOpen] = useState(false)
  const [gotoLineInput, setGotoLineInput] = useState('')
  const [leftWidth, setLeftWidth] = useState(() => {
    if (typeof window === 'undefined') return 260
    return Number(window.localStorage.getItem('editor_left_w')) || 260
  })
  const [rightWidth, setRightWidth] = useState(() => {
    if (typeof window === 'undefined') return 320
    return Number(window.localStorage.getItem('editor_right_w')) || 320
  })
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const dragRef = useRef(null)
  const inFileSearchRef = useRef(null)
  const codeWrapRef = useRef(null)
  const lineRef = useRef(null)
  const lineHeightPx = 18
  const editorPadding = 12

  const classifySeverity = (item) => {
    const raw = String(
      item?.severity || item?.level || item?.priority || item?.kind || item?.type || '',
    ).toLowerCase()
    if (raw.includes('error') || raw.includes('critical')) return 'error'
    if (raw.includes('warn')) return 'warning'
    return 'info'
  }

  const normalizeIssue = (item, idx) => {
    const path = item?.path || item?.file || item?.filename || item?.location?.path || ''
    const line = item?.line || item?.line_number || item?.location?.line || null
    const message = item?.message || item?.text || item?.description || item?.rule_id || item?.title || '-'
    const tool = item?.tool || item?.source || ''
    return {
      key: item?.id || `${path}:${line || 0}:${idx}`,
      path,
      line,
      message,
      tool,
      severity: classifySeverity(item),
    }
  }

  const issueList = (findings || []).map(normalizeIssue)
  const issueCounts = issueList.reduce(
    (acc, item) => {
      acc[item.severity] += 1
      return acc
    },
    { error: 0, warning: 0, info: 0 },
  )
  const currentFileIssues = useMemo(() => {
    const p = String(editorPath || '').trim()
    if (!p) return []
    return issueList.filter(item => {
      const ip = String(item.path || '').trim()
      return ip === p || ip.endsWith('/' + p) || p.endsWith('/' + ip)
    })
  }, [issueList, editorPath])

  const issuesByLine = useMemo(() => {
    const map = new Map()
    currentFileIssues.forEach(issue => {
      const ln = Number(issue.line) || 0
      if (ln <= 0) return
      if (!map.has(ln)) map.set(ln, [])
      map.get(ln).push(issue)
    })
    return map
  }, [currentFileIssues])

  const inFileMatches = useMemo(() => {
    if (!inFileSearchTerm || !editorText) return []
    const lines = editorText.split(/\r?\n/)
    const matches = []
    try {
      const flags = inFileSearchCase ? 'g' : 'gi'
      const pat = inFileSearchRegex
        ? new RegExp(inFileSearchTerm, flags)
        : new RegExp(inFileSearchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), flags)
      lines.forEach((line, idx) => {
        if (pat.test(line)) { matches.push({ line: idx + 1, text: line.trim() }); pat.lastIndex = 0 }
      })
    } catch { /* invalid regex */ }
    return matches
  }, [editorText, inFileSearchTerm, inFileSearchRegex, inFileSearchCase])

  const tests = summary?.tests || {}
  const coverage = summary?.coverage || {}
  const qemu = summary?.qemu || {}
  const testsOk = tests.ok
  const testsTone = testsOk === false ? 'failed' : testsOk === true ? 'success' : 'info'
  const coverageLine = normalizePct(coverage.line_rate_pct ?? coverage.line_rate)
  const coverageBranch = normalizePct(coverage.branch_rate_pct ?? coverage.branch_rate)
  const coverageThreshold = normalizePct(coverage.threshold)
  const coverageTone = coverage?.ok === false
    ? 'failed'
    : coverageLine != null && coverageThreshold != null && coverageLine < coverageThreshold
      ? 'warning'
      : coverage?.enabled
        ? 'success'
        : 'info'
  const coverageBarClass = coverageTone === 'failed'
    ? 'bar-fill-error'
    : coverageTone === 'warning'
      ? 'bar-fill-warn'
      : ''
  const qemuTone = qemu.ok === false ? 'failed' : qemu.ok === true ? 'success' : 'info'

  const flattenLogFiles = () => {
    if (!logFiles || typeof logFiles !== 'object') return []
    return Object.entries(logFiles).flatMap(([key, values]) => {
      if (!Array.isArray(values)) return []
      return values.map((path) => ({ group: key, path }))
    })
  }

  const resolveLogPath = (path) => {
    if (!path) return ''
    const raw = String(path)
    const isAbs = /^[a-zA-Z]:[\\/]/.test(raw) || raw.startsWith('/')
    if (isAbs) return raw
    if (reportDir) return `${reportDir.replace(/[\\/]+$/, '')}\\${raw}`.replace(/\\/g, '\\')
    return raw
  }
  const filteredIssues = issueList.filter((item) => {
    if (issueFilter !== 'all' && item.severity !== issueFilter) return false
    if (!issueQuery.trim()) return true
    const q = issueQuery.trim().toLowerCase()
    return (
      String(item.message || '').toLowerCase().includes(q)
      || String(item.path || '').toLowerCase().includes(q)
      || String(item.tool || '').toLowerCase().includes(q)
    )
  })
  const severityOrder = { error: 0, warning: 1, info: 2 }
  const sortDirFactor = issueSortDir === 'desc' ? -1 : 1
  const sortedIssues = [...filteredIssues].sort((a, b) => {
    if (issueSort === 'severity') {
      return (
        (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9)
      ) * sortDirFactor
    }
    if (issueSort === 'path') {
      return String(a.path || '').localeCompare(String(b.path || '')) * sortDirFactor
    }
    if (issueSort === 'tool') {
      return String(a.tool || '').localeCompare(String(b.tool || '')) * sortDirFactor
    }
    return 0
  })

  const languageId = useMemo(() => {
    const path = String(editorPath || '').toLowerCase()
    if (path.endsWith('.ts') || path.endsWith('.tsx')) return 'typescript'
    if (path.endsWith('.jsx')) return 'jsx'
    if (path.endsWith('.js')) return 'javascript'
    if (path.endsWith('.json')) return 'json'
    if (path.endsWith('.md')) return 'markdown'
    if (path.endsWith('.py')) return 'python'
    if (path.endsWith('.yml') || path.endsWith('.yaml')) return 'yaml'
    if (path.endsWith('.sh') || path.endsWith('.bash')) return 'bash'
    if (path.endsWith('.c')) return 'c'
    if (path.endsWith('.cpp') || path.endsWith('.cxx') || path.endsWith('.cc')) return 'cpp'
    if (path.endsWith('.h') || path.endsWith('.hpp') || path.endsWith('.hh')) return 'cpp'
    return 'plain'
  }, [editorPath])

  const highlightCode = (code) => {
    const lang = Prism.languages[languageId] || Prism.languages.plain || Prism.languages.markup
    return Prism.highlight(code, lang, languageId)
  }

  const lineCount = useMemo(() => {
    if (!editorText) return 1
    return editorText.split(/\r?\n/).length || 1
  }, [editorText])

  const updateCurrentLine = (event) => {
    const target = event?.target
    if (!target || typeof target.selectionStart !== 'number') return
    const before = String(editorText || '').slice(0, target.selectionStart)
    const line = before.split(/\r?\n/).length || 1
    setCurrentLine(line)
  }

  const syncScroll = (event) => {
    if (!lineRef.current) return
    lineRef.current.scrollTop = event.target.scrollTop
  }

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_tab_size', String(tabSize))
  }, [tabSize])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_indent_mode', indentGuideMode)
  }, [indentGuideMode])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_indent_step', String(indentGuideStep))
  }, [indentGuideStep])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_indent_color', indentGuideColor)
  }, [indentGuideColor])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_line_highlight', lineHighlightColor)
  }, [lineHighlightColor])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_issue_filter', issueFilter)
  }, [issueFilter])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_issue_query', issueQuery)
  }, [issueQuery])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_issue_limit', String(issueLimit))
  }, [issueLimit])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_issue_sort', issueSort)
  }, [issueSort])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('editor_issue_sort_dir', issueSortDir)
  }, [issueSortDir])

  const formatEditorText = async () => {
    if (!editorText) return
    if (languageId === 'c' || languageId === 'cpp') {
      if (!onFormatCCode) {
        setFormatNotice('C/C++ 포맷터가 연결되지 않았습니다.')
        return
      }
      setFormatNotice('')
      const res = await onFormatCCode({
        text: editorText,
        filename: editorPath || (languageId === 'c' ? 'temp.c' : 'temp.cpp'),
      })
      if (res?.ok) {
        setEditorText(res.text || '')
        setFormatNotice('자동 포맷 완료')
      } else {
        const msg = res?.error || 'C/C++ 포맷 실패'
        setFormatNotice(msg)
      }
      return
    }
    const parserMap = {
      javascript: { parser: 'babel', plugins: [prettierBabel] },
      jsx: { parser: 'babel', plugins: [prettierBabel] },
      typescript: { parser: 'typescript', plugins: [prettierTypescript] },
      json: { parser: 'json', plugins: [prettierBabel] },
      markdown: { parser: 'markdown', plugins: [prettierMarkdown] },
      yaml: { parser: 'yaml', plugins: [prettierYaml] },
      css: { parser: 'css', plugins: [prettierPostcss] },
      html: { parser: 'html', plugins: [prettierHtml] },
    }
    const key = languageId
    const cfg = parserMap[key]
    if (!cfg) {
      setFormatNotice('현재 확장자는 자동 포맷을 지원하지 않습니다.')
      return
    }
    try {
      const formatted = prettier.format(editorText, {
        parser: cfg.parser,
        plugins: cfg.plugins,
        printWidth: 100,
        tabWidth: 2,
        semi: true,
        singleQuote: true,
        trailingComma: 'all',
      })
      setEditorText(formatted)
      setFormatNotice('자동 포맷 완료')
    } catch (e) {
      setFormatNotice(`포맷 실패: ${e.message}`)
    }
  }

  const aiPreset = {
    changeGuide: '이 파일 기준으로 변경 가이드(수정 단계/주의사항/체크리스트)를 정리해줘.',
    staticMock: '정적 분석 관점에서 문제점 가설과 확인 체크리스트를 만들어줘.',
    unitMock: '유닛 테스트 시나리오(모의 테스트)를 목록으로 만들어줘.',
    codeReview: '이 코드의 코드 리뷰를 해줘. 버그 가능성, 성능, 가독성을 평가해줘.',
    refactor: '이 코드를 리팩토링 방안을 제시해줘. 코드 블록으로 개선 코드를 보여줘.',
    fixIssue: (issue) => `파일 ${issue.path} 라인 ${issue.line}에서 발견된 이슈를 수정해줘.\n이슈: ${issue.message}\n심각도: ${issue.severity}\n\n수정된 코드를 코드 블록으로 보여줘.`,
  }

  const addRecentFile = (path) => {
    if (!path) return
    setRecentFiles(prev => {
      const next = [path, ...prev.filter(p => p !== path)].slice(0, 10)
      try { window.localStorage.setItem('editor_recent_files', JSON.stringify(next)) } catch { /* noop */ }
      return next
    })
  }

  useEffect(() => {
    if (!editorPath) return
    addRecentFile(editorPath)
    const existing = openTabs.find(t => t.path === editorPath)
    if (!existing) {
      const newId = `tab-${Date.now()}`
      setOpenTabs(prev => [...prev, { id: newId, path: editorPath }])
      setActiveTabId(newId)
    } else if (existing.id !== activeTabId) {
      setActiveTabId(existing.id)
    }
  }, [editorPath])

  const switchTab = (tabId) => {
    if (tabId === activeTabId) return
    if (activeTabId && editorPath) {
      tabCacheRef.current.set(editorPath, { text: editorText, line: currentLine })
    }
    const tab = openTabs.find(t => t.id === tabId)
    if (!tab) return
    setActiveTabId(tabId)
    setEditorPath(tab.path)
    const cached = tabCacheRef.current.get(tab.path)
    if (cached) {
      setEditorText(cached.text)
      if (cached.line) setTimeout(() => jumpToLine(cached.line), 0)
    } else {
      setTimeout(() => editorRead(), 0)
    }
  }

  const closeTab = (tabId, e) => {
    if (e) e.stopPropagation()
    const idx = openTabs.findIndex(t => t.id === tabId)
    if (idx < 0) return
    const tab = openTabs[idx]
    tabCacheRef.current.delete(tab.path)
    const newTabs = openTabs.filter(t => t.id !== tabId)
    setOpenTabs(newTabs)
    if (tabId === activeTabId) {
      if (newTabs.length > 0) {
        const nextIdx = Math.min(idx, newTabs.length - 1)
        const next = newTabs[nextIdx]
        setActiveTabId(next.id)
        setEditorPath(next.path)
        const cached = tabCacheRef.current.get(next.path)
        if (cached) setEditorText(cached.text)
        else setTimeout(() => editorRead(), 0)
      } else {
        setActiveTabId(null)
        setEditorPath('')
        setEditorText('')
      }
    }
  }

  const requestAiFix = async (issue) => {
    if (!onRequestAiGuide || !issue) return
    setIssueFixLoading(true)
    const prompt = aiPreset.fixIssue(issue)
    setAiPrompt(prompt)
    try {
      const answer = await onRequestAiGuide({
        question: prompt,
        filePath: editorPath,
        startLine: issue.line ? Math.max(1, Number(issue.line) - 3) : editorStartLine,
        endLine: issue.line ? Number(issue.line) + 5 : editorEndLine,
        excerpt: issue.line ? getLineText(Number(issue.line)) : editorExcerpt,
      })
      setAiAnswer(answer || '응답이 비어 있습니다.')
    } catch (e) {
      setAiAnswer(`오류: ${e.message}`)
    } finally {
      setIssueFixLoading(false)
    }
  }

  const insertCodeAtCursor = (code) => {
    if (!code) return
    const textarea = codeWrapRef.current?.querySelector('textarea')
    if (!textarea) { setEditorText(prev => prev + '\n' + code); return }
    const pos = textarea.selectionStart || 0
    const before = editorText.slice(0, pos)
    const after = editorText.slice(pos)
    setEditorText(before + code + after)
  }

  const handleGotoLine = () => {
    const line = Number(gotoLineInput)
    if (Number.isFinite(line) && line > 0) jumpToLine(line)
    setGotoLineOpen(false)
    setGotoLineInput('')
  }

  const cycleInFileMatch = (delta) => {
    if (inFileMatches.length === 0) return
    const next = (inFileMatchIdx + delta + inFileMatches.length) % inFileMatches.length
    setInFileMatchIdx(next)
    jumpToLine(inFileMatches[next].line)
  }

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); if (editorPath) editorWrite() }
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') { e.preventDefault(); setInFileSearchOpen(v => !v); setTimeout(() => inFileSearchRef.current?.focus(), 50) }
      if ((e.ctrlKey || e.metaKey) && e.key === 'g') { e.preventDefault(); setGotoLineOpen(v => !v) }
      if (e.key === 'Escape') { setIsCodeFocus(false); setShortcutHelpOpen(false); setInFileSearchOpen(false); setGotoLineOpen(false) }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === '?') { e.preventDefault(); setShortcutHelpOpen(v => !v) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [editorPath])

  const startDrag = (side) => (e) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = side === 'left' ? leftWidth : rightWidth
    dragRef.current = { side, startX, startW }
    const onMove = (ev) => {
      if (!dragRef.current) return
      const delta = side === 'left' ? ev.clientX - startX : startX - ev.clientX
      const next = Math.max(140, Math.min(600, startW + delta))
      if (side === 'left') setLeftWidth(next)
      else setRightWidth(next)
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      if (side === 'left') window.localStorage.setItem('editor_left_w', String(leftWidth))
      else window.localStorage.setItem('editor_right_w', String(rightWidth))
      dragRef.current = null
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const editorExcerpt = useMemo(() => {
    if (!editorText) return ''
    const lines = editorText.split(/\r?\n/)
    const start = Math.max(1, Number(editorStartLine || 1))
    const end = Math.max(start, Number(editorEndLine || start))
    const slice = lines.slice(start - 1, end)
    if (!slice.length) return ''
    const maxLines = 80
    if (slice.length > maxLines) {
      return [...slice.slice(0, maxLines), '...[truncated]...'].join('\n')
    }
    return slice.join('\n')
  }, [editorText, editorStartLine, editorEndLine])

  const handleAiGuide = async () => {
    if (!onRequestAiGuide || !aiPrompt.trim()) return
    setAiLoading(true)
    setAiAnswer('')
    try {
      const answer = await onRequestAiGuide({
        question: aiPrompt.trim(),
        filePath: editorPath,
        startLine: editorStartLine,
        endLine: editorEndLine,
        excerpt: editorExcerpt,
      })
      setAiAnswer(answer || '응답이 비어 있습니다.')
    } catch (e) {
      setAiAnswer(`오류: ${e.message}`)
    } finally {
      setAiLoading(false)
    }
  }

  const getLineText = (lineNumber) => {
    const lines = String(editorText || '').split(/\r?\n/)
    return lines[lineNumber - 1] ?? ''
  }

  const setLineRange = (lineNumber) => {
    setEditorStartLine(lineNumber)
    setEditorEndLine(lineNumber)
  }

  const jumpToLine = (lineNumber) => {
    const lines = String(editorText || '').split(/\r?\n/)
    const clamped = Math.min(Math.max(1, lineNumber), lines.length || 1)
    let offset = 0
    for (let i = 0; i < clamped - 1; i += 1) {
      offset += lines[i].length + 1
    }
    const textarea = codeWrapRef.current?.querySelector('textarea')
    if (!textarea) return
    textarea.focus()
    textarea.setSelectionRange(offset, offset)
    setCurrentLine(clamped)
    setLineRange(clamped)
  }

  useEffect(() => {
    if (!focusRequest?.path || !editorText) return
    if (focusRequest.path !== editorPath) return
    let line = Number(focusRequest.line || 0)
    if ((!Number.isFinite(line) || line <= 0) && focusRequest.query) {
      const q = String(focusRequest.query || '').trim().toLowerCase()
      if (q) {
        const lines = String(editorText || '').split(/\r?\n/)
        const idx = lines.findIndex((text) => String(text || '').toLowerCase().includes(q))
        if (idx >= 0) line = idx + 1
      }
    }
    if (!Number.isFinite(line) || line <= 0) return
    setIsCodeFocus(true)
    setTimeout(() => {
      jumpToLine(line)
    }, 0)
  }, [editorPath, editorText, focusRequest])

  const handleLineContextMenu = (event, lineNumber) => {
    event.preventDefault()
    const rect = event.currentTarget.getBoundingClientRect()
    setLineMenu({
      line: lineNumber,
      x: rect.right + 6,
      y: rect.top,
    })
  }

  const closeLineMenu = () => setLineMenu(null)

  const copyText = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch (e) {
      setFormatNotice('복사 실패')
    }
  }

  const isPathChanged = (path) => {
    if (changedSet.has(path)) return true
    for (const changed of changedSet) {
      if (changed.startsWith(path + '/')) return true
    }
    return false
  }

  const issueCountByPath = useMemo(() => {
    const map = {}
    issueList.forEach(item => {
      const p = String(item.path || '').trim()
      if (p) map[p] = (map[p] || 0) + 1
    })
    return map
  }, [issueList])

  const renderTree = (path, depth = 0) => {
    const entries = explorerMap?.[path] || []
    if (!entries.length) return null
    return entries.map((entry) => {
      const isExpanded = expandedPaths.includes(entry.path)
      const isChanged = isPathChanged(entry.path)
      if (treeFilter === 'changed' && !isChanged) return null
      if (explorerFilter) {
        const q = explorerFilter.toLowerCase()
        const match = String(entry.path).toLowerCase().includes(q)
        if (!match && !entry.is_dir) return null
      }
      const status = statusByPath[entry.path] || (isChanged ? 'modified' : '')
      const indent = { paddingLeft: `${depth * 14}px` }
      const ic = issueCountByPath[entry.path] || 0
      return (
        <div key={entry.path}>
          <button
            className={`list-item tree-item${isChanged ? ' tree-changed' : ''}`}
            style={indent}
            onClick={() => {
              if (entry.is_dir) toggleExplorerPath(entry.path)
              else onOpenFile(entry.path)
            }}
          >
            <span className="list-icon">
              {entry.is_dir ? <Icon name={isExpanded ? 'folder-open' : 'folder'} /> : <Icon name={fileExtIcon(entry.path)} />}
            </span>
            <span className="tree-name">{entry.path.split('/').pop() || entry.path}</span>
            {ic > 0 ? <span className="tree-issue-badge">{ic}</span> : null}
            {status ? <span className={`status-badge status-${status}`} /> : null}
          </button>
          {entry.is_dir && isExpanded ? renderTree(entry.path, depth + 1) : null}
        </div>
      )
    })
  }

  return (
    <div className={`view-root ${isCodeFocus ? 'editor-focus' : ''}`}>
      <div className="tri-split">
        <section className={`tri-panel tri-left${leftCollapsed ? ' panel-collapsed' : ''}`} style={leftCollapsed ? { width: 32 } : { width: leftWidth }}>
          {leftCollapsed ? (
            <button className="panel-expand-btn" onClick={() => setLeftCollapsed(false)} title="좌측 패널 펼치기">◀</button>
          ) : (
            <>
          <div className="panel-collapse-bar">
            <button className="panel-collapse-btn" onClick={() => setLeftCollapsed(true)} title="접기">▶</button>
          </div>
          <div className="help-box">
            <h4>에디터 사용 방법</h4>
            <ul>
              <li>좌측 파일 탐색기에서 경로를 불러오고 파일을 선택합니다.</li>
              <li>이슈 목록과 테스트 연결은 필요할 때 펼쳐 확인합니다.</li>
              <li>검색/치환과 Git은 오른쪽 패널에 정리됩니다.</li>
            </ul>
          </div>
          <div className="panel">
            <h4>파일 탐색기</h4>
            {mode === 'jenkins' && jenkinsSourceRoot ? (
              <div className="hint">소스 루트: {jenkinsSourceRoot}</div>
            ) : null}
            {editorPath ? (
              <div className="breadcrumb">
                {editorPath.split(/[\\/]/).map((seg, i, arr) => (
                  <span key={i} className="breadcrumb-seg">{i < arr.length - 1 ? <>{seg}<span className="breadcrumb-sep">/</span></> : <strong>{seg}</strong>}</span>
                ))}
              </div>
            ) : null}
            <div className="row">
              <button onClick={() => setTreeFilter('all')} className={treeFilter === 'all' ? 'active' : ''}>전체</button>
              <button onClick={() => setTreeFilter('changed')} className={treeFilter === 'changed' ? 'active' : ''}>변경</button>
            </div>
            <div className="input-row">
              {mode === 'jenkins' ? (
                <select value={explorerRoot} onChange={(e) => setExplorerRoot(e.target.value)}>
                  {(explorerRootOptions || ['.']).map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input value={explorerRoot} onChange={(e) => setExplorerRoot(e.target.value)} placeholder="상대 경로" />
              )}
              <button
                onClick={() => loadExplorerRoot(mode === 'jenkins' ? jenkinsSourceRoot : undefined, '.')}
                disabled={explorerLoading}
              >
                {explorerLoading ? '불러오는 중...' : '불러오기'}
              </button>
            </div>
            <input
              className="explorer-filter-input"
              value={explorerFilter}
              onChange={(e) => setExplorerFilter(e.target.value)}
              placeholder="파일명 검색..."
            />
            {message ? <div className="hint">{message}</div> : null}
            <div className="list tree-list">
              {renderTree(explorerRoot)}
              {(explorerMap?.[explorerRoot] || []).length === 0 && <div className="empty">항목 없음</div>}
            </div>
            {recentFiles.length > 0 ? (
              <details className="recent-files-panel">
                <summary className="hint">최근 파일 ({recentFiles.length})</summary>
                <div className="list recent-list">
                  {recentFiles.map(p => (
                    <button key={p} className="list-item" onClick={() => onOpenFile(p)}>
                      <span className="list-icon"><Icon name={fileExtIcon(p)} /></span>
                      <span className="list-text">{p.split(/[\\/]/).pop()}</span>
                      <span className="list-snippet">{p}</span>
                    </button>
                  ))}
                </div>
              </details>
            ) : null}
          </div>
          <details className="panel panel-collapsible" open>
            <summary>이슈 목록</summary>
            <div className="panel-body">
              <div className="row">
                <span className="hint">Error {issueCounts.error}</span>
                <span className="hint">Warn {issueCounts.warning}</span>
                <span className="hint">Info {issueCounts.info}</span>
              </div>
              <div className="row">
                <select value={issueFilter} onChange={(e) => setIssueFilter(e.target.value)}>
                  <option value="all">전체</option>
                  <option value="error">에러만</option>
                  <option value="warning">경고만</option>
                  <option value="info">정보만</option>
                </select>
                <input
                  placeholder="이슈 메시지 검색"
                  value={issueQuery}
                  onChange={(e) => setIssueQuery(e.target.value)}
                />
                <select value={issueLimit} onChange={(e) => setIssueLimit(Number(e.target.value))}>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
                <select value={issueSort} onChange={(e) => setIssueSort(e.target.value)}>
                  <option value="severity">심각도</option>
                  <option value="path">파일</option>
                  <option value="tool">도구</option>
                </select>
                <button
                  type="button"
                  onClick={() => setIssueSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
                  title={issueSortDir === 'asc' ? '오름차순' : '내림차순'}
                  aria-label={issueSortDir === 'asc' ? '오름차순' : '내림차순'}
                  className="icon-toggle"
                >
                  {issueSortDir === 'asc' ? '▲' : '▼'}
                </button>
              </div>
              <div className="list">
                {sortedIssues.slice(0, issueLimit).map((item) => (
                  <button
                    key={item.key}
                    className={`list-item issue-item issue-${item.severity}`}
                    onClick={() => (item.path ? onOpenFile(item.path, item.line) : null)}
                    disabled={!item.path}
                    title={item.path ? `${item.path}:${item.line || ''}` : '경로 정보 없음'}
                  >
                    <span className="list-icon"><Icon name="alert" /></span>
                    <span className="list-text">{item.message}</span>
                    <span className="list-snippet">
                      {item.path ? `${item.path}${item.line ? `:${item.line}` : ''}` : '경로 없음'}
                    </span>
                  </button>
                ))}
                {sortedIssues.length === 0 && <div className="empty">이슈 없음</div>}
              </div>
              {sortedIssues.length > issueLimit && (
                <div className="hint">상위 {issueLimit}개만 표시됩니다.</div>
              )}
            </div>
          </details>
          <details className="panel panel-collapsible" open>
            <summary>테스트 결과 연결</summary>
            <div className="panel-body">
              <div className="row">
                <span className={`status-chip tone-${statusTone(status?.state)}`}>{status?.state || 'idle'}</span>
              </div>
              <div className="summary-grid test-summary-grid">
                <div className={`summary-card tone-${testsTone}`}>
                  <div className="summary-title">테스트</div>
                  <div className="summary-value">{testsOk ? 'OK' : testsOk === false ? 'FAIL' : '-'}</div>
                  <div className="summary-sub">cases {tests.total ?? tests.count ?? '-'}</div>
                </div>
                <div className={`summary-card tone-${coverageTone}`}>
                  <div className="summary-title">Coverage (Line)</div>
                  <div className="summary-value">{coverageLine != null ? `${coverageLine.toFixed(1)}%` : '-'}</div>
                  <div className="summary-sub">threshold {formatPct(coverage.threshold)}</div>
                </div>
                <div className={`summary-card tone-${coverageTone}`}>
                  <div className="summary-title">Coverage (Branch)</div>
                  <div className="summary-value">{coverageBranch != null ? `${coverageBranch.toFixed(1)}%` : '-'}</div>
                  <div className="summary-sub">enabled {coverage?.enabled ? 'Y' : 'N'}</div>
                </div>
                <div className={`summary-card tone-${qemuTone}`}>
                  <div className="summary-title">QEMU</div>
                  <div className="summary-value">{qemu.ok ? 'OK' : qemu.ok === false ? 'FAIL' : '-'}</div>
                  <div className="summary-sub">runtime {qemu.runtime ?? '-'}</div>
                </div>
              </div>
              <div className="summary-chart">
                <div className="bar-row">
                  <span className="bar-label">Line</span>
                  <div className="bar">
                    <div className={`bar-fill ${coverageBarClass}`} style={{ width: `${Math.min(100, Math.max(0, coverageLine || 0))}%` }} />
                  </div>
                  <span className="bar-value">{coverageLine != null ? `${coverageLine.toFixed(1)}%` : '-'}</span>
                </div>
                <div className="bar-row">
                  <span className="bar-label">Branch</span>
                  <div className="bar">
                    <div className={`bar-fill ${coverageBarClass}`} style={{ width: `${Math.min(100, Math.max(0, coverageBranch || 0))}%` }} />
                  </div>
                  <span className="bar-value">{coverageBranch != null ? `${coverageBranch.toFixed(1)}%` : '-'}</span>
                </div>
              </div>
              <div className="row">
                <button onClick={refreshSession} disabled={!sessionId}>결과 새로고침</button>
                <button onClick={onGoWorkflow}>워크플로우 보기</button>
              </div>
              <div className="row">
                <button onClick={loadLogList} disabled={!sessionId}>로그 목록</button>
                <input
                  placeholder="상대 경로"
                  value={selectedLogPath}
                  onChange={(e) => setSelectedLogPath(e.target.value)}
                />
                <button onClick={() => readLog(selectedLogPath)} disabled={!selectedLogPath}>읽기</button>
              </div>
              <div className="list">
                {flattenLogFiles().map((item) => (
                  <button
                    key={`${item.group}-${item.path}`}
                    className="list-item"
                    onClick={() => {
                      readLog(item.path)
                      const resolved = resolveLogPath(item.path)
                      if (onOpenEditorFile && resolved) onOpenEditorFile(resolved)
                    }}
                  >
                    <span className="list-text">{item.group}</span>
                    <span className="list-snippet">{item.path}</span>
                  </button>
                ))}
                {flattenLogFiles().length === 0 && <div className="empty">로그 파일 없음</div>}
              </div>
              {logContent ? <pre className="json">{logContent}</pre> : null}
            </div>
          </details>
            </>
          )}
        </section>
        <div className="resize-handle" onMouseDown={startDrag('left')} />
        <section className="tri-panel tri-center editor-panel">
          {openTabs.length > 0 ? (
            <div className="editor-tab-bar">
              {openTabs.map(tab => {
                const name = tab.path.split(/[\\/]/).pop() || tab.path
                const isActive = tab.id === activeTabId
                const isDirty = tabCacheRef.current.has(tab.path) && tabCacheRef.current.get(tab.path).text !== editorText && isActive
                return (
                  <button key={tab.id} className={`editor-tab${isActive ? ' active' : ''}`} onClick={() => switchTab(tab.id)} title={tab.path}>
                    <span className="editor-tab-name">{isDirty ? '● ' : ''}{name}</span>
                    <span className="editor-tab-close" onClick={(e) => closeTab(tab.id, e)}>&times;</span>
                  </button>
                )
              })}
            </div>
          ) : null}
          <div className="editor-header">
            <div className="editor-controls">
              <label>파일 경로(프로젝트 루트 기준)</label>
              <div className="input-row">
                <input value={editorPath} onChange={(e) => setEditorPath(e.target.value)} />
                <button onClick={onPickFile}>찾기</button>
              </div>
              <div className="row">
                <button onClick={editorRead} disabled={!editorPath}>읽기</button>
                <button onClick={editorWrite} disabled={!editorPath}>저장</button>
                <button onClick={formatEditorText} disabled={!editorText}>자동 포맷</button>
                <button onClick={() => setIsCodeFocus((prev) => !prev)}>
                  {isCodeFocus ? '기본 보기' : '코드 확대'}
                </button>
                <button onClick={() => setShortcutHelpOpen(true)} title="단축키 도움말">⌨</button>
              </div>
              {formatNotice ? <div className="hint">{formatNotice}</div> : null}
              {currentFileIssues.length > 0 ? (
                <div className="hint editor-issue-summary">
                  현재 파일 이슈: <strong>{currentFileIssues.length}</strong>건
                  {currentFileIssues.filter(i => i.severity === 'error').length > 0 ? (
                    <span className="issue-badge-inline issue-error"> Error {currentFileIssues.filter(i => i.severity === 'error').length}</span>
                  ) : null}
                  {currentFileIssues.filter(i => i.severity === 'warning').length > 0 ? (
                    <span className="issue-badge-inline issue-warning"> Warn {currentFileIssues.filter(i => i.severity === 'warning').length}</span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="editor-actions editor-controls">
              <label>탭 크기</label>
              <div className="row">
                <select value={tabSize} onChange={(e) => setTabSize(Number(e.target.value))}>
                  <option value={2}>2</option>
                  <option value={4}>4</option>
                  <option value={8}>8</option>
                </select>
              </div>
              <label>가이드/강조</label>
              <div className="row">
                <select value={indentGuideMode} onChange={(e) => setIndentGuideMode(e.target.value)}>
                  <option value="tab">탭 기준</option>
                  <option value="space">공백 전체</option>
                  <option value="custom">간격 지정</option>
                </select>
                {indentGuideMode === 'custom' ? (
                  <select value={indentGuideStep} onChange={(e) => setIndentGuideStep(Number(e.target.value))}>
                    <option value={2}>가이드 2</option>
                    <option value={4}>가이드 4</option>
                    <option value={8}>가이드 8</option>
                  </select>
                ) : null}
                <input
                  type="color"
                  value={indentGuideColor}
                  onChange={(e) => setIndentGuideColor(e.target.value)}
                  title="들여쓰기 가이드 색상"
                />
                <input
                  type="color"
                  value={lineHighlightColor}
                  onChange={(e) => setLineHighlightColor(e.target.value)}
                  title="현재 라인 강조 색상"
                />
              </div>
              <div className="row">
                <button
                  onClick={() => {
                    setTabSize(2)
                    setIndentGuideMode('tab')
                    setIndentGuideStep(2)
                    setIndentGuideColor('#94a3b8')
                    setLineHighlightColor('#93c5fd')
                    setFormatNotice('설정 초기화됨')
                  }}
                >
                  설정 초기화
                </button>
              </div>
            </div>
          </div>
          <div className="editor-body">
            {inFileSearchOpen ? (
              <div className="in-file-search-bar">
                <input
                  ref={inFileSearchRef}
                  value={inFileSearchTerm}
                  onChange={(e) => { setInFileSearchTerm(e.target.value); setInFileMatchIdx(0) }}
                  placeholder="파일 내 검색..."
                  onKeyDown={(e) => { if (e.key === 'Enter') cycleInFileMatch(e.shiftKey ? -1 : 1); if (e.key === 'Escape') setInFileSearchOpen(false) }}
                />
                <button type="button" className={`search-toggle${inFileSearchRegex ? ' active' : ''}`} onClick={() => setInFileSearchRegex(v => !v)} title="정규식">.*</button>
                <button type="button" className={`search-toggle${inFileSearchCase ? ' active' : ''}`} onClick={() => setInFileSearchCase(v => !v)} title="대소문자 구분">Aa</button>
                <span className="in-file-match-count">{inFileMatches.length > 0 ? `${inFileMatchIdx + 1}/${inFileMatches.length}` : '0'}</span>
                <button type="button" onClick={() => cycleInFileMatch(-1)} disabled={!inFileMatches.length}>▲</button>
                <button type="button" onClick={() => cycleInFileMatch(1)} disabled={!inFileMatches.length}>▼</button>
                <button type="button" onClick={() => setInFileSearchOpen(false)}>✕</button>
              </div>
            ) : null}
            {!editorText && (
              <div className="editor-empty">코드를 불러오면 여기에 표시됩니다.</div>
            )}
            <div className="editor-shell">
              <div className="editor-lines" ref={lineRef}>
                {Array.from({ length: lineCount }, (_, idx) => {
                  const ln = idx + 1
                  const lineIssues = issuesByLine.get(ln)
                  const isMatch = inFileSearchTerm && inFileMatches.some(m => m.line === ln)
                  return (
                    <button
                      key={`ln-${ln}`}
                      className={`line-number${ln === currentLine ? ' is-active' : ''}${isMatch ? ' is-search-match' : ''}`}
                      type="button"
                      onClick={() => jumpToLine(ln)}
                      onContextMenu={(event) => handleLineContextMenu(event, ln)}
                      onMouseEnter={lineIssues ? () => setHoveredIssueLine(ln) : undefined}
                      onMouseLeave={lineIssues ? () => setHoveredIssueLine(null) : undefined}
                    >
                      {lineIssues ? (
                        <span className={`gutter-marker gutter-${lineIssues[0].severity}`} title={lineIssues.map(i => i.message).join('\n')}>●</span>
                      ) : null}
                      {ln}
                      {hoveredIssueLine === ln && lineIssues ? (
                        <div className="gutter-tooltip">
                          {lineIssues.map((issue, ii) => (
                            <div key={ii} className={`gutter-tooltip-item issue-${issue.severity}`}>
                              <span className="gutter-tooltip-sev">{issue.severity}</span>
                              <span className="gutter-tooltip-msg">{issue.message}</span>
                              {onRequestAiGuide ? (
                                <button type="button" className="btn-xs btn-ai-fix" onClick={(e) => { e.stopPropagation(); requestAiFix(issue) }} disabled={issueFixLoading}>
                                  {issueFixLoading ? '...' : 'AI Fix'}
                                </button>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </button>
                  )
                })}
              </div>
              <div
                className="editor-code"
                ref={codeWrapRef}
                onScroll={syncScroll}
                style={{
                  '--current-line-top': `${(currentLine - 1) * lineHeightPx + editorPadding}px`,
                  '--code-line-height': `${lineHeightPx}px`,
                  '--tab-size': tabSize,
                  '--indent-guide-step': indentGuideMode === 'space'
                    ? '1ch'
                    : indentGuideMode === 'custom'
                      ? `${indentGuideStep}ch`
                      : `${tabSize}ch`,
                  '--indent-guide-color': indentGuideColor,
                  '--line-highlight-color': lineHighlightColor,
                }}
              >
                <Editor
                  value={editorText}
                  onValueChange={setEditorText}
                  highlight={highlightCode}
                  padding={editorPadding}
                  className="editor-code-inner"
                onKeyUp={updateCurrentLine}
                onClick={updateCurrentLine}
                onScroll={syncScroll}
                />
              </div>
            </div>
            <div className="editor-statusbar">
              <span className="statusbar-item">Ln {currentLine}, Col 1</span>
              <span className="statusbar-item">{languageId !== 'plain' ? languageId.toUpperCase() : 'TEXT'}</span>
              <span className="statusbar-item">Tab: {tabSize}</span>
              <span className="statusbar-item">{indentGuideMode === 'tab' ? 'Tabs' : 'Spaces'}</span>
              {currentFileIssues.length > 0 ? (
                <span className="statusbar-item statusbar-issues">Issues: {currentFileIssues.length}</span>
              ) : null}
              <span className="statusbar-item statusbar-lines">{lineCount} lines</span>
            </div>
            {lineMenu ? (
              <div className="line-menu" style={{ top: lineMenu.y, left: lineMenu.x }}>
                <button type="button" onClick={() => { copyText(getLineText(lineMenu.line)); closeLineMenu() }}>
                  라인 복사
                </button>
                <button type="button" onClick={() => { setRangeStart(lineMenu.line); closeLineMenu() }}>
                  범위 시작
                </button>
                <button type="button" onClick={() => { setRangeEnd(lineMenu.line); closeLineMenu() }}>
                  범위 끝
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (rangeStart && rangeEnd) {
                      const start = Math.min(rangeStart, rangeEnd)
                      const end = Math.max(rangeStart, rangeEnd)
                      const lines = String(editorText || '').split(/\r?\n/)
                      const text = lines.slice(start - 1, end).join('\n')
                      copyText(text)
                    }
                    closeLineMenu()
                  }}
                  disabled={!rangeStart || !rangeEnd}
                >
                  선택 범위 복사
                </button>
              </div>
            ) : null}
          </div>
        </section>
        <div className="resize-handle" onMouseDown={startDrag('right')} />
        <section className={`tri-panel tri-right${rightCollapsed ? ' panel-collapsed' : ''}`} style={rightCollapsed ? { width: 32 } : { width: rightWidth }}>
          {rightCollapsed ? (
            <button className="panel-expand-btn" onClick={() => setRightCollapsed(false)} title="우측 패널 펼치기">▶</button>
          ) : (
          <div className="panel-group">
            <div className="panel-collapse-bar">
              <button className="panel-collapse-btn" onClick={() => setRightCollapsed(true)} title="접기">◀</button>
            </div>
            <div className="help-box">
              <h4>오른쪽 패널 사용 방법</h4>
              <ul>
                <li>검색/치환: 파일 내 검색과 문자열 치환을 수행합니다.</li>
                <li>AI 변경 가이드: 선택 라인 기준으로 변경 가이드/모의 테스트를 생성합니다.</li>
                <li>Git: 변경사항, diff, 브랜치 정보를 확인합니다.</li>
              </ul>
            </div>
            <details className="panel panel-collapsible" open>
              <summary>검색 / 치환</summary>
              <div className="panel-body">
            <div className="input-row">
              <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="검색어" />
              <button onClick={runSearch}>검색</button>
            </div>
            <div className="list">
              {searchResults.map((result) => (
                <button
                  key={`${result.path}:${result.line}`}
                  className="list-item"
                  onClick={() => onOpenFile(result.path, result.line)}
                >
                  <span className="list-icon"><Icon name="file" /></span>
                  <span className="list-text">{result.path}:{result.line}</span>
                  <span className="list-snippet">{result.text}</span>
                </button>
              ))}
              {searchResults.length === 0 && <div className="empty">검색 결과 없음</div>}
            </div>
            <div className="input-row">
              <input value={replaceQuery} onChange={(e) => setReplaceQuery(e.target.value)} placeholder="찾을 텍스트" />
              <input value={replaceValue} onChange={(e) => setReplaceValue(e.target.value)} placeholder="바꿀 텍스트" />
              <button onClick={runReplaceText} disabled={!editorPath}>치환</button>
            </div>
              </div>
            </details>

            <details className="panel panel-collapsible" open>
              <summary>AI 변경 가이드</summary>
              <div className="panel-body">
                <div className="row ai-preset-row">
                  <button onClick={() => setAiPrompt(aiPreset.changeGuide)}>변경 가이드</button>
                  <button onClick={() => setAiPrompt(aiPreset.staticMock)}>정적 모의</button>
                  <button onClick={() => setAiPrompt(aiPreset.unitMock)}>유닛 모의</button>
                  <button onClick={() => setAiPrompt(aiPreset.codeReview)}>코드 리뷰</button>
                  <button onClick={() => setAiPrompt(aiPreset.refactor)}>리팩토링</button>
                  {onSendToChat && editorExcerpt && (
                    <button onClick={() => onSendToChat(`파일 ${editorPath}의 선택 영역(라인 ${editorStartLine}-${editorEndLine}) 코드에 대해 분석해줘:\n\`\`\`\n${editorExcerpt.slice(0, 500)}\n\`\`\``)}>💬 챗봇에 물어보기</button>
                  )}
                </div>
                {currentFileIssues.length > 0 ? (
                  <details className="ai-issue-quick">
                    <summary className="hint">현재 파일 이슈에서 AI Fix 요청 ({currentFileIssues.length}건)</summary>
                    <div className="list ai-issue-list">
                      {currentFileIssues.slice(0, 10).map((issue, i) => (
                        <button key={i} className={`list-item issue-item issue-${issue.severity}`} onClick={() => requestAiFix(issue)} disabled={issueFixLoading}>
                          <span className="list-icon"><Icon name="alert" /></span>
                          <span className="list-text">L{issue.line}: {issue.message}</span>
                          <span className="btn-xs">AI Fix</span>
                        </button>
                      ))}
                    </div>
                  </details>
                ) : null}
                <label>요청 내용</label>
                <textarea
                  rows={4}
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder="AI에게 요청할 내용을 입력하세요."
                />
                <div className="row">
                  <button onClick={handleAiGuide} disabled={aiLoading || !aiPrompt.trim()}>
                    {aiLoading ? '생성 중...' : '가이드 생성'}
                  </button>
                  <button onClick={() => setAiAnswer('')} disabled={!aiAnswer}>지우기</button>
                </div>
                {editorExcerpt ? (
                  <>
                    <div className="hint">선택 라인({editorStartLine}-{editorEndLine}) 기준 요약 첨부됨</div>
                    <pre className="json" style={{ maxHeight: '100px', overflow: 'auto' }}>{editorExcerpt}</pre>
                  </>
                ) : (
                  <div className="hint">선택 라인이 없으면 전체 컨텍스트만 사용됩니다.</div>
                )}
                {aiAnswer ? (
                  <div className="ai-answer-box">
                    <SimpleMarkdown text={aiAnswer} onInsertCode={insertCodeAtCursor} />
                  </div>
                ) : null}
              </div>
            </details>

            <details className="panel panel-collapsible">
              <summary>Git</summary>
              <div className="panel-body">
            <div className="row">
              <button onClick={loadGitStatus}>상태</button>
              <button onClick={() => loadGitDiff(false)}>변경(diff)</button>
              <button onClick={() => loadGitDiff(true)}>스테이징(diff)</button>
              <button onClick={loadGitLog}>로그</button>
              <button onClick={loadGitBranches}>브랜치</button>
            </div>
            {gitStatusInfo?.branchLine ? <div className="hint git-branch-indicator">⎇ {gitStatusInfo.branchLine}</div> : null}
            <div className="panel-grid git-status-grid">
              <div>
                <div className="hint">Staged ({(gitStatusInfo?.staged || []).length})</div>
                <ul className="plain-list git-file-list">
                  {(gitStatusInfo?.staged || []).map((p) => (
                    <li key={`staged-${p}`} className="git-file-item">
                      <span className="git-file-name" onClick={() => onOpenFile(p)}>{p}</span>
                      <button type="button" className="btn-xs btn-outline" onClick={() => { setGitPathInput(p); setTimeout(() => runGitStage(true), 0) }}>unstage</button>
                    </li>
                  ))}
                  {(gitStatusInfo?.staged || []).length === 0 && <li className="empty">없음</li>}
                </ul>
              </div>
              <div>
                <div className="hint">Unstaged ({(gitStatusInfo?.unstaged || []).length})</div>
                <ul className="plain-list git-file-list">
                  {(gitStatusInfo?.unstaged || []).map((p) => (
                    <li key={`unstaged-${p}`} className="git-file-item">
                      <span className="git-file-name" onClick={() => onOpenFile(p)}>{p}</span>
                      <button type="button" className="btn-xs btn-outline" onClick={() => { setGitPathInput(p); setTimeout(() => runGitStage(false), 0) }}>stage</button>
                    </li>
                  ))}
                  {(gitStatusInfo?.unstaged || []).length === 0 && <li className="empty">없음</li>}
                </ul>
              </div>
              <div>
                <div className="hint">Untracked ({(gitStatusInfo?.untracked || []).length})</div>
                <ul className="plain-list git-file-list">
                  {(gitStatusInfo?.untracked || []).map((p) => (
                    <li key={`untracked-${p}`} className="git-file-item">
                      <span className="git-file-name" onClick={() => onOpenFile(p)}>{p}</span>
                      <button type="button" className="btn-xs btn-outline" onClick={() => { setGitPathInput(p); setTimeout(() => runGitStage(false), 0) }}>stage</button>
                    </li>
                  ))}
                  {(gitStatusInfo?.untracked || []).length === 0 && <li className="empty">없음</li>}
                </ul>
              </div>
            </div>
            <label>파일 경로(옵션)</label>
            <input value={gitPathInput} onChange={(e) => setGitPathInput(e.target.value)} placeholder="예: src/App.jsx" />
            <div className="row">
              <button onClick={() => runGitStage(false)}>스테이징</button>
              <button onClick={() => runGitStage(true)}>언스테이징</button>
            </div>
            <label>커밋 메시지</label>
            <div className="input-row">
              <input value={gitCommitMessage} onChange={(e) => setGitCommitMessage(e.target.value)} />
              <button onClick={runGitCommit}>커밋</button>
            </div>
            <label>브랜치</label>
            <div className="input-row">
              {gitBranches ? (
                <select value={gitBranchName} onChange={(e) => setGitBranchName(e.target.value)}>
                  <option value="">브랜치 선택...</option>
                  {String(gitBranches).split('\n').filter(Boolean).map(b => {
                    const name = b.replace(/^\*?\s+/, '').trim()
                    return <option key={name} value={name}>{b.trim()}</option>
                  })}
                </select>
              ) : (
                <input value={gitBranchName} onChange={(e) => setGitBranchName(e.target.value)} placeholder="branch-name" />
              )}
              <button onClick={() => runGitCheckout(false)}>체크아웃</button>
              <button onClick={() => runGitCheckout(true)}>생성</button>
            </div>
            <div className="panel-grid">
              <div>
                <div className="hint">Diff</div>
                <div className="diff-viewer">
                  {gitDiffRows.map((row, idx) => (
                    <div
                      key={`diff-${idx}`}
                      className={`diff-row ${row.type}${row.file ? ' diff-clickable' : ''}`}
                      onClick={() => (row.file ? onOpenFile(row.file, row.rightNo || row.leftNo) : null)}
                    >
                      <div className="diff-num">{row.leftNo ?? ''}</div>
                      <div className="diff-cell">{row.left}</div>
                      <div className="diff-num">{row.rightNo ?? ''}</div>
                      <div className="diff-cell">{row.right}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="hint">Staged Diff</div>
                <div className="diff-viewer">
                  {gitDiffStagedRows.map((row, idx) => (
                    <div
                      key={`staged-${idx}`}
                      className={`diff-row ${row.type}${row.file ? ' diff-clickable' : ''}`}
                      onClick={() => (row.file ? onOpenFile(row.file, row.rightNo || row.leftNo) : null)}
                    >
                      <div className="diff-num">{row.leftNo ?? ''}</div>
                      <div className="diff-cell">{row.left}</div>
                      <div className="diff-num">{row.rightNo ?? ''}</div>
                      <div className="diff-cell">{row.right}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="hint">Log</div>
                <div className="git-log-list">
                  {String(gitLog || '').split('\n').filter(Boolean).map((line, i) => (
                    <div key={i} className="git-log-entry">{line}</div>
                  ))}
                  {!gitLog && <div className="empty">로그 없음</div>}
                </div>
              </div>
              <div>
                <div className="hint">Branches</div>
                <div className="git-branch-list">
                  {String(gitBranches || '').split('\n').filter(Boolean).map((b, i) => (
                    <div key={i} className={`git-branch-entry${b.trim().startsWith('*') ? ' current' : ''}`}
                         onClick={() => setGitBranchName(b.replace(/^\*?\s+/, '').trim())}
                    >{b.trim()}</div>
                  ))}
                  {!gitBranches && <div className="empty">브랜치 없음</div>}
                </div>
              </div>
            </div>
              </div>
            </details>
          </div>
          )}
        </section>
      </div>
      {shortcutHelpOpen ? (
        <div className="overlay-backdrop" onClick={() => setShortcutHelpOpen(false)}>
          <div className="overlay-panel shortcut-help" onClick={(e) => e.stopPropagation()}>
            <h4>키보드 단축키</h4>
            <table className="shortcut-table">
              <tbody>
                <tr><td><kbd>Ctrl+S</kbd></td><td>파일 저장</td></tr>
                <tr><td><kbd>Ctrl+F</kbd></td><td>파일 내 검색</td></tr>
                <tr><td><kbd>Ctrl+G</kbd></td><td>라인 이동</td></tr>
                <tr><td><kbd>Escape</kbd></td><td>코드 확대 해제 / 닫기</td></tr>
                <tr><td><kbd>Ctrl+Shift+?</kbd></td><td>단축키 도움말</td></tr>
              </tbody>
            </table>
            <button onClick={() => setShortcutHelpOpen(false)}>닫기</button>
          </div>
        </div>
      ) : null}
      {gotoLineOpen ? (
        <div className="overlay-backdrop" onClick={() => setGotoLineOpen(false)}>
          <div className="overlay-panel goto-line-dialog" onClick={(e) => e.stopPropagation()}>
            <h4>라인 이동</h4>
            <div className="input-row">
              <input
                type="number"
                min={1}
                max={lineCount}
                value={gotoLineInput}
                onChange={(e) => setGotoLineInput(e.target.value)}
                placeholder={`1 ~ ${lineCount}`}
                autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter') handleGotoLine() }}
              />
              <button onClick={handleGotoLine}>이동</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default LocalEditor
