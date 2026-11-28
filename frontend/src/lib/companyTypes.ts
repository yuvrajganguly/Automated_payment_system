/** Zomato runs three kinds of rider id, paid three ways (domain/zomato.py):
 *  Flat (per_order) = orders × rate, Salary = salary less days short +
 *  incentives, Commission = Zomato pays the rider itself.
 *
 *  Everywhere a company is shown or picked, a Zomato id reads as
 *  "Zomato · Flat" / "Zomato · Salary" / "Zomato · Commission" so the three are
 *  never confused; the server still stores company "Zomato" plus the id's
 *  payment_model. */

export const ZOMATO_TYPES: { value: string; label: string }[] = [
  { value: 'per_order', label: 'Flat' },
  { value: 'salary', label: 'Salary' },
  { value: 'commission', label: 'Commission' },
]

export const isZomato = (company: string | null | undefined) =>
  (company ?? '').trim().toLowerCase() === 'zomato'

const SEP = ' · '

/** "Zomato · Flat" for a typed Zomato id, "Zomato · type not set" for an
 *  untyped one, the bare company name for everybody else. */
export function companyLabel(company: string, paymentModel?: string | null): string {
  if (!isZomato(company)) return company
  const t = ZOMATO_TYPES.find((x) => x.value === paymentModel)
  return company + SEP + (t ? t.label : 'type not set')
}

/** A company picker's options: Zomato listed once per id type. */
export function companyChoices(companies: string[]): string[] {
  return companies.flatMap((c) => (isZomato(c) ? ZOMATO_TYPES.map((t) => c + SEP + t.label) : [c]))
}

/** Back from a picker choice to what the server takes. */
export function parseCompanyChoice(choice: string): { company: string; payment_model?: string } {
  const at = choice.lastIndexOf(SEP)
  if (at > 0) {
    const company = choice.slice(0, at)
    const t = ZOMATO_TYPES.find((x) => x.label === choice.slice(at + SEP.length))
    if (t && isZomato(company)) return { company, payment_model: t.value }
  }
  return { company: choice }
}
