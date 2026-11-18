import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Banner, Card } from './ui.jsx'

const FIELDS = [
  { key: 'rf_annual_pct', label: 'Risk-free rate (% p.a.)', step: 0.05, help: 'Used for Sharpe and Jensen\'s alpha. Placeholder default — set to the rate you consider appropriate (e.g. a T-bill yield). It is not fetched automatically.' },
  { key: 'mar_annual_pct', label: 'Minimum acceptable return (% p.a.)', step: 0.05, help: 'Threshold for the Sortino ratio\'s downside deviation.' },
  { key: 'window_months', label: 'Analysis window (months)', step: 1, help: 'Most recent N monthly returns used for ratios (12–120).' },
  { key: 'min_obs', label: 'Minimum observations', step: 1, help: 'Metrics show N/A below this many valid monthly observations (6–120, ≤ window).' },
]

export default function SettingsPanel({ settings, onSaved }) {
  const [draft, setDraft] = useState(settings)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  useEffect(() => setDraft(settings), [settings])

  async function save(e) {
    e.preventDefault()
    setError(null)
    setSaved(false)
    try {
      const payload = Object.fromEntries(FIELDS.map((f) => [f.key, Number(draft[f.key])]))
      const res = await api.putSettings(payload)
      onSaved(res)
      setSaved(true)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <Card title="Analysis settings">
      <form onSubmit={save} className="grid max-w-3xl gap-4 md:grid-cols-2">
        {FIELDS.map((f) => (
          <label key={f.key} className="text-sm">
            <span className="mb-1 block font-medium text-slate-700">{f.label}</span>
            <input type="number" step={f.step} value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} className="num w-full rounded-lg border border-slate-300 px-3 py-2" required />
            <span className="mt-1 block text-xs text-slate-500">{f.help}</span>
          </label>
        ))}
        <div className="md:col-span-2">
          <button className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700">Save and recalculate</button>
          {saved && <span className="ml-3 text-sm text-emerald-700">Saved — results are being recalculated.</span>}
        </div>
        {error && (
          <div className="md:col-span-2">
            <Banner kind="error" title="Settings not saved">{error.message}</Banner>
          </div>
        )}
      </form>
    </Card>
  )
}
