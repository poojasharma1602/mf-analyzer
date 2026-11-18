import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Banner, Card, Spinner } from './ui.jsx'

export default function MethodologyPanel() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    api.methodology().then(setData).catch(setError)
  }, [])
  if (error) return <Banner kind="error">{error.message}</Banner>
  if (!data) return <Spinner label="Loading…" />
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {data.sections.map((s) => (
        <Card key={s.title} title={s.title}>
          <div className="space-y-2 text-sm leading-relaxed text-slate-700">
            {s.body.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        </Card>
      ))}
    </div>
  )
}
