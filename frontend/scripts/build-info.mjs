// Records a fingerprint of the sources the committed bundle was built from
// (web/dist/build-info.json). tests/unit/test_frontend.py recomputes it, so
// a change to frontend/ without a rebuild fails the test suite.
// Line endings are normalised, so a Windows checkout gives the same answer.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const files = ["package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"];
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? walk(path) : [relative(root, path).split("\\").join("/")];
});
files.push(...walk(join(root, "src")).filter((f) => !/\.test\.tsx?$/.test(f)));
files.sort();
const hash = createHash("sha256");
for (const f of files) {
  hash.update(f + "\0");
  hash.update(readFileSync(join(root, f), "utf8").replace(/\r\n/g, "\n") + "\0");
}
const info = { sources: hash.digest("hex"), files: files.length, built: new Date().toISOString().slice(0, 10) };
writeFileSync(join(root, "../web/dist/build-info.json"), JSON.stringify(info, null, 1) + "\n");
console.log(`build-info: ${info.files} files, ${info.sources.slice(0, 12)}`);
