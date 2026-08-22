/**
 * EvidenceStamp — the product's signature UI element.
 *
 * Evidence is the product, not a compliance artifact. This component renders
 * only provenance actually returned by the API. If source is missing, it
 * renders nothing rather than inventing a provider or evidence state.
 */

interface EvidenceStampProps {
  source?: string
  provider?: string
  observedAt?: string | null
  className?: string
}

function formatObservedAt(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString().slice(11, 19) + 'Z'
}

export default function EvidenceStamp({ source, provider, observedAt, className }: EvidenceStampProps) {
  if (!source) return null

  const time = formatObservedAt(observedAt)
  const normalized = source.toLowerCase()
  const label = normalized === 'live' ? (provider || 'live') : normalized === 'demo' ? 'demo' : source

  return (
    <span
      className={`evidence-stamp ${className || ''}`}
      data-source={normalized}
      title={`Source: ${label}${time ? ` · observed ${time}` : ''}`}
      aria-label={`Evidence source ${label}${time ? `, observed ${time}` : ''}`}
    >
      <span className="evidence-dot" aria-hidden="true" />
      {label}
      {time && <>&nbsp;·&nbsp;{time}</>}
    </span>
  )
}
