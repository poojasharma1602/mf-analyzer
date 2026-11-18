import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Banner, Card, Spinner } from './ui.jsx'

export default function BenchmarksPanel({ rows, selected, onChanged }) {
  const [info, setInfo] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null) // {kind, text, warnings}
  const fileRef = useRef(null)

  const load = useCallback(async () => {
    try {
      setInfo(await api.getBenchmarks())
      setLoadError(null)
    } catch (e) {
      setLoadError(e)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const ruleNames = info ? [...new Set(info.mapping.rules.map((r) => r.benchmark))] : []
  const importedNames = info ? info.benchmarks.map((b) => b.name) : []
  const overrides = info ? Object.fromEntries(info.overrides.map((o) => [o.scheme_code, o.benchmark_name])) : {}
  const rowByCode = Object.fromEntries(rows.map((r) => [r.scheme_code, r]))

  async function submit(e) {
    e.preventDefault()
    if (!name.trim() || !file) return
    setBusy(true)
    setResult(null)
    try {
      const res = await api.importBenchmark(name.trim(), file)
      setResult({ kind: 'ok', text: `Imported “${res.benchmark.name}”: ${res.benchmark.n_points} points, ${res.benchmark.first_date} → ${res.benchmark.last_date}.`, warnings: res.warnings })
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      await load()
      onChanged()
    } catch (err) {
      setResult({ kind: 'error', text: err.message, warnings: [] })
    } finally {
      setBusy(false)
    }
  }

  async function remove(n) {
    if (!window.confirm(`Delete imported benchmark “${n}”? Metrics that need it will become N/A.`)) return
    try {
      await api.deleteBenchmark(n)
      await load()
      onChanged()
    } catch (err) {
      setResult({ kind: 'error', text: err.message, warnings: [] })
    }
  }

  async function setOverride(code, value) {
    try {
      await api.setOverride(code, value || null)
      await load()
      onChanged()
    } catch (err) {
      setResult({ kind: 'error', text: err.message, warnings: [] })
    }
  }

  return (
    <div className="space-y-4">
      <Banner kind="info" title="Why a CSV import?">
        Beta, Jensen's alpha and the information ratio need a benchmark <strong>total return index (TRI)</strong>. This app does not scrape index websites or
        guess API endpoints; export the TRI history from a source you are entitled to use (e.g. the index provider's site) as a CSV with the columns
        <code className="mx-1 rounded bg-white/60 px-1">Date</code> and <code className="mx-1 rounded bg-white/60 px-1">Index Value</code>. Dates must be day-first
        (DD-MM-YYYY, DD/MM/YYYY, DD-Mon-YYYY) or ISO (YYYY-MM-DD). Daily or month-end rows both work. The importer also accepts NSE historical CSV columns Date and Close. For accurate mutual-fund comparison use TRI, not the price index (PR).
      </Banner>

      {loadError && <Banner kind="error" title="Could not load benchmarks">{loadError.message}</Banner>}

      <Card title="Import benchmark TRI CSV">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Benchmark name</span>
            <input list="bench-names" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. NIFTY 100 TRI" className="w-64 rounded-lg border border-slate-300 px-3 py-2 text-sm" required />
            <datalist id="bench-names">
              {ruleNames.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">CSV file</span>
            <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files[0] || null)} className="block text-sm" required />
          </label>
          <button disabled={busy || !name.trim() || !file} className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50">
            {busy ? 'Importing…' : 'Import'}
          </button>
          {busy && <Spinner label="Validating…" />}
        </form>
        <p className="mt-2 text-xs text-slate-500">Your uploaded NIFTY 500 PR file covers about one year, not the default 24 required monthly returns. To calculate from short history, set Settings → Analysis window to 12 and Minimum observations to 6; results will be less robust. For standard comparisons, import at least 25 months of TRI data. Importing with an existing name replaces that benchmark. The name must match the benchmark names used by the mapping rules below (or an override) for funds to pick it up.</p>
        {result && (
          <div className="mt-3 space-y-2">
            <Banner kind={result.kind === 'ok' ? 'ok' : 'error'} title={result.kind === 'ok' ? 'Import complete' : 'Import failed'}>{result.text}</Banner>
            {result.warnings.map((w, i) => (
              <Banner key={i} kind="warn">{w}</Banner>
            ))}
          </div>
        )}
      </Card>

      <Card title="Imported benchmarks">
        {!info ? (
          <Spinner label="Loading…" />
        ) : info.benchmarks.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing imported yet. Benchmark-relative metrics show N/A until you import a matching TRI.</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1 pr-4">Name</th><th className="pr-4">From</th><th className="pr-4">To</th><th className="pr-4">Points</th><th className="pr-4">File</th><th />
              </tr>
            </thead>
            <tbody>
              {info.benchmarks.map((b) => (
                <tr key={b.name} className="border-t border-slate-100">
                  <td className="py-1.5 pr-4 font-medium">{b.name}</td>
                  <td className="num pr-4">{b.first_date}</td>
                  <td className="num pr-4">{b.last_date}</td>
                  <td className="num pr-4">{b.n_points}</td>
                  <td className="pr-4 text-xs text-slate-500">{b.source_filename}</td>
                  <td className="text-right"><button onClick={() => remove(b.name)} className="text-xs text-slate-500 hover:text-rose-700">Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Fallback benchmark">
        <p className="mb-3 text-sm text-slate-600">
          Used for any fund whose own mapped benchmark has not been imported. If only one benchmark is imported it is used automatically; with several, choose one here.
          Each affected fund shows a warning so you always know the comparison index.
        </p>
        <select
          value={info?.default_benchmark || ''}
          onChange={async (e) => { try { await api.setDefaultBenchmark(e.target.value); await load(); onChanged() } catch (err) { setResult({ kind: 'error', text: err.message, warnings: [] }) } }}
          className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          aria-label="Fallback benchmark"
        >
          <option value="">{importedNames.length === 1 ? `Automatic (${importedNames[0]})` : 'None (choose one)'}</option>
          {importedNames.map((n) => (<option key={n} value={n}>{n}</option>))}
        </select>
      </Card>

      <Card title="Benchmark mapping for your selected funds">
        {info && <p className="mb-3 text-xs text-slate-500">{info.mapping.note}</p>}
        {selected.length === 0 ? (
          <p className="text-sm text-slate-500">Add funds on the Dashboard to map benchmarks.</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500"><th className="py-1 pr-4">Scheme</th><th className="pr-4">Category</th><th className="pr-4">Currently used</th><th>Override</th></tr>
            </thead>
            <tbody>
              {selected.map((f) => {
                const r = rowByCode[f.scheme_code]
                const b = r && !r.error ? r.benchmark : null
                return (
                  <tr key={f.scheme_code} className="border-t border-slate-100 align-top">
                    <td className="py-1.5 pr-4"><div>{f.scheme_name}</div><div className="num text-xs text-slate-500">Code {f.scheme_code}</div></td>
                    <td className="pr-4 text-xs text-slate-600">{r && !r.error ? r.category || '—' : '—'}</td>
                    <td className="pr-4 text-xs">
                      {b ? (b.name ? <><span className="font-medium">{b.name}</span> <span className="text-slate-500">({b.source}{b.imported ? '' : ', not imported'})</span></> : <span className="text-slate-400">none</span>) : '—'}
                    </td>
                    <td>
                      <select value={overrides[f.scheme_code] || ''} onChange={(e) => setOverride(f.scheme_code, e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-xs" aria-label={`Benchmark override for ${f.scheme_name}`}>
                        <option value="">Default rule</option>
                        {importedNames.map((n) => (
                          <option key={n} value={n}>{n}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {info && (
          <div className="mt-4 text-xs text-slate-500">
            <div className="mb-1 font-medium text-slate-600">Default rule benchmark names (import a CSV under exactly one of these names to use it):</div>
            <div className="flex flex-wrap gap-2">
              {ruleNames.map((n) => (
                <span key={n} className={`rounded px-2 py-0.5 ${importedNames.some((i) => i.toLowerCase() === n.toLowerCase()) ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{n}{importedNames.some((i) => i.toLowerCase() === n.toLowerCase()) ? ' ✓' : ''}</span>
              ))}
            </div>
            <div className="mt-2">Rules live in <code>backend/config/benchmark_mapping.json</code> and can be edited.</div>
          </div>
        )}
      </Card>
    </div>
  )
}
