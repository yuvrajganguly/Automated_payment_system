import { InputHTMLAttributes, useState } from 'react'

/** A password field with a Show/Hide toggle. Pass the same props you would
 *  give an <input type="password">; `className` styles the input itself.
 *  The toggle is a full-height button on the right with a proper hit area,
 *  and it never steals focus from the field (mousedown is cancelled). */
export function PasswordInput({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input {...props} type={show ? 'text' : 'password'} className={className + ' !pr-16'} />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setShow((s) => !s)}
        tabIndex={-1}
        aria-pressed={show}
        aria-label={show ? 'Hide password' : 'Show password'}
        title={show ? 'Hide password' : 'Show password'}
        className="absolute inset-y-0 right-0 z-10 flex items-center gap-1 px-3 text-xs font-medium
                   opacity-80 hover:opacity-100 cursor-pointer select-none"
      >
        {show ? <EyeOff /> : <Eye />}
        {show ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}

function Eye() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeOff() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-11-7-11-7a18.6 18.6 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}
