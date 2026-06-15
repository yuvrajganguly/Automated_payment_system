export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-600">
      <div className="w-4 h-4 border-2 border-slate-300 border-t-brand rounded-full animate-spin" />
      {label && <span>{label}</span>}
    </div>
  )
}
