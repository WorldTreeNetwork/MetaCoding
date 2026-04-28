// Tree-sitter parser cache.
//
// Loads grammar .wasm files from tree-sitter-wasms once per language and
// hands out parsers configured with that grammar. Wraps the runtime init
// dance from web-tree-sitter so callers see one async makeParser().

import { readFileSync } from "node:fs";
import { join } from "node:path";

import Parser from "web-tree-sitter";

export type TsParser = Parser;
export type TsLanguage = Parser.Language;

let initialized = false;
const languages = new Map<string, TsLanguage>();

async function init(): Promise<void> {
  if (initialized) return;
  await Parser.init();
  initialized = true;
}

export async function loadLanguage(grammarName: string): Promise<TsLanguage> {
  await init();
  const cached = languages.get(grammarName);
  if (cached) return cached;
  const path = join(
    "node_modules",
    "tree-sitter-wasms",
    "out",
    `tree-sitter-${grammarName}.wasm`,
  );
  const bytes = readFileSync(path);
  const lang = await Parser.Language.load(bytes);
  languages.set(grammarName, lang);
  return lang;
}

export async function makeParser(grammarName: string): Promise<TsParser> {
  const lang = await loadLanguage(grammarName);
  const parser = new Parser();
  parser.setLanguage(lang);
  return parser;
}
