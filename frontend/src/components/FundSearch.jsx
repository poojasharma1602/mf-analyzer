import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Banner, OptionBadges, Spinner } from './ui.jsx'

export default function FundSearch({ selectedCodes, max, onAdd }) {
  const [query, setQuery] = useState('')
  const [growthOnly, setGrowthOnly] = useState(true)
  const [state, setState] = useState({ loading: false, error: null, data: null })
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)
  const full = selectedCodes.length >= max

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setState({ loading: false, error: null, data: null })
      return undefined
    }
    const ctrl = new AbortController()
    const t = setTimeout(async () => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await api.searchSchemes(q, growthOnly, ctrl.signal)
        setState({ loading: false, error: null, data })
      } catch (e) {
        if (e.name === 'AbortError') return
        setState({ loading: false, error: e, data: null })
      }
    }, 300)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [query, growthOnly])

  useEffect(() => {
    const onDoc = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const { data, loading, error } = state
  return (
    <div ref={boxRef} className="relative">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          disabled={full}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          placeholder={full ? `Maximum of ${max} funds selected` : 'Search any scheme by name or scheme code (min. 2 characters)…'}
          className="min-w-[260px] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-200 disabled:bg-slate-100"
          aria-label="Search mutual fund schemes"
        />
        <label className="flex items-center gap-2 text-sm text-slate-600" title="IDCW/Dividend NAVs drop on payouts, so NAV-based returns are understated">
          <input type="checkbox" checked={growthOnly} onChange={(e) => setGrowthOnly(e.target.checked)} />
          Growth options only
        </label>
        <span className="text-sm text-slate-500">
          {selectedCodes.length}/{max} selected
        </span>
      </div>

      {open && query.trim().length >= 2 && (
        <div className="absolute z-20 mt-1 max-h-[420px] w-full overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          {loading && (
            <div className="p-3">
              <Spinner label="Searching schemes…" />
            </div>
          )}
          {error && (
            <div className="p-3">
              <Banner kind="error" title="Search failed">
                {error.message}
              </Banner>
            </div>
          )}
          {data && !loading && (
            <>
              {data.stale && (
                <div className="p-2">
                  <Banner kind="warn">Showing a cached scheme list — the provider could not be reached. {data.stale_reason}</Banner>
                </div>
              )}
              {data.warning && (
                <div className="p-2">
                  <Banner kind="warn">{data.warning}</Banner>
                </div>
              )}
              {data.results.length === 0 && <div className="p-3 text-sm text-slate-500">No schemes match “{query}”.</div>}
              <ul>
                {data.results.map((r) => {
                  const added = selectedCodes.includes(r.scheme_code)
                  return (
                    <li key={r.scheme_code}>
                      <button
                        type="button"
                        disabled={added || full}
                        onClick={() => {
                          onAdd({ scheme_code: r.scheme_code, scheme_name: r.scheme_name })
                        }}
                        className="flex w-full items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span>
                          <span className="block text-slate-900">{r.scheme_name}</span>
                          <span className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                            <span className="num">Code {r.scheme_code}</span>
                            <OptionBadges option={r.option} plan={r.plan} />
                          </span>
                        </span>
                        <span className="shrink-0 text-xs font-medium text-sky-700">{added ? 'Added' : '+ Add'}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
              {data.total_matches > data.results.length && (
                <div className="p-2 text-center text-xs text-slate-500">
                  Showing {data.results.length} of {data.total_matches} matches — refine your search to narrow down.
                </div>
              )}
              <div className="border-t border-slate-100 p-2 text-center text-xs text-slate-400">
                Scheme list as of {data.schemes_as_of ? new Date(data.schemes_as_of).toLocaleString() : 'n/a'}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
