import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { downloadBlob } from './format.js'
import BenchmarksPanel from './components/BenchmarksPanel.jsx'
import Charts from './components/Charts.jsx'
import ComparisonTable from './components/ComparisonTable.jsx'
import FundDetail from './components/FundDetail.jsx'
import FundSearch from './components/FundSearch.jsx'
import MethodologyPanel from './components/MethodologyPanel.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import { Banner, Card, Spinner } from './components/ui.jsx'

const MAX_FUNDS = 20
const TABS = [
  ['dashboard', 'Dashboard'],
  ['benchmarks', 'Benchmarks'],
  ['settings', 'Settings'],
  ['methodology', 'Methodology'],
]

function HealthPill({ health, error, onProbe, probing }) {
  let tone = 'bg-slate-100 text-slate-600'
  let text = 'Checking backend…'
  if (error) {
    tone = 'bg-rose-100 text-rose-800'
    text = 'Backend offline'
  } else if (health) {
    const p = health.provider
    if (p.probe && !p.probe.reachable) {
      tone = 'bg-rose-100 text-rose-800'
      text = 'Provider unreachable'
    } else if (p.consecutive_failures > 0) {
      tone = 'bg-amber-100 text-amber-800'
      text = 'Provider errors (using cache)'
    } else if (p.last_success_at) {
      tone = 'bg-emerald-100 text-emerald-800'
      text = 'Provider OK'
    } else {
      tone = 'bg-slate-100 text-slate-700'
      text = 'Backend OK'
    }
  }
  return (
    <button onClick={onProbe} title="Click to test whether the data provider is reachable" className={`rounded-full px-3 py-1 text-xs font-medium ${tone}`}>
      {probing ? 'Testing provider…' : text}
    </button>
  )
}

