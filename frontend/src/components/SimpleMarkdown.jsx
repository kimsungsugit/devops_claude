import { useState } from 'react'
import Prism from 'prismjs'

const copyToClip = async (text) => {
  try { await navigator.clipboard.writeText(text) } catch { /* noop */ }
}

const LANG_MAP = {
  c: 'c', cpp: 'cpp', 'c++': 'cpp', h: 'cpp', js: 'javascript',
  javascript: 'javascript', ts: 'typescript', typescript: 'typescript',
  py: 'python', python: 'python', json: 'json', yaml: 'yaml',
  bash: 'bash', sh: 'bash', md: 'markdown', diff: 'clike',
}

const hlBlock = (code, lang) => {
  const key = LANG_MAP[String(lang || '').toLowerCase()] || 'clike'
  const grammar = Prism.languages[key] || Prism.languages.clike
  if (!grammar) return Prism.util.encode(code)
  try { return Prism.highlight(code, grammar, key) } catch { return code }
}

const renderInline = (text) => {
  if (!text) return null
  const parts = []
  let rest = text
  let k = 0
  while (rest) {
    const codeM = rest.match(/`([^`]+)`/)
    const boldM = rest.match(/\*\*(.+?)\*\*/)
    let earliest = null
    let type = null
    if (codeM) { earliest = codeM; type = 'code' }
    if (boldM && (!earliest || boldM.index < earliest.index)) { earliest = boldM; type = 'bold' }
    if (!earliest) { parts.push(rest); break }
    if (earliest.index > 0) parts.push(rest.slice(0, earliest.index))
    if (type === 'code') parts.push(<code key={k++} className="smd-ic">{earliest[1]}</code>)
    else parts.push(<strong key={k++}>{earliest[1]}</strong>)
    rest = rest.slice(earliest.index + earliest[0].length)
  }
  return parts
}

const SimpleMarkdown = ({ text, onInsertCode }) => {
  const [copiedIdx, setCopiedIdx] = useState(-1)
  if (!text || !text.trim()) return null

  const blocks = []
  const lines = text.split('\n')
  let buf = []
  let inCode = false
  let codeLang = ''

  const flushText = () => {
    if (buf.length > 0) { blocks.push({ type: 'text', content: buf.join('\n') }); buf = [] }
  }

  for (const line of lines) {
    const fence = line.match(/^```(\w*)/)
    if (fence) {
      if (inCode) {
        blocks.push({ type: 'code', lang: codeLang, content: buf.join('\n') })
        buf = []; inCode = false
      } else {
        flushText(); codeLang = fence[1] || ''; inCode = true
      }
      continue
    }
    buf.push(line)
  }
  if (inCode && buf.length) blocks.push({ type: 'code', lang: codeLang, content: buf.join('\n') })
  else flushText()

  return (
    <div className="smd">
      {blocks.map((block, idx) => {
        if (block.type === 'code') {
          const html = hlBlock(block.content, block.lang)
          return (
            <div key={idx} className="smd-code-block">
              <div className="smd-code-toolbar">
                <span className="smd-code-lang">{block.lang || 'code'}</span>
                <button type="button" className="btn-outline btn-xs" onClick={async () => {
                  await copyToClip(block.content); setCopiedIdx(idx); setTimeout(() => setCopiedIdx(-1), 1500)
                }}>{copiedIdx === idx ? '복사됨' : '복사'}</button>
                {typeof onInsertCode === 'function' ? (
                  <button type="button" className="btn-outline btn-xs" onClick={() => onInsertCode(block.content)}>삽입</button>
                ) : null}
              </div>
              <pre className="smd-code-pre"><code dangerouslySetInnerHTML={{ __html: html }} /></pre>
            </div>
          )
        }
        return (
          <div key={idx} className="smd-text">
            {block.content.split('\n').map((line, li) => {
              const t = line.trimStart()
              if (!t) return <div key={li} className="smd-blank" />
              if (t.startsWith('### ')) return <h5 key={li} className="smd-h">{renderInline(t.slice(4))}</h5>
              if (t.startsWith('## ') || t.startsWith('# ')) {
                const off = t.startsWith('## ') ? 3 : 2
                return <h4 key={li} className="smd-h">{renderInline(t.slice(off))}</h4>
              }
              if (t.startsWith('- ') || t.startsWith('* '))
                return <div key={li} className="smd-li">{renderInline(t.slice(2))}</div>
              if (/^\d+\.\s/.test(t)) {
                const m = t.match(/^(\d+)\.\s(.*)/)
                return <div key={li} className="smd-li"><span className="smd-li-num">{m[1]}.</span> {renderInline(m[2])}</div>
              }
              return <p key={li} className="smd-p">{renderInline(t)}</p>
            })}
          </div>
        )
      })}
    </div>
  )
}

export default SimpleMarkdown
