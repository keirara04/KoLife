import { useEffect, useState } from 'react'

export default function App() {
  const [health, setHealth] = useState('checking…')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d: { status: string }) => setHealth(d.status))
      .catch(() => setHealth('unreachable'))
  }, [])

  return (
    <main className="mx-auto max-w-md p-6">
      <h1 className="text-3xl font-bold">KoLife</h1>
      <p className="mt-2 text-slate-600">Your admin calendar, before the letter arrives.</p>
      <p className="mt-6 text-sm">API: {health}</p>
    </main>
  )
}
