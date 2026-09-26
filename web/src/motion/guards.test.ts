import { readdirSync, readFileSync, statSync } from "node:fs";
import { relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(__dirname, "..");

function sourceFiles(): string[] {
  return readdirSync(sourceRoot, { recursive: true, withFileTypes: false })
    .filter((file): file is string => typeof file === "string")
    .filter((file) => /\.(ts|tsx|css)$/.test(file))
    .filter((file) => !/\.(test|spec)\.(ts|tsx)$/.test(file))
    .map((file) => resolve(sourceRoot, file))
    .filter((file) => statSync(file).isFile());
}

function sourceEntries() {
  return sourceFiles().map((file) => ({
    file,
    relativePath: relative(sourceRoot, file),
    source: readFileSync(file, "utf8"),
  }));
}

describe("motion source guards", () => {
  it("keeps transition utilities paired with a motion token", () => {
    const unpaired: string[] = [];

    for (const { file, source } of sourceEntries()) {
      if (!/\.(ts|tsx)$/.test(file)) continue;

      const stringLiterals = [...source.matchAll(/(["'`])(?:\\[\s\S]|(?!\1)[\s\S])*?\1/g)];
      for (const match of stringLiterals) {
        const classList = match[0].slice(1, -1);
        if (!/(^|\s)transition(?:-[a-z]+)?(\s|$)/.test(classList)) continue;
        if (
          !/(^|\s)(duration-(?:quick|standard|loop-shimmer|loop-spinner)|ease-(?:signature|exit|loop))(\s|$)/.test(
            classList,
          )
        ) {
          unpaired.push(`${relative(sourceRoot, file)}: ${classList}`);
        }
      }
    }

    expect(unpaired).toEqual([]);
  });

  it("does not use literal duration utilities", () => {
    const matches = sourceEntries().flatMap(({ relativePath, source }) =>
      [...source.matchAll(/\bduration-\d+\b/g)].map(
        (match) => `${relativePath}: ${match[0]}`,
      ),
    );

    expect(matches).toEqual([]);
  });

  it("keeps keyframes inside the motion directory", () => {
    const matches = sourceEntries().flatMap(({ relativePath, source }) =>
      /@keyframes\b/.test(source) && !relativePath.startsWith("motion/")
        ? [relativePath]
        : [],
    );

    expect(matches).toEqual([]);
  });

  it("does not use animate-spin", () => {
    const matches = sourceEntries().flatMap(({ relativePath, source }) =>
      /(?:^|[\s.'"`])animate-spin(?:$|[\s'"`])/.test(source)
        ? [relativePath]
        : [],
    );

    expect(matches).toEqual([]);
  });
});
