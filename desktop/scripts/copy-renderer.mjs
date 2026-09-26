import { cp, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const source = resolve("src/renderer");
const destination = resolve("dist/renderer");
await mkdir(dirname(destination), { recursive: true });
await cp(source, destination, { recursive: true });
