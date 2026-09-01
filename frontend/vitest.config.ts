import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    environment: 'node',
    // Pin the timezone the operators use so date tests fail the way production would.
    env: { TZ: 'Asia/Kolkata' },
  },
})
