import React, { useMemo, useState } from 'react'
import { METRICS, METRIC_BY_KEY, fmt, signClass } from '../format.js'
import { OptionBadges } from './ui.jsx'

const TABLE_METRICS = ['cagr_3y', 'sharpe', 'sortino', 'jensen_alpha', 'beta', 'information_ratio', 'volatility', 'max_drawdown']

function sortValue(row, key) {
  if (row.error) return null
  if (key === 'name') return row.scheme_name.toLowerCase()
  if (key === 'benchmark') return (row.benchmark.name || '').toLowerCase() || null
  if (key === 'nav_as_of') return row.nav_as_of
  return row.metrics[key]?.value ?? null
}

export default function ComparisonTable({ rows, focus, onFocus, onRemove, loading }) {
  const [sort, setSort] = useState({ key: 'name', dir: 'asc' })
  const [filter, setFilter] = useState('')
  const [onlyBenchmark, setOnlyBenchmark] = useState(false)
  const [hideErrors, setHideErrors] = useState(false)

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase()
    let out = rows.filter((r) => {
      if (hideErrors && r.error) return false
      if (onlyBenchmark && (r.error || r.metrics.beta.value === null)) return false
      if (!f) return true
      const hay = `${r.scheme_name} ${r.scheme_code} ${r.benchmark?.name || ''} ${r.fund_house || ''} ${r.category || ''}`.toLowerCase()
      return hay.includes(f)
    })
    out = [...out].sort((a, b) => {
      const va = sortValue(a, sort.key)
      const vb = sortValue(b, sort.key)
      if (va === null && vb === null) return 0
      if (va === null) return 1 // N/A always last, regardless of direction
      if (vb === null) return -1
      const c = va < vb ? -1 : va > vb ? 1 : 0
      return sort.dir === 'asc' ? c : -c
    })
    return out
  }, [rows, sort, filter, onlyBenchmark, hideErrors])

  const toggle = (key) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' || key === 'benchmark' ? 'asc' : 'desc' }))
  const arrow = (key) => (sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '')

  const Th = ({ k, children, className = '', title }) => (
    <th scope="col" title={title} className={`cursor-pointer select-none whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-600 hover:text-slate-900 ${className}`} onClick={() => toggle(k)}>
      {children}
      {arrow(k)}
    </th>
  )

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name, code, benchmark, category…"
          className="min-w-[240px] flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200"
          aria-label="Filter comparison table"
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={onlyBenchmark} onChange={(e) => setOnlyBenchmark(e.target.checked)} />
          Only funds with benchmark metrics
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={hideErrors} onChange={(e) => setHideErrors(e.target.checked)} />
          Hide failed funds
        </label>
        <span className="text-sm text-slate-500">
          {shown.length} of {rows.length} shown
        </span>
      </div>

      <div className={`overflow-x-auto rounded-lg border border-slate-200 ${loading ? 'opacity-60' : ''}`}>
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <Th k="name" className="min-w-[280px]">Scheme</Th>
              <Th k="benchmark">Benchmark</Th>
              <Th k="nav_as_of">NAV date</Th>
              {TABLE_METRICS.map((k) => (
                <Th key={k} k={k} title={METRIC_BY_KEY[k].desc} className="text-right">
                  {METRIC_BY_KEY[k].label}
                </Th>
              ))}
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {shown.map((r) => {
              const active = focus === r.scheme_code
              if (r.error) {
                return (
                  <tr key={r.scheme_code} className="bg-rose-50/50">
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900">{r.scheme_name}</div>
                      <div className="num text-xs text-slate-500">Code {r.scheme_code}</div>
                    </td>
                    <td colSpan={TABLE_METRICS.length + 2} className="px-3 py-2 text-xs text-rose-800">
                      <strong>{r.error.code}:</strong> {r.error.message}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => onRemove(r.scheme_code)} className="text-xs text-slate-500 hover:text-rose-700">Remove</button>
                    </td>
                  </tr>
                )
              }
              return (
                <tr key={r.scheme_code} onClick={() => onFocus(r.scheme_code)} className={`cursor-pointer hover:bg-sky-50 ${active ? 'bg-sky-50' : ''}`}>
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-900">{r.scheme_name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                      <span className="num">Code {r.scheme_code}</span>
                      <OptionBadges option={r.option} plan={r.plan} />
                      {r.data_status.stale && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">stale cache</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {r.benchmark.name ? (
                      <>
                        <div className="text-slate-800">{r.benchmark.name}</div>
                        <div className="text-slate-500">{r.benchmark.imported ? `${r.benchmark.source} · TRI imported` : `${r.benchmark.source} · not imported`}</div>
                      </>
                    ) : (
                      <span className="text-slate-400" title="Set one in the Benchmarks tab">none mapped</span>
                    )}
                  </td>
                  <td className="num whitespace-nowrap px-3 py-2 text-slate-700">{r.nav_as_of}</td>
                  {TABLE_METRICS.map((k) => {
                    const m = r.metrics[k]
                    const def = METRIC_BY_KEY[k]
                    return (
                      <td key={k} title={m.value === null ? m.reason : def.desc} className={`num whitespace-nowrap px-3 py-2 text-right ${m.value === null ? 'text-slate-400' : signClass(m.value, def.signed)}`}>
                        {fmt(m.value, def.kind)}
                      </td>
                    )
                  })}
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        onRemove(r.scheme_code)
                      }}
                      className="text-xs text-slate-500 hover:text-rose-700"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              )
            })}
            {shown.length === 0 && (
              <tr>
                <td colSpan={TABLE_METRICS.length + 4} className="px-3 py-8 text-center text-slate-500">
                  {rows.length === 0 ? 'Search and add funds above to compare them.' : 'No funds match the current filters.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Green/red colouring shows only the <em>sign</em> of a value; it does not mean a fund is good or bad. Hover an “N/A” to see why. Click a row for details and charts. Percent columns are annualised unless noted.
      </p>
    </div>
  )
}
