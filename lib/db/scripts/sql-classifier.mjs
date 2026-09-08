import crypto from 'node:crypto';
import fs from 'node:fs';
import { splitSqlStatements } from './sql-statements.mjs';

const protectedTables = new Set(JSON.parse(fs.readFileSync(new URL('../protected-tables.json', import.meta.url))).protected);
// Pinned, reviewed SQL only. Never derive approvals from the migration being checked.
const reviewed = new Set(JSON.parse(fs.readFileSync(new URL('./reviewed-additive-sql.json', import.meta.url))).statements.map(x => x.sha256));
const hash = s => crypto.createHash('sha256').update(s).digest('hex');
const name = String.raw`(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z_0-9$]*)`;
const qualified = `${name}(?:\\s*\\.\\s*${name})?`;
const tableName = text => [...text.matchAll(new RegExp(name, 'g'))].at(-1)?.[0].replace(/^"|"$/g, '').replaceAll('""', '"').toLowerCase() || '';
const finding = (kind, table, sql, destructive = false) => ({ kind, table, destructive,
  protected: protectedTables.has(table), sql, unsafe: kind === 'UNKNOWN' });
const unknown = sql => finding('UNKNOWN', '', sql, true);

// Split action/target lists only at top-level commas. Quoted strings and names
// remain opaque. Unsupported dollar bodies and malformed syntax fail closed.
function clauses(s) {
  const parts = []; let start = 0; let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '"' || s[i] === "'") {
      const quote = s[i]; let closed = false;
      while (++i < s.length) {
        if (s[i] === quote) {
          if (s[i + 1] === quote) { i++; continue; }
          closed = true; break;
        }
      }
      if (!closed) throw new Error('Unclosed quote');
    } else if (s[i] === '(') depth++;
    else if (s[i] === ')') { if (--depth < 0) throw new Error('Unbalanced parentheses'); }
    else if (s[i] === ',' && depth === 0) { parts.push(s.slice(start, i).trim()); start = i + 1; }
  }
  if (depth) throw new Error('Unbalanced parentheses');
  parts.push(s.slice(start).trim());
  if (parts.some(p => !p)) throw new Error('Empty clause');
  return parts;
}
const primitive = '(?:text|integer|int|bigint|boolean|jsonb|date|timestamptz)';
const column = `${name}\\s+${primitive}(?:\\s+PRIMARY\\s+KEY)?(?:\\s+NOT\\s+NULL)?`;
const safeColumn = new RegExp(`^${column}$`, 'i');

function inspect(s) {
  // All reviewed declarations include their complete body and suffix.
  if (reviewed.has(hash(s))) {
    const m = s.match(new RegExp(`^CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(${qualified})`, 'i'));
    return [finding(m ? 'table_added' : 'reviewed_additive', m ? tableName(m[1]) : '', s)];
  }
  let m = s.match(/^(DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?)\s+(?:IF\s+EXISTS\s+)?([\s\S]+)$/i);
  if (m) {
    const body = m[2].replace(/\s+(?:(?:RESTART|CONTINUE)\s+IDENTITY\s*)?(?:CASCADE|RESTRICT)?\s*$/i, '').trim();
    return clauses(body).flatMap(part => {
      const target = part.match(new RegExp(`^(?:ONLY\\s+)?(${qualified})(?:\\s*\\*)?$`, 'i'));
      return target ? [finding(/^DROP/i.test(m[1]) ? 'table_dropped' : 'table_truncated', tableName(target[1]), s, true)] : [unknown(s)];
    });
  }
  m = s.match(new RegExp(`^DELETE\\s+FROM\\s+(?:ONLY\\s+)?(${qualified})(?=\\s|$|\\*)`, 'i'));
  if (m) return [finding('rows_deleted', tableName(m[1]), s, true)];
  m = s.match(new RegExp(`^ALTER\\s+TABLE\\s+(?:IF\\s+EXISTS\\s+)?(?:ONLY\\s+)?(${qualified})\\s+([\\s\\S]+)$`, 'i'));
  if (m) return clauses(m[2]).map(action => {
    const table = tableName(m[1]);
    if (/^(?:DROP|RENAME|DISABLE|DETACH|ALTER)\b/i.test(action)) return finding(/^DROP\s+COLUMN\b/i.test(action) ? 'column_dropped' : 'table_changed_destructively', table, s, true);
    const add = action.match(/^ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([\s\S]+)$/i);
    if (add && safeColumn.test(add[1]) && !/PRIMARY|NOT\s+NULL/i.test(add[1])) return finding('column_added', table, s);
    return { ...unknown(s), table, protected: protectedTables.has(table) };
  });
  // Small fully anchored additive grammar. Expressions, CTAS, procedural SQL,
  // new function calls, policies and unsupported syntax require explicit review.
  m = s.match(new RegExp(`^CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(${qualified})\\s*\\(([\\s\\S]+)\\)$`, 'i'));
  if (m && clauses(m[2]).every(c => safeColumn.test(c))) return [finding('table_added', tableName(m[1]), s)];
  m = s.match(new RegExp(`^CREATE\\s+(?:UNIQUE\\s+)?INDEX\\s+IF\\s+NOT\\s+EXISTS\\s+${name}\\s+ON\\s+(${qualified})\\s*\\(([^()]*)\\)$`, 'i'));
  if (m && clauses(m[2]).every(c => new RegExp(`^${name}(?:\\s+(?:ASC|DESC))?$`, 'i').test(c))) return [finding('index_added', tableName(m[1]), s)];
  return [unknown(s)];
}

export function classifyMigration(sql) {
  let findings;
  try { findings = splitSqlStatements(sql).flatMap(inspect); }
  catch { findings = [unknown(sql)]; }
  const destructive = findings.filter(f => f.destructive);
  const summary = {
    tablesAdded: findings.filter(f => f.kind === 'table_added').map(f => f.table),
    columnsAdded: findings.filter(f => f.kind === 'column_added').map(f => f.table),
    columnsChanged: [], destructive,
    tablesAtRisk: [...new Set(destructive.map(f => f.table).filter(Boolean))],
    protectedAtRisk: [...new Set(destructive.filter(f => f.protected).map(f => f.table))],
    dataLossRisk: destructive.length > 0,
    unknown: findings.some(f => f.unsafe),
    blocked: findings.some(f => f.destructive || f.unsafe),
  };
  return { findings, summary };
}

// Compatibility API: never summarize a compound statement as its safe prefix.
export function classifyStatement(sql) {
  const { findings, summary } = classifyMigration(sql);
  if (!findings.length) return null;
  return { ...(findings.find(f => f.destructive) || findings[0]), findings, blocked: summary.blocked };
}
export function assertSafeMigration(sql) {
  const report = classifyMigration(sql);
  if (report.summary.blocked) throw new Error('BLOCKED: destructive or UNKNOWN / UNSAFE SQL');
  return report;
}
