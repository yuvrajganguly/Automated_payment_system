import { InputHTMLAttributes, useState } from 'react'

/** A password field with a Show/Hide toggle. Pass the same props you would
 *  give an <input type="password">; `className` styles the input itself. */
export function PasswordInput({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input {...props} type={show ? 'text' : 'password'} className={className + ' pr-14'} />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        tabIndex={-1}
        aria-label={show ? 'Hide password' : 'Show password'}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-xs opacity-60 hover:opacity-100 select-none"
      >
        {show ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}
