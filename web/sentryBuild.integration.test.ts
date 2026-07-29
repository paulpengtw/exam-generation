import { spawnSync } from 'node:child_process'
import {
  mkdtempSync,
  readdirSync,
  rmSync,
  type Dirent,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from 'vitest'

const webDirectory = process.cwd()
const viteEntryPoint = join(webDirectory, 'node_modules/vite/bin/vite.js')

function findSourceMaps(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(
    (entry: Dirent) => {
      const path = join(directory, entry.name)

      if (entry.isDirectory()) {
        return findSourceMaps(path)
      }

      return entry.isFile() && entry.name.endsWith('.map') ? [path] : []
    },
  )
}

test(
  'a production build without Sentry credentials succeeds without emitting source maps',
  () => {
    const outDir = mkdtempSync(join(tmpdir(), 'exam-generation-web-build-'))
    const env = Object.fromEntries(
      Object.entries(process.env).filter(([name]) => !name.startsWith('SENTRY_')),
    )

    try {
      const build = spawnSync(
        process.execPath,
        [viteEntryPoint, 'build', '--outDir', outDir],
        {
          cwd: webDirectory,
          encoding: 'utf8',
          env,
        },
      )

      expect(
        build.status,
        [
          build.error?.message,
          build.stdout,
          build.stderr,
        ]
          .filter(Boolean)
          .join('\n'),
      ).toBe(0)
      expect(findSourceMaps(outDir)).toEqual([])
    } finally {
      rmSync(outDir, { force: true, recursive: true })
    }
  },
  180_000,
)
