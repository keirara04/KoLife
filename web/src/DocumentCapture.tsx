import { useState } from 'react'

// Mirrors DocumentOut in api/app/routes/documents.py (hand-written until openapi-typescript is added).
type Doc = { id: string; status: 'pending' | 'confirmed'; counts: Record<string, number>; payload_hash: string }

const LABELS: Record<string, string> = {
  ARC: 'registration number',
  RRN: 'resident number',
  PASSPORT: 'passport number',
  MYKAD: 'MyKad number',
  PHONE: 'phone number',
  face: 'face',
  'QR code': 'QR code',
  barcode: 'barcode',
  signature: 'signature',
  'seal stamp': 'seal',
}

function summary(counts: Record<string, number>): string {
  const parts = Object.entries(counts).map(([k, n]) => `${n} ${LABELS[k] ?? k}${n > 1 ? 's' : ''}`)
  return parts.length ? `Blacked out: ${parts.join(', ')}.` : 'No ID numbers or faces found.'
}

async function errorText(r: Response): Promise<string> {
  try {
    return ((await r.json()) as { detail?: string }).detail ?? `Error ${r.status}`
  } catch {
    return `Error ${r.status}`
  }
}

export default function DocumentCapture() {
  const [doc, setDoc] = useState<Doc | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function upload(file: File) {
    setBusy(true)
    setError('')
    try {
      const r = await fetch('/api/documents', { method: 'POST', body: file, headers: { 'Content-Type': file.type } })
      if (!r.ok) throw new Error(await errorText(r))
      setDoc((await r.json()) as Doc)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!doc) return
    const r = await fetch(`/api/documents/${doc.id}/confirm`, { method: 'POST' })
    if (r.ok) setDoc((await r.json()) as Doc)
    else setError(await errorText(r))
  }

  async function retake() {
    if (doc) await fetch(`/api/documents/${doc.id}`, { method: 'DELETE' })
    setDoc(null)
    setError('')
  }

  if (!doc) {
    return (
      <section className="mt-8">
        <label className="block w-full cursor-pointer rounded-xl bg-slate-900 px-4 py-4 text-center text-lg font-semibold text-white has-disabled:opacity-60">
          {busy ? 'Hiding your ID numbers…' : 'Snap a letter or bill'}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="sr-only"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) void upload(f)
            }}
          />
        </label>
        <p className="mt-2 text-sm text-slate-500">ID numbers and faces are blacked out on our server before any AI sees it.</p>
        {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      </section>
    )
  }

  return (
    <section className="mt-8">
      <img
        src={`/api/documents/${doc.id}/image`}
        alt="Your document with ID numbers and faces blacked out"
        className="w-full rounded-xl border border-slate-200"
      />
      <p className="mt-3 font-medium">{summary(doc.counts)}</p>
      {doc.status === 'pending' ? (
        <>
          <p className="mt-1 text-sm text-slate-600">
            Check nothing private is still visible. Only this redacted image is sent to Meta AI (USA).
          </p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button onClick={() => void retake()} className="rounded-xl border border-slate-300 px-4 py-3 font-semibold">
              Retake
            </button>
            <button onClick={() => void confirm()} className="rounded-xl bg-slate-900 px-4 py-3 font-semibold text-white">
              Looks safe
            </button>
          </div>
        </>
      ) : (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-green-700">Confirmed. Ready to explain.</p>
          <button onClick={() => void retake()} className="text-sm underline">New document</button>
        </div>
      )}
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    </section>
  )
}
