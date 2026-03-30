import { useState, useCallback } from 'react'

const api = async (path, options = {}) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}

export default function ExcelCompare({ onMessage }) {
  const [sourceFile, setSourceFile] = useState(null)
  const [targetFile, setTargetFile] = useState(null)
  const [sheetSource, setSheetSource] = useState(1)
  const [sheetTarget, setSheetTarget] = useState(1)
  const [compareResult, setCompareResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const handleSourceFileChange = useCallback((e) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setSourceFile(selectedFile)
      setCompareResult(null)
      setMessage('')
    }
  }, [])

  const handleTargetFileChange = useCallback((e) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setTargetFile(selectedFile)
      setCompareResult(null)
      setMessage('')
    }
  }, [])

  const handleCompare = useCallback(async () => {
    if (!sourceFile || !targetFile) {
      setMessage('두 파일을 모두 선택해주세요')
      return
    }

    setLoading(true)
    setMessage('')
    try {
      const formData = new FormData()
      formData.append('source_file', sourceFile)
      formData.append('target_file', targetFile)
      formData.append('sheet_source', sheetSource)
      formData.append('sheet_target', sheetTarget)

      const res = await fetch(`/api/excel/compare-upload?sheet_source=${sheetSource}&sheet_target=${sheetTarget}`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `HTTP ${res.status}`)
      }

      const data = await res.json()
      setCompareResult(data)
      
      if (data.is_same) {
        setMessage('두 파일이 동일합니다')
        if (onMessage) onMessage('Excel 파일 비교 완료: 동일함')
      } else {
        setMessage(`${data.diff_count}개의 차이점이 발견되었습니다`)
        if (onMessage) onMessage(`Excel 파일 비교 완료: ${data.diff_count}개 차이점`)
      }
    } catch (e) {
      setMessage(`비교 실패: ${e.message}`)
      if (onMessage) onMessage(`Excel 파일 비교 실패: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }, [sourceFile, targetFile, sheetSource, sheetTarget, onMessage])

  return (
    <div style={{ padding: '20px' }}>
      <h2>Excel 파일 비교</h2>
      
      <div style={{ marginBottom: '20px' }}>
        <div style={{ marginBottom: '15px' }}>
          <label>
            소스 파일:
            <input
              type="file"
              accept=".xlsx,.xlsm"
              onChange={handleSourceFileChange}
              style={{ marginLeft: '10px' }}
            />
          </label>
          {sourceFile && <div style={{ marginTop: '5px', color: 'var(--text-muted)' }}>선택된 파일: {sourceFile.name}</div>}
        </div>
        
        <div style={{ marginBottom: '15px' }}>
          <label>
            타겟 파일:
            <input
              type="file"
              accept=".xlsx,.xlsm"
              onChange={handleTargetFileChange}
              style={{ marginLeft: '10px' }}
            />
          </label>
          {targetFile && <div style={{ marginTop: '5px', color: 'var(--text-muted)' }}>선택된 파일: {targetFile.name}</div>}
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label>
            소스 시트 번호:
            <input
              type="number"
              min="1"
              value={sheetSource}
              onChange={(e) => setSheetSource(parseInt(e.target.value) || 1)}
              style={{ marginLeft: '10px', width: '80px' }}
            />
          </label>
        </div>

        <div style={{ marginBottom: '15px' }}>
          <label>
            타겟 시트 번호:
            <input
              type="number"
              min="1"
              value={sheetTarget}
              onChange={(e) => setSheetTarget(parseInt(e.target.value) || 1)}
              style={{ marginLeft: '10px', width: '80px' }}
            />
          </label>
        </div>
      </div>

      <div style={{ marginBottom: '20px' }}>
        <button
          onClick={handleCompare}
          disabled={loading || !sourceFile || !targetFile}
          style={{
            padding: '8px 16px',
            backgroundColor: 'var(--accent)',
            color: 'var(--text-inverse)',
            border: 'none',
            borderRadius: 'var(--radius-sm)',
            cursor: !loading && sourceFile && targetFile ? 'pointer' : 'not-allowed',
          }}
        >
          {loading ? '비교 중...' : '비교'}
        </button>
      </div>

      {message && (
        <div style={{ marginBottom: '20px', padding: '10px', backgroundColor: message.includes('실패') ? 'var(--color-danger-soft)' : message.includes('동일') ? 'var(--color-success-soft)' : 'var(--color-warning-soft)', borderRadius: 'var(--radius-sm)' }}>
          {message}
        </div>
      )}

      {compareResult && !compareResult.is_same && (
        <div style={{ marginBottom: '20px', padding: '15px', backgroundColor: 'var(--bg)', borderRadius: 'var(--radius-sm)' }}>
          <h3>차이점 목록 ({compareResult.diff_count}개)</h3>
          <div style={{ maxHeight: '500px', overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
              <thead>
                <tr style={{ backgroundColor: 'var(--sidebar)', position: 'sticky', top: 0 }}>
                  <th style={{ padding: '8px', border: '1px solid var(--border)' }}>No</th>
                  <th style={{ padding: '8px', border: '1px solid var(--border)' }}>Row</th>
                  <th style={{ padding: '8px', border: '1px solid var(--border)' }}>Column</th>
                  <th style={{ padding: '8px', border: '1px solid var(--border)' }}>Source Data</th>
                  <th style={{ padding: '8px', border: '1px solid var(--border)' }}>Target Data</th>
                </tr>
              </thead>
              <tbody>
                {compareResult.diffs.map((diff, idx) => (
                  <tr key={idx}>
                    <td style={{ padding: '8px', border: '1px solid var(--border)' }}>{idx + 1}</td>
                    <td style={{ padding: '8px', border: '1px solid var(--border)' }}>{diff.row}</td>
                    <td style={{ padding: '8px', border: '1px solid var(--border)' }}>{diff.column || '-'}</td>
                    <td style={{ padding: '8px', border: '1px solid var(--border)', backgroundColor: 'var(--color-danger-soft)' }}>{diff.source_data}</td>
                    <td style={{ padding: '8px', border: '1px solid var(--border)', backgroundColor: 'var(--color-info-soft)' }}>{diff.target_data}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
