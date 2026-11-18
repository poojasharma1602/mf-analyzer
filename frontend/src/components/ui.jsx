import React from 'react'

export function Card({ title, right, children, className = '' }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Banner({ kind = 'error', title, children, onClose }) {
  const styles = {
    error: 'border-rose-200 bg-rose-50 text-rose-900',
    warn: 'border-amber-200 bg-amber-50 text-amber-900',
    info: 'border-sky-200 bg-sky-50 text-sky-900',
    ok: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  }[kind]
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${styles}`}>
      <div className="flex-1">
        {title && <div className="font-semibold">{title}</div>}
        <div>{children}</div>
      </div>
      {onClose && (
        <button onClick={onClose} className="text-lg leading-none opacity-60 hover:opacity-100" aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  )
}

export function Badge({ children, tone = 'slate', title }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-emerald-100 text-emerald-800',
    amber: 'bg-amber-100 text-amber-800',
    blue: 'bg-sky-100 text-sky-800',
  }
  return (
    <span title={title} className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function OptionBadges({ option, plan }) {
  return (
    <>
      {option === 'growth' && <Badge tone="green" title="Inferred from the scheme name">Growth</Badge>}
      {option === 'idcw' && <Badge tone="amber" title="NAV falls on payouts; returns understated">IDCW</Badge>}
      {option === 'unknown' && <Badge tone="slate" title="Could not infer option from name">Option?</Badge>}
      {plan === 'direct' && <Badge tone="blue">Direct</Badge>}
      {plan === 'regular' && <Badge>Regular</Badge>}
    </>
  )
}

export function Spinner({ label }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
      {label}
    </span>
  )
}
