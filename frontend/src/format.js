export const METRICS = [
  { key: 'cagr_3y', label: '3Y CAGR', kind: 'pct', signed: true, desc: 'Compound annual growth over the last 3 years, from actual NAV dates.' },
  { key: 'sharpe', label: 'Sharpe', kind: 'ratio', signed: true, desc: 'Annualised excess return per unit of total volatility (monthly returns).' },
  { key: 'sortino', label: 'Sortino', kind: 'ratio', signed: true, desc: 'Annualised return above the minimum acceptable return per unit of downside deviation.' },
  { key: 'jensen_alpha', label: "Jensen's Alpha", kind: 'pct', signed: true, desc: 'Annualised CAPM alpha versus the mapped benchmark TRI. Needs an imported benchmark.' },
  { key: 'beta', label: 'Beta', kind: 'ratio', signed: false, desc: 'Sensitivity to the benchmark: covariance / benchmark variance on matched monthly returns.' },
  { key: 'information_ratio', label: 'Information Ratio', kind: 'ratio', signed: true, desc: 'Annualised active return divided by annualised tracking error versus the benchmark.' },
  { key: 'volatility', label: 'Volatility', kind: 'pct', signed: false, desc: 'Annualised standard deviation of monthly returns.' },
  { key: 'max_drawdown', label: 'Max Drawdown', kind: 'pct', signed: false, desc: 'Largest peak-to-trough fall of month-end NAV within the window.' },
  { key: 'tracking_error', label: 'Tracking Error', kind: 'pct', signed: false, desc: 'Annualised standard deviation of monthly active returns vs the benchmark.' },
  { key: 'active_return', label: 'Active Return', kind: 'pct', signed: true, desc: 'Annualised average monthly (fund minus benchmark) return.' },
]

export const METRIC_BY_KEY = Object.fromEntries(METRICS.map((m) => [m.key, m]))

export function fmt(value, kind) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A'
  if (kind === 'pct') return `${(value * 100).toFixed(2)}%`
  return value.toFixed(2)
}

export function signClass(value, signed) {
  if (!signed || value === null || value === undefined) return 'text-slate-800'
  if (value > 0) return 'text-emerald-700'
  if (value < 0) return 'text-rose-700'
  return 'text-slate-800'
}

export const PALETTE = [
  '#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#4f46e5',
  '#0d9488', '#b91c1c', '#a16207', '#9333ea', '#0369a1', '#be185d', '#4d7c0f', '#c2410c', '#3730a3', '#115e59',
]

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}
