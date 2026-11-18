// All requests go to the local FastAPI backend only (never to mfapi.in directly).
const BASE = (import.meta.env.VITE_API_BASE || '') + '/api'

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(BASE + path, options)
  } catch {
    throw new ApiError(
      'Cannot reach the local backend. Make sure the backend window opened by start.bat is still running.',
      'BACKEND_OFFLINE',
      0,
    )
  }
  if (!res.ok) {
    let message = `Request failed (HTTP ${res.status})`
    let code
    try {
      const j = await res.json()
      if (j.error) {
        message = j.error.message
        code = j.error.code
      } else if (j.detail) {
        message = typeof j.detail === 'string' ? j.detail : j.detail.map((d) => d.msg).join('; ')
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, code, res.status)
  }
  return res
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
const put = (body) => ({ ...json(body), method: 'PUT' })

export const api = {
  health: async (probe = false) => (await request(`/health${probe ? '?probe=true' : ''}`)).json(),
  searchSchemes: async (search, growthOnly, signal) =>
    (
      await request(
        `/schemes?search=${encodeURIComponent(search)}&limit=40&growth_only=${growthOnly}`,
        { signal },
      )
    ).json(),
  getSelection: async () => (await request('/selection')).json(),
  putSelection: async (funds) => (await request('/selection', put({ funds }))).json(),
  getSettings: async () => (await request('/settings')).json(),
  putSettings: async (s) => (await request('/settings', put(s))).json(),
  analyze: async (codes, signal) =>
    (await request('/analyze', { ...json({ scheme_codes: codes }), signal })).json(),
  getBenchmarks: async () => (await request('/benchmarks')).json(),
  importBenchmark: async (name, file) => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('file', file)
    return (await request('/benchmarks/import', { method: 'POST', body: fd })).json()
  },
  deleteBenchmark: async (name) =>
    (await request(`/benchmarks/${encodeURIComponent(name)}`, { method: 'DELETE' })).json(),
  setOverride: async (schemeCode, benchmarkName) =>
    (await request('/benchmarks/override', put({ scheme_code: schemeCode, benchmark_name: benchmarkName }))).json(),
  setDefaultBenchmark: async (name) =>
    (await request('/benchmarks/default', put({ benchmark_name: name }))).json(),
  methodology: async () => (await request('/methodology')).json(),
  exportFile: async (codes, format) => {
    const res = await request(`/export?format=${format}`, json({ scheme_codes: codes }))
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const m = /filename="([^"]+)"/.exec(cd)
    return { blob, filename: m ? m[1] : `mf_comparison.${format}` }
  },
}
