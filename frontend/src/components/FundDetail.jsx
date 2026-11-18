import React from 'react'
import { METRICS, fmt, signClass } from '../format.js'
import { Banner, Card, OptionBadges } from './ui.jsx'

function periodText(row, key) {
  const p = row.periods[key]
  if (!p) return null
  return `${p.n_obs} monthly obs · ${p.start ?? '—'} → ${p.end}`
}

export default function FundDetail({ row }) {
  if (!row) return null
  if (row.error) {
    return (
      <Card title={row.scheme_name}>
        <Banner kind="error" title={row.error.code}>{row.error.message}</Banner>
      </Card>
    )
  }
  const benchRelative = ['jensen_alpha', 'beta', 'information_ratio', 'tracking_error', 'active_return']
  return (
    <Card
      title="Fund detail"
      right={<span className="text-xs text-slate-500">NAV as of <strong className="num">{row.nav_as_of}</strong> · latest NAV <strong className="num">{row.latest_nav}</strong></span>}
    >
      <div className="mb-3">
        <h3 className="text-base font-semibold text-slate-900">{row.scheme_name}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="num">Code {row.scheme_code}</span>
          {row.fund_house && <span>{row.fund_house}</span>}
          {row.category && <span>· {row.category}</span>}
          <OptionBadges option={row.option} plan={row.plan} />
          <span>· {row.nav_points.toLocaleString()} NAV points since {row.first_nav_date}</span>
        </div>
        <div className="mt-1 text-xs text-slate-500">
          Benchmark: {row.benchmark.name ? <strong className="text-slate-700">{row.benchmark.name}</strong> : 'none mapped'}
          {row.benchmark.name && ` (${row.benchmark.source}${row.benchmark.imported ? `, TRI ${row.benchmark.first_date} → ${row.benchmark.last_date}` : ', TRI not imported'})`}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {METRICS.map((m) => {
          const v = row.metrics[m.key]
          const per = m.key === 'cagr_3y' ? (row.periods.cagr ? `${row.periods.cagr.start} → ${row.periods.cagr.end}` : null) : benchRelative.includes(m.key) ? periodText(row, 'matched') : periodText(row, 'fund')
          return (
            <div key={m.key} className="rounded-lg border border-slate-200 p-3" title={m.desc}>
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{m.label}</div>
              <div className={`num mt-1 text-2xl font-semibold ${v.value === null ? 'text-slate-300' : signClass(v.value, m.signed)}`}>{fmt(v.value, m.kind)}</div>
              <div className="mt-1 min-h-[2.2rem] text-[11px] leading-snug text-slate-500">{v.value === null ? v.reason : per}</div>
            </div>
          )
        })}
      </div>

      <div className="mt-4 space-y-2">
        {row.data_status.stale && <Banner kind="warn" title="Stale cached data">{row.data_status.stale_reason}</Banner>}
        {row.warnings.filter((w) => !w.startsWith('Using cached data')).map((w, i) => (
          <Banner key={i} kind="warn">{w}</Banner>
        ))}
        <p className="text-xs text-slate-500">
          Data fetched {new Date(row.data_status.fetched_at).toLocaleString()} ({row.data_status.from_cache ? 'local cache' : 'live from provider'}). Ratios cover the window ending at the last complete calendar month; CAGR ends at the NAV as-of date.
        </p>
      </div>
    </Card>
  )
}