export default function App() {
  const [tab, setTab] = useState('dashboard')
  const [selected, setSelected] = useState([])
  const [settings, setSettings] = useState(null)
  const [bootError, setBootError] = useState(null)
  const [analysis, setAnalysis] = useState({ loading: false, data: null, error: null })
  const [focus, setFocus] = useState(null)
  const [reload, setReload] = useState(0)
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState(null)
  const [probing, setProbing] = useState(false)
  const [exporting, setExporting] = useState(null)
  const [exportError, setExportError] = useState(null)
  const ready = settings !== null
  const persisted = useRef(false)

  // initial load of persisted selection + settings
  useEffect(() => {
    Promise.all([api.getSelection(), api.getSettings()])
      .then(([sel, set]) => {
        setSelected(sel.funds)
        setSettings(set)
        if (sel.funds.length) setFocus(sel.funds[0].scheme_code)
        persisted.current = true
      })
      .catch(setBootError)
  }, [])

  // health polling
  const refreshHealth = useCallback(async (probe = false) => {
    try {
      setHealth(await api.health(probe))
      setHealthError(null)
    } catch (e) {
      setHealthError(e)
    }
  }, [])
  useEffect(() => {
    refreshHealth()
    const t = setInterval(refreshHealth, 30000)
    return () => clearInterval(t)
  }, [refreshHealth])
  const probe = async () => {
    setProbing(true)
    await refreshHealth(true)
    setProbing(false)
  }

  // persist selection
  useEffect(() => {
    if (!persisted.current) return undefined
    const t = setTimeout(() => api.putSelection(selected).catch(() => {}), 300)
    return () => clearTimeout(t)
  }, [selected])

  // (re)analyse whenever the selection, settings or benchmark data change
  const codesKey = selected.map((f) => f.scheme_code).join(',')
  const settingsKey = JSON.stringify(settings)
  useEffect(() => {
    if (!ready) return undefined
    if (!codesKey) {
      setAnalysis({ loading: false, data: null, error: null })
      return undefined
    }
    const ctrl = new AbortController()
    const t = setTimeout(async () => {
      setAnalysis((a) => ({ ...a, loading: true, error: null }))
      try {
        const data = await api.analyze(codesKey.split(',').map(Number), ctrl.signal)
        setAnalysis({ loading: false, data, error: null })
        refreshHealth()
      } catch (e) {
        if (e.name === 'AbortError') return
        setAnalysis((a) => ({ ...a, loading: false, error: e }))
        refreshHealth()
      }
    }, 400)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [ready, codesKey, settingsKey, reload, refreshHealth])

  const addFund = (f) => {
    setSelected((s) => (s.length >= MAX_FUNDS || s.some((x) => x.scheme_code === f.scheme_code) ? s : [...s, f]))
    setFocus((cur) => cur ?? f.scheme_code)
  }
  const removeFund = (code) => {
    setSelected((s) => s.filter((x) => x.scheme_code !== code))
    setFocus((cur) => (cur === code ? null : cur))
  }

  // rows in selection order (only rows that match the current selection)
  const rows = useMemo(() => {
    if (!analysis.data) return []
    const byCode = Object.fromEntries(analysis.data.results.map((r) => [r.scheme_code, r]))
    return selected.map((f) => byCode[f.scheme_code]).filter(Boolean)
  }, [analysis.data, selected])
  const focusRow = rows.find((r) => r.scheme_code === focus) || rows.find((r) => !r.error) || null
  const failed = rows.filter((r) => r.error)
  const allUnreachable = failed.length > 0 && failed.every((r) => r.error.code === 'PROVIDER_UNREACHABLE')

  async function doExport(format) {
    setExporting(format)
    setExportError(null)
    try {
      const { blob, filename } = await api.exportFile(selected.map((f) => f.scheme_code), format)
      downloadBlob(blob, filename)
    } catch (e) {
      setExportError(e)
    } finally {
      setExporting(null)
    }
  }

  if (bootError) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <Banner kind="error" title="The app could not start">
          {bootError.message}
        </Banner>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-12">
      <header className="flex flex-wrap items-center justify-between gap-3 py-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Indian Mutual Fund Analyzer</h1>
          <p className="text-xs text-slate-500">NAV data via mfapi.in · computed locally · benchmark TRI from your CSV imports</p>
        </div>
        <HealthPill health={health} error={healthError} onProbe={probe} probing={probing} />
      </header>

      <nav className="mb-5 flex gap-1 border-b border-slate-200" aria-label="Sections">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === k ? 'border-sky-600 text-sky-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>
            {label}
          </button>
        ))}
      </nav>

      {!ready && <Spinner label="Loading saved funds and settings…" />}

      {ready && tab === 'dashboard' && (
        <div className="space-y-5">
          <Card title="Find and add funds">
            <FundSearch selectedCodes={selected.map((f) => f.scheme_code)} max={MAX_FUNDS} onAdd={addFund} />
            {selected.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {selected.map((f) => (
                  <span key={f.scheme_code} className="inline-flex max-w-full items-center gap-2 rounded-full border border-slate-200 bg-slate-50 py-1 pl-3 pr-2 text-xs">
                    <span className="truncate" title={f.scheme_name}>{f.scheme_name}</span>
                    <span className="num text-slate-400">{f.scheme_code}</span>
                    <button onClick={() => removeFund(f.scheme_code)} className="text-slate-400 hover:text-rose-700" aria-label={`Remove ${f.scheme_name}`}>×</button>
                  </span>
                ))}
              </div>
            )}
          </Card>

          {analysis.error && (
            <Banner kind="error" title="Analysis failed">
              {analysis.error.message}
            </Banner>
          )}
          {allUnreachable && (
            <Banner kind="error" title="The data provider could not be reached">
              No NAV data could be loaded and nothing is cached for these funds yet. Check your internet connection / firewall / proxy and try again — no numbers are shown rather than guessed ones.
            </Banner>
          )}
          {!allUnreachable && failed.length > 0 && (
            <Banner kind="warn" title={`${failed.length} fund(s) could not be analysed`}>
              See the error text in their table rows; the remaining funds are unaffected.
            </Banner>
          )}

          {selected.length > 0 && (
            <Card
              title="Comparison"
              right={
                <div className="flex items-center gap-2">
                  {analysis.loading && <Spinner label="Calculating…" />}
                  {analysis.data && (
                    <span className="text-xs text-slate-500">
                      Generated {new Date(analysis.data.generated_at).toLocaleString()} · RF {analysis.data.settings.rf_annual_pct}% · MAR {analysis.data.settings.mar_annual_pct}% · {analysis.data.settings.window_months}m window
                    </span>
                  )}
                  <button onClick={() => doExport('csv')} disabled={!!exporting || rows.length === 0} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50">
                    {exporting === 'csv' ? 'Exporting…' : 'Export CSV'}
                  </button>
                  <button onClick={() => doExport('xlsx')} disabled={!!exporting || rows.length === 0} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50">
                    {exporting === 'xlsx' ? 'Exporting…' : 'Export Excel'}
                  </button>
                </div>
              }
            >
              {exportError && (
                <div className="mb-3">
                  <Banner kind="error" title="Export failed" onClose={() => setExportError(null)}>{exportError.message}</Banner>
                </div>
              )}
              {rows.length === 0 && analysis.loading ? (
                <Spinner label="Loading NAV history for the selected funds…" />
              ) : (
                <ComparisonTable rows={rows} focus={focusRow?.scheme_code} onFocus={setFocus} onRemove={removeFund} loading={analysis.loading} />
              )}
            </Card>
          )}

          {selected.length === 0 && (
            <Banner kind="info" title="Get started">
              Search for a scheme above and add it. Metrics are calculated from real NAV history as soon as a fund is added. Add up to {MAX_FUNDS} funds to compare them side by side.
            </Banner>
          )}

          {focusRow && <FundDetail row={focusRow} />}
          {rows.length > 0 && <Charts rows={rows} focus={focusRow?.scheme_code} />}
        </div>
      )}

      {ready && tab === 'benchmarks' && <BenchmarksPanel rows={rows} selected={selected} onChanged={() => setReload((n) => n + 1)} />}
      {ready && tab === 'settings' && <SettingsPanel settings={settings} onSaved={setSettings} />}
      {tab === 'methodology' && <MethodologyPanel />}

      <footer className="mt-10 border-t border-slate-200 pt-4 text-xs text-slate-500">
        For information and analysis only — not investment advice. Ratios are backward-looking and sensitive to the window, benchmark and risk-free rate; no single ratio shows that a fund is good or bad. Past performance does not predict future results.
      </footer>
    </div>
  )
}
