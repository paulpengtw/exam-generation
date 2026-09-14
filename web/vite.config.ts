import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { sentryVitePlugin } from '@sentry/vite-plugin'
import { resolveSentryUpload } from './sentryUpload'
import { buildIdentityPlugin } from './buildIdentity'

// https://vite.dev/config/
const sentryUpload = resolveSentryUpload(process.env)

export default defineConfig({
  plugins: [
    buildIdentityPlugin(),
    react(),
    tailwindcss(),
    // Issue #233: upload maps only when the release matches the SDK-stamped
    // VITE_SENTRY_RELEASE, then delete them from dist after upload.
    ...(sentryUpload.enabled
      ? [
          sentryVitePlugin({
            org: sentryUpload.org,
            project: sentryUpload.project,
            authToken: sentryUpload.authToken,
            telemetry: false,
            release: { name: sentryUpload.release },
            sourcemaps: {
              filesToDeleteAfterUpload: [
                sentryUpload.filesToDeleteAfterUpload,
              ],
            },
          }),
        ]
      : []),
  ],
  build: {
    sourcemap: sentryUpload.enabled ? sentryUpload.sourcemap : false,
  },
  server: {
    proxy: {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
