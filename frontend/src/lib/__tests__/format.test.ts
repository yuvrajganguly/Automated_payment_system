import { describe, expect, it } from 'vitest'
import { integer, money, moneyWhole, rupees } from '../format'

describe('format (en-IN grouping regardless of browser locale)', () => {
  it('groups lakhs', () => {
    expect(money(125000)).toBe('1,25,000.00')
    expect(rupees(1250.5)).toBe('₹1,250.50')
    expect(moneyWhole(12345678)).toBe('1,23,45,678')
    expect(integer(7)).toBe('7')
  })
  it('treats null/undefined as zero', () => {
    expect(money(null)).toBe('0.00')
    expect(money(undefined)).toBe('0.00')
  })
})
