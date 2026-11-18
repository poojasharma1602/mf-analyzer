import React, { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { METRICS, METRIC_BY_KEY, PALETTE, fmt } from '../format.js'
import { Card } from './ui.jsx'

const shortName = (n) => (n.length > 34 ? n.slice(0, 33) + '…' : n)

export default function Charts({ rows, focus }) {
  const ok = rows.filter((r) => !r.error)
  const [metricKey, setMetricKey] = useState('sharpe')
  const metric = METRIC_BY_KEY[metricKey]

  const colorOf = useMemo(() => {
    const map = {}
    rows.forEach((r, i) => (map[r.scheme_code] = PALETTE[i % PALETTE.length]))
    return map
  }, [rows])

  const barData = useMemo(
    () =>
      ok
        .map((r) => ({ name: shortName(r.scheme_name), code: r.scheme_code, value: r.metrics[metricKey].value }))
        .filter((d) => d.value !== null)
        .sort((a, b) => b.value - a.value)
        .map((d) => ({ ...d, plot: metric.kind === 'pct' ? d.value * 100 : d.value })),
    [ok, metricKey, metric],
  )
  const naCount = ok.length - barData.length

  const growth = useMemo(() => {
    const months = new Set()
    ok.forEach((r) => r.chart.forEach(([m]) => months.add(m)))
    const sorted = [...months].sort()
    const byCode = Object.fromEntries(ok.map((r) => [r.scheme_code, Object.fromEntries(r.chart)]))
    return sorted.map((m) => {
      const row = { month: m }
      ok.forEach((r) => {
        if (byCode[r.scheme_code][m] !== undefined) row[r.scheme_code] = byCode[r.scheme_code][m]
      })
      return row
    })
  }, [ok])

  const scatter = useMemo(
    () =>
      ok
        .filter((r) => r.metrics.volatility.value !== null && r.metrics.cagr_3y.value !== null)
        .map((r) => ({ x: r.metrics.volatility.value * 100, y: r.metrics.cagr_3y.value * 100, name: r.scheme_name, code: r.scheme_code })),
    [ok],
  )

  if (ok.length === 0) return null
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card
        title="Metric across funds"
        right={
          <select value={metricKey} onChange={(e) => setMetricKey(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" aria-label="Metric to chart">
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        }
      >
        {barData.length === 0 ? (
          <p className="text-sm text-slate-500">No fund has a value for {metric.label} (see N/A reasons in the table).</p>
        ) : (
          <div style={{ height: Math.max(220, barData.length * 26 + 40) }}>
            <ResponsiveContainer>
              <BarChart data={barData} layout="vertical" margin={{ left: 10, right: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => (metric.kind === 'pct' ? `${v.toFixed(0)}%` : v.toFixed(1))} />
                <YAxis type="category" dataKey="name" width={210} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => (metric.kind === 'pct' ? `${v.toFixed(2)}%` : v.toFixed(3))} labelFormatter={(l) => l} />
                <Bar dataKey="plot" name={metric.label} fill="#2563eb" radius={[0, 3, 3, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {naCount > 0 && <p className="mt-2 text-xs text-slate-500">{naCount} fund(s) omitted because the metric is N/A.</p>}
      </Card>

      <Card title="Risk vs return (volatility vs 3Y CAGR)">
        {scatter.length === 0 ? (
          <p className="text-sm text-slate-500">Needs both volatility and 3Y CAGR (at least 3 years of history).</p>
        ) : (
          <div style={{ height: 320 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ left: 0, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" dataKey="x" name="Volatility" unit="%" domain={['auto', 'auto']} tickFormatter={(v) => v.toFixed(0)} label={{ value: 'Annualised volatility (%)', position: 'insideBottom', offset: -2, fontSize: 11 }} />
                <YAxis type="number" dataKey="y" name="3Y CAGR" unit="%" domain={['auto', 'auto']} tickFormatter={(v) => v.toFixed(0)} />
                <ZAxis range={[70, 70]} />
                <Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ payload }) => (payload && payload[0] ? (
                  <div className="rounded border border-slate-200 bg-white p-2 text-xs shadow">
                    <div className="font-medium">{payload[0].payload.name}</div>
                    <div>Volatility {payload[0].payload.x.toFixed(2)}% · CAGR {payload[0].payload.y.toFixed(2)}%</div>
                  </div>
                ) : null)} />
                <Scatter data={scatter} isAnimationActive={false} shape={(p) => <circle cx={p.cx} cy={p.cy} r={p.payload.code === focus ? 8 : 5} fill={colorOf[p.payload.code]} stroke="#fff" strokeWidth={1.5} />} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="Growth of 100 over the analysis window (month-end NAV)" className="xl:col-span-2">
        <div style={{ height: 340 }}>
          <ResponsiveContainer>
            <LineChart data={growth} margin={{ left: 0, right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} minTickGap={30} />
              <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }} />
              <Tooltip itemSorter={(i) => -i.value} formatter={(v, n) => [Number(v).toFixed(1), shortName(ok.find((r) => String(r.scheme_code) === String(n))?.scheme_name || n)]} />
              {ok.length <= 6 && <Legend formatter={(n) => shortName(ok.find((r) => String(r.scheme_code) === String(n))?.scheme_name || n)} />}
              {ok.map((r) => (
                <Line key={r.scheme_code} type="monotone" dataKey={String(r.scheme_code)} stroke={colorOf[r.scheme_code]} strokeWidth={r.scheme_code === focus ? 3 : 1.3} strokeOpacity={focus && r.scheme_code !== focus ? 0.55 : 1} dot={false} connectNulls isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-slate-500">Each line is rebased to 100 at the start of its own window. NAV-based: IDCW options exclude distributions. Past performance does not predict future results.</p>
      </Card>
    </div>
  )
}
