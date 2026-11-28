import { describe, expect, it } from 'vitest'
import { companyChoices, companyLabel, parseCompanyChoice } from '../companyTypes'

describe('Zomato id types', () => {
  it('lists Zomato once per type and leaves other companies alone', () => {
    expect(companyChoices(['Jiffy', 'Zomato'])).toEqual(['Jiffy', 'Zomato · Flat', 'Zomato · Salary', 'Zomato · Commission'])
  })
  it('round-trips a choice to company + payment_model', () => {
    expect(parseCompanyChoice('Zomato · Salary')).toEqual({ company: 'Zomato', payment_model: 'salary' })
    expect(parseCompanyChoice('Jiffy')).toEqual({ company: 'Jiffy' })
  })
  it('labels ids', () => {
    expect(companyLabel('Zomato', 'per_order')).toBe('Zomato · Flat')
    expect(companyLabel('Zomato', null)).toBe('Zomato · type not set')
    expect(companyLabel('Myntra', 'salary')).toBe('Myntra')
  })
})
