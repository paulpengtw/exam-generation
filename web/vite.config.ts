import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { sentryVitePlugin } from '@sentry/vite-plugin'
import { fakeBackend } from './prototypes/720-action-feedback/fakeBackend'
import { resolveSentryUpload } from './sentryUpload'

// https://vite.dev/config/
const prototype720 = process.env.PROTO_720 === "1"
const sentryUpload = resolveSentryUpload(process.env)

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  define: { "import.meta.env.VITE_PROTO_720": JSON.stringify(prototype720 ? "1" : "0") },
  plugins: [
    ...(prototype720 ? [fakeBackend()] : []),
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
    proxy: prototype720 ? undefined : {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
